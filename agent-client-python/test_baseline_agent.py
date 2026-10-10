"""Tests for the rule-based agent. A fake MCP session stands in for the Go server: no Redis, binary or key."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import baseline_agent as ba
from eval_scoring import parse_ledger, score_session, split_sessions, summarize_session


def car(device, issues, slope=0.5, speed=60.0):
    return {"device_id": device, "issues": issues, "slope_per_reading": slope, "speed": speed}


def scan_reply(flagged=(), feed="ok", stale=(), spikes=()):
    return {"feed_status": feed, "flagged": list(flagged), "stale_devices": list(stale),
            "transient_spikes_ignored": list(spikes), "message": "" if feed == "ok" else f"STALE TELEMETRY ({feed})"}


class FakeSession:
    """Answers scan_fleet from a script (the last answer repeats) and records every call."""
    def __init__(self, scans, write_errors=()):
        self.scans = list(scans)
        self.calls = []
        self.write_errors = set(write_errors)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if name == "scan_fleet":
            body = self.scans.pop(0) if len(self.scans) > 1 else self.scans[0]
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(body))], is_error=False)
        if name == "send_ota_command":
            if arguments["device_id"] in self.write_errors:
                return SimpleNamespace(content=[SimpleNamespace(text="Rejected: telemetry is 19 s old")], is_error=True)
            text = (f"Success: Over-The-Air command deployed to {arguments['device_id']}. "
                    f"Register '{arguments['parameter']}' updated to '{arguments['value']}'.")
            return SimpleNamespace(content=[SimpleNamespace(text=text)], is_error=False)
        return SimpleNamespace(content=[SimpleNamespace(text="Waited 8 seconds.")], is_error=False)

    def names(self):
        return [c[0] for c in self.calls]

    def writes(self):
        return [(a["device_id"], a["parameter"], a["value"]) for n, a in self.calls if n == "send_ota_command"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    ba.SESSION.update(started=False, status="not_started")
    return tmp_path


def run(session):
    asyncio.run(ba.run_with_session(session))


def events(tmp_path):
    out = []
    for path in (tmp_path / "logs").glob("fleet_agent_ledger_*.jsonl"):
        out += parse_ledger(path.read_text())
    return out


# ---- the rules -------------------------------------------------------------------------------

def test_plan_actions_maps_issues_to_fixes():
    flagged = [car("car_001", ["battery_sustained_anomaly"]), car("car_002", ["cabin_overheating_critical"]),
               car("car_003", ["battery_rising_trend", "cabin_overheating_critical"])]
    assert ba.plan_actions(flagged, set()) == [
        ("car_001", "power_parameter", "eco_mode", "battery"),
        ("car_002", "speed_governor", "50", "cabin"),
        ("car_003", "power_parameter", "eco_mode", "battery"),
        ("car_003", "speed_governor", "50", "cabin")]


def test_plan_actions_never_repeats_a_write_and_ignores_unknown_issues():
    flagged = [car("car_001", ["battery_sustained_anomaly"]), car("car_002", ["cabin_something_else"]), car("car_003", None)]
    assert ba.plan_actions(flagged, {("car_001", "power_parameter")}) == []


def test_unresolved_rules():
    cooling = car("car_001", ["battery_sustained_anomaly"], slope=-0.8)
    heating = car("car_001", ["battery_sustained_anomaly"], slope=0.4)
    cabin = car("car_002", ["cabin_overheating_critical"], slope=-1.0)
    assert ba.unresolved([("car_001", "battery")], [cooling]) == []
    assert ba.unresolved([("car_001", "battery")], [heating]) == [("car_001", "battery")]
    assert ba.unresolved([("car_002", "cabin")], [cabin]) == [("car_002", "cabin")]
    assert ba.unresolved([("car_001", "battery")], []) == []
    # a car fixed for its cabin whose battery is still hot is not unresolved for the cabin
    both = car("car_005", ["battery_sustained_anomaly"], slope=0.6)
    assert ba.unresolved([("car_005", "cabin")], [both]) == []


# ---- whole runs ------------------------------------------------------------------------------

def test_healthy_fleet_writes_nothing_and_scans_once(isolated):
    s = FakeSession([scan_reply()])
    run(s)
    assert s.names() == ["scan_fleet"] and ba.SESSION["status"] == "completed"
    assert "No vehicle needed action" in events(isolated)[-1]["payload"]["final_summary"]


@pytest.mark.parametrize("feed", ["stale", "empty"])
def test_bad_feed_means_no_writes_and_a_stale_report(isolated, feed):
    s = FakeSession([scan_reply(feed=feed, flagged=[car("car_001", ["battery_sustained_anomaly"])])])
    run(s)
    assert s.writes() == [] and s.names() == ["scan_fleet"]
    assert "STALE TELEMETRY" in events(isolated)[-1]["payload"]["final_summary"]


def test_fixes_then_waits_then_confirms(isolated):
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"]), car("car_002", ["cabin_overheating_critical"])]),
                     scan_reply([car("car_001", ["battery_sustained_anomaly"], slope=-0.8)])])
    run(s)
    assert s.writes() == [("car_001", "power_parameter", "eco_mode"), ("car_002", "speed_governor", "50")]
    assert s.names() == ["scan_fleet", "send_ota_command", "send_ota_command", "wait_for_telemetry", "scan_fleet"]
    summary = events(isolated)[-1]["payload"]["final_summary"]
    assert "car_001 (battery): RESOLVED" in summary and "car_002 (cabin): RESOLVED" in summary


def test_dual_fault_car_gets_both_fixes(isolated):
    s = FakeSession([scan_reply([car("car_005", ["battery_sustained_anomaly", "cabin_overheating_critical"])]),
                     scan_reply([car("car_005", ["battery_sustained_anomaly"], slope=-0.7)])])
    run(s)
    assert sorted(s.writes()) == [("car_005", "power_parameter", "eco_mode"), ("car_005", "speed_governor", "50")]


def test_a_car_flagged_only_in_the_verification_scan_is_fixed_once(isolated):
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"])]),
                     scan_reply([car("car_001", ["battery_sustained_anomaly"], slope=-1.0),
                                 car("car_009", ["battery_rising_trend"])]),
                     scan_reply([car("car_009", ["battery_rising_trend"], slope=-0.5)])])
    run(s)
    assert s.writes() == [("car_001", "power_parameter", "eco_mode"), ("car_009", "power_parameter", "eco_mode")]


def test_a_fix_that_does_not_work_is_reported_unresolved_and_not_repeated(isolated):
    heating = scan_reply([car("car_001", ["battery_sustained_anomaly"], slope=0.5)])
    s = FakeSession([heating])
    run(s)
    assert s.writes() == [("car_001", "power_parameter", "eco_mode")]                   # written once
    assert s.names().count("scan_fleet") == 1 + ba.MAX_VERIFY_ROUNDS                    # then bounded re-checks
    assert "car_001 (battery): UNRESOLVED" in events(isolated)[-1]["payload"]["final_summary"]


def test_feed_going_stale_during_verification_stops_everything(isolated):
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"])]), scan_reply(feed="stale")])
    run(s)
    assert s.writes() == [("car_001", "power_parameter", "eco_mode")]
    assert s.names().count("scan_fleet") == 2
    assert "STALE TELEMETRY appeared" in events(isolated)[-1]["payload"]["final_summary"]


def test_server_refusal_is_recorded_not_retried_and_other_cars_still_fixed(isolated):
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"]), car("car_002", ["battery_sustained_anomaly"])]),
                     scan_reply([car("car_002", ["battery_sustained_anomaly"], slope=-0.9)])], write_errors={"car_001"})
    run(s)
    assert [w[0] for w in s.writes()] == ["car_001", "car_002"]
    summary = events(isolated)[-1]["payload"]["final_summary"]
    assert "refused: car_001" in summary and "car_002 (battery): RESOLVED" in summary


def test_stale_and_spike_cars_are_mentioned_but_not_touched(isolated):
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"])], stale=["car_050"], spikes=["car_020"]),
                     scan_reply([])])
    run(s)
    assert [w[0] for w in s.writes()] == ["car_001"]
    summary = events(isolated)[-1]["payload"]["final_summary"]
    assert "car_050" in summary and "car_020" in summary


# ---- the ledger is the one the scorer expects --------------------------------------------------

def test_ledger_events_have_the_same_layout_as_the_claude_agent(isolated):
    run(FakeSession([scan_reply()]))
    for event in events(isolated):
        assert set(event) == {"timestamp", "event_type", "payload"}
    kinds = [e["event_type"] for e in events(isolated)]
    assert kinds == ["SESSION_START", "TOOL_REQUESTED", "TOOL_RESPONSE", "SESSION_COMPLETED"]
    done = events(isolated)[-1]["payload"]
    assert done["total_input_tokens"] == 0 and done["turns"] == 1


def test_scorer_passes_a_correct_baseline_run_on_dual_and_silent_faulty_cases(isolated):
    manifest = {"battery": ["car_001"], "cabin": [], "dual": ["car_005"], "spikes": [], "silent": ["car_002"],
                "silent_faulty": ["car_002"], "freeze_after": None}
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"]),
                                 car("car_005", ["battery_sustained_anomaly", "cabin_overheating_critical"])], stale=["car_002"]),
                     scan_reply([car("car_001", ["battery_sustained_anomaly"], slope=-0.8),
                                 car("car_005", ["battery_sustained_anomaly"], slope=-0.7)])])
    run(s)
    result = score_session(manifest, summarize_session(split_sessions(events(isolated))[-1]))
    assert result["passed"], result["reasons"]
    assert result["input_tokens"] == 0 and len(result["fixed"]) == 3


def test_scorer_passes_a_baseline_dead_feed_run(isolated):
    run(FakeSession([scan_reply(feed="stale")]))
    result = score_session({"battery": [], "cabin": [], "dual": [], "freeze_after": 35},
                           summarize_session(split_sessions(events(isolated))[-1]))
    assert result["passed"], result["reasons"]


# ---- crashes ---------------------------------------------------------------------------------

def test_startup_failure_is_logged_and_exits_1(isolated, monkeypatch, capsys):
    async def boom():
        raise FileNotFoundError("./mcp-server-go/mcp-server-go-binary")
    monkeypatch.setattr(ba, "main_async", boom)
    assert ba.main() == 1
    assert events(isolated)[-1]["event_type"] == "STARTUP_FAILED"
    assert "make build" in capsys.readouterr().err


def test_crash_after_session_start_is_logged_as_aborted(isolated, monkeypatch):
    def broken_parse(text):
        raise RuntimeError("parser exploded")
    monkeypatch.setattr(ba, "parse_feed_status", broken_parse)

    async def go():
        await ba.run_with_session(FakeSession([scan_reply()]))
    monkeypatch.setattr(ba, "main_async", go)
    assert ba.main() == 1
    last = events(isolated)[-1]
    assert last["event_type"] == "SESSION_ABORTED" and last["payload"]["reason"] == "exception"
    assert "parser exploded" in last["payload"]["error"]


def test_a_failing_scan_call_is_treated_as_no_data_and_changes_nothing(isolated):
    class ScanDown(FakeSession):
        async def call_tool(self, name, arguments=None):
            self.calls.append((name, arguments))
            raise ConnectionError("server gone")
    s = ScanDown([scan_reply()])
    run(s)
    assert s.writes() == []
    assert "STALE TELEMETRY" in events(isolated)[-1]["payload"]["final_summary"]


def test_exit_code_is_2_when_the_session_never_completes(isolated, monkeypatch):
    async def quiet():
        return None
    monkeypatch.setattr(ba, "main_async", quiet)
    assert ba.main() == 2


def test_a_write_that_fails_the_payload_check_is_logged_and_never_sent(isolated, monkeypatch):
    monkeypatch.setattr(ba, "validate_ota_payload", lambda payload: (False, "Guardrail Violation: test"))
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"])])])
    run(s)
    assert s.writes() == []
    assert "GUARDRAIL_VIOLATION" in [e["event_type"] for e in events(isolated)]
    assert "refused: car_001" in events(isolated)[-1]["payload"]["final_summary"]


def test_a_write_is_never_sent_when_the_feed_check_fails(isolated, monkeypatch):
    monkeypatch.setattr(ba, "check_feed_allows_writes", lambda status: (False, "Guardrail Violation: stale"))
    s = FakeSession([scan_reply([car("car_001", ["battery_sustained_anomaly"])])])
    run(s)
    assert s.writes() == []
