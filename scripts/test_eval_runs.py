import json
from pathlib import Path

import eval_runs as ev
from test_eval_scoring import Ledger


def test_suite_is_deterministic_and_has_controls():
    a, b = ev.build_suite(20, 1000), ev.build_suite(20, 1000)
    assert a == b and len({c["seed"] for c in a}) == 20
    kinds = [c["kind"] for c in a]
    for kind in ("random", "none", "spikes_only", "silent", "freeze"):
        assert kinds.count(kind) >= 2
    assert all(c["fault_start"] >= 20 for c in a)                 # the detector needs a baseline first
    assert ev.build_suite(20, 2000) != a


def test_freeze_cases_freeze_after_faults_start_and_wait_until_the_feed_is_old():
    for c in ev.build_suite(20, 1):
        if c["kind"] == "freeze":
            assert c["freeze_after"] > c["fault_start"]
            assert ev.wait_seconds(c, 15) - c["freeze_after"] >= 16      # older than the 15 s limit
        else:
            assert c["freeze_after"] is None


def test_silent_cases_wait_long_enough_for_silent_cars_to_go_stale():
    for c in ev.build_suite(20, 1):
        if c["silent_cars"]:
            assert ev.wait_seconds(c, 15) - c["fault_start"] >= 16


def test_simulator_command_carries_the_case_options():
    case = {"seed": 7, "fault_start": 30, "profile": "random", "silent_cars": 5, "freeze_after": 45}
    cmd = ev.simulator_command(case, Path("m.json"))
    assert ["--seed", "7"] == cmd[cmd.index("--seed"):cmd.index("--seed") + 2]
    assert "--silent-cars" in cmd and "--freeze-after" in cmd and "--manifest" in cmd
    plain = ev.simulator_command({"seed": 1, "fault_start": 20, "profile": "none", "silent_cars": 0, "freeze_after": None}, Path("m.json"))
    assert "--silent-cars" not in plain and "--freeze-after" not in plain


def _fake_start(manifest):
    def start(case, case_dir):
        path = case_dir / "manifest.json"
        path.write_text(json.dumps(manifest))
        return "proc", path
    return start


def test_run_case_scores_the_last_session_and_always_stops_the_simulator(tmp_path):
    stopped = []
    case = ev.build_suite(1, 1)[0]
    manifest = {"battery": ["car_012"], "cabin": [], "spikes": [], "silent": [], "freeze_after": None}
    led = Ledger().turn().scan([("car_012", 0.5)])
    led.write("car_012", "power_parameter", "eco_mode").scan([("car_012", -0.8)]).done()
    text = "\n".join(json.dumps(e) for e in led.events)

    result = ev.run_case(case, tmp_path / "c", lead=15, agent_timeout=1, sleep=lambda s: None,
                         start=_fake_start(manifest), stop=stopped.append, agent=lambda d, t: (0, text))
    assert result["passed"] and result["seed"] == case["seed"] and stopped == ["proc"]

    def exploding_agent(d, t):
        raise OSError("boom")
    stopped.clear()
    try:
        ev.run_case(case, tmp_path / "d", 15, 1, sleep=lambda s: None, start=_fake_start(manifest),
                    stop=stopped.append, agent=exploding_agent)
    except OSError:
        pass
    assert stopped == ["proc"]                                   # the simulator is stopped even on error


def test_run_case_marks_a_run_without_a_session_as_invalid_not_failed(tmp_path):
    case = ev.build_suite(1, 1)[0]
    result = ev.run_case(case, tmp_path / "e", 15, 1, sleep=lambda s: None,
                         start=_fake_start({"battery": []}), stop=lambda p: None, agent=lambda d, t: (1, ""))
    assert "error" in result and "no session" in result["error"]


def test_run_case_reports_a_simulator_that_would_not_start(tmp_path):
    def broken_start(case, case_dir):
        raise RuntimeError("simulator exited early")
    case = ev.build_suite(1, 1)[0]
    result = ev.run_case(case, tmp_path / "f", 15, 1, sleep=lambda s: None, start=broken_start)
    assert result["error"] == "simulator exited early"


def test_score_existing_ledger_with_session_filter(tmp_path, capsys):
    good = Ledger().turn().scan([]).done("No faults.")
    stale = Ledger("x").turn().scan([], feed="stale").done("STALE TELEMETRY")
    stale.events[0]["timestamp"] = "2026-10-06T19:00:00+00:00"
    path = tmp_path / "l.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in good.events + stale.events))
    args = ev.parse_args(["--score-ledger", str(path), "--expect", "stale", "--session-start", "2026-10-06T19"])
    assert ev.score_existing(args) == 0
    out = capsys.readouterr().out
    assert "Passed: 1 / 1" in out
    args = ev.parse_args(["--score-ledger", str(path), "--session-start", "1999"])
    assert ev.score_existing(args) == 1


def test_startup_failure_is_reported_as_the_reason_for_an_invalid_case():
    case = ev.build_suite(1, 1)[0]
    text = json.dumps({"timestamp": "2026-10-06T18:00:00+00:00", "event_type": "STARTUP_FAILED",
                       "payload": {"error": "The Go MCP server stopped while starting. Run 'make up'.\nDetail: x"}})
    result = ev.score_case(case, {"battery": []}, text, 1)
    assert "error" in result and "make up" in result["error"] and "exit code 1" in result["error"]


def test_only_flag_is_parsed():
    assert ev.parse_args(["--only", "freeze,silent"]).only == "freeze,silent"
    assert ev.parse_args([]).only is None


def test_a_crashed_run_is_invalid_and_keeps_the_error_text():
    case = ev.build_suite(1, 1)[0]
    led = Ledger().turn()
    led.add("SESSION_ABORTED", {"reason": "exception",
                                "error": "The Anthropic API rejected the key. Check ANTHROPIC_API_KEY in .env.\nDetail: AuthenticationError: 401"})
    text = "\n".join(json.dumps(e) for e in led.events)
    result = ev.score_case(case, {"battery": ["car_001"]}, text, 1)
    assert "passed" not in result
    assert "ANTHROPIC_API_KEY" in result["error"] and "\n" not in result["error"]


def test_a_turn_limit_abort_is_still_scored_as_a_failure_not_invalid():
    case = ev.build_suite(1, 1)[0]
    led = Ledger().turn().add("SESSION_ABORTED", {"reason": "max_turns", "turns": 15})
    text = "\n".join(json.dumps(e) for e in led.events)
    result = ev.score_case(case, {"battery": ["car_001"]}, text, 2)
    assert result["passed"] is False


def test_suite_stops_after_repeated_invalid_cases(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ev, "preflight", lambda: None)
    calls = []

    def fake_run_case(case, case_dir, lead, timeout):
        calls.append(case["index"])
        return {"index": case["index"], "kind": case["kind"], "seed": case["seed"],
                "fault_start": case["fault_start"], "error": "agent crashed: AuthenticationError"}
    monkeypatch.setattr(ev, "run_case", fake_run_case)
    assert ev.main(["--runs", "10", "--out", str(tmp_path)]) == 0
    assert calls == [1, 2, 3]
    assert "Stopping: 3 invalid cases in a row" in capsys.readouterr().out


def test_valid_cases_reset_the_invalid_streak(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "preflight", lambda: None)
    outcomes = iter(["bad", "bad", "good", "bad", "bad", "good"])
    seen = []

    def fake_run_case(case, case_dir, lead, timeout):
        seen.append(case["index"])
        base = {"index": case["index"], "kind": case["kind"], "seed": case["seed"], "fault_start": case["fault_start"]}
        if next(outcomes) == "bad":
            return {**base, "error": "x"}
        return {**base, "passed": True, "mode": "normal", "expected": {}, "fixed": [], "missed": [],
                "false_actions": [], "unverified": [], "reasons": [], "blocked_attempts": 0,
                "turns": 4, "input_tokens": 1, "duration_s": 1.0}
    monkeypatch.setattr(ev, "run_case", fake_run_case)
    ev.main(["--runs", "6", "--out", str(tmp_path)])
    assert seen == [1, 2, 3, 4, 5, 6]
