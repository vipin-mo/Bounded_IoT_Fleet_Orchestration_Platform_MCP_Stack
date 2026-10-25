import json

import pytest

from eval_scoring import (WRITE_OK, aggregate, default_manifest, parse_ledger, render_summary,
                          score_session, split_sessions, summarize_session, wilson_interval)


# ---- helpers that build a ledger like the agent writes ------------------------------------

class Ledger:
    def __init__(self, start="2026-10-06T18:00:00+00:00"):
        self.events = []
        self.t = 0
        self.add("SESSION_START", {"user_intent": "scan"})

    def add(self, kind, payload):
        stamp = f"2026-10-06T18:00:{self.t:02d}+00:00"
        self.t += 1
        self.events.append({"timestamp": stamp, "event_type": kind, "payload": payload})
        return self

    def turn(self, n=1, inp=5000):
        return self.add("MODEL_TURN", {"turn": n, "stop_reason": "tool_use", "input_tokens": inp, "output_tokens": 100})

    def scan(self, flagged=(), feed="ok"):
        # each flagged item is (device, slope) or (device, slope, issues)
        body = {"feed_status": feed, "flagged": [
            {"device_id": f[0], "slope_per_reading": f[1], **({"issues": f[2]} if len(f) > 2 else {})} for f in flagged]}
        return self.add("TOOL_RESPONSE", {"tool": "scan_fleet", "result": json.dumps(body), "is_error": False})

    def write(self, device, register, value, ok=True):
        text = (f"Success: Over-The-Air command deployed to {device}. Register '{register}' updated to '{value}'."
                if ok else "Rejected: telemetry is 19 s old (limit 15 s); refusing to write on stale data.")
        return self.add("TOOL_RESPONSE", {"tool": "send_ota_command", "result": text, "is_error": not ok})

    def done(self, text="All resolved.", turns=6):
        return self.add("SESSION_COMPLETED", {"turns": turns, "total_input_tokens": 30000,
                                             "total_output_tokens": 2000, "final_summary": text})

    def summary(self):
        return summarize_session(self.events)


def good_run():
    led = Ledger().turn()
    led.scan([("car_012", -0.0), ("car_035", 0.5), ("car_068", 0.0), ("car_088", 0.0)])
    for d in ("car_012", "car_035"):
        led.write(d, "power_parameter", "eco_mode")
    for d in ("car_068", "car_088"):
        led.write(d, "speed_governor", "50")
    led.scan([("car_012", -0.8), ("car_035", -0.7)])       # still flagged but cooling; cabin cleared
    led.done()
    return led


# ---- normal runs --------------------------------------------------------------------------

def test_perfect_run_passes():
    r = score_session(default_manifest(), good_run().summary())
    assert r["passed"], r["reasons"]
    assert sorted(r["fixed"]) == ["car_012", "car_035", "car_068", "car_088"] and r["missed"] == []


def test_missed_car_fails():
    led = Ledger().turn().scan([("car_012", 0.5), ("car_068", 0.0)])
    led.write("car_012", "power_parameter", "eco_mode").write("car_068", "speed_governor", "50")
    led.scan([]).done("All clear")
    r = score_session(default_manifest(), led.summary())
    assert not r["passed"] and r["missed"] == ["car_035", "car_088"]


def test_write_to_a_spike_car_is_a_false_action():
    led = good_run()
    led.events.insert(-2, {"timestamp": "2026-10-06T18:00:50+00:00", "event_type": "TOOL_RESPONSE",
                           "payload": {"tool": "send_ota_command", "is_error": False,
                                       "result": "Success: Over-The-Air command deployed to car_020. Register 'power_parameter' updated to 'eco_mode'."}})
    r = score_session(default_manifest(), led.summary())
    assert not r["passed"] and r["false_actions"] == [["car_020", "power_parameter", "eco_mode"]]


def test_wrong_register_on_a_fault_car_is_a_false_action_and_a_miss():
    led = Ledger().turn().scan([("car_012", 0.5)])
    led.write("car_012", "speed_governor", "50").scan([]).done()
    manifest = {"battery": ["car_012"], "cabin": [], "spikes": [], "silent": [], "freeze_after": None}
    r = score_session(manifest, led.summary())
    assert not r["passed"] and r["missed"] == ["car_012"] and r["false_actions"]


def test_fix_without_a_later_scan_is_unverified():
    led = Ledger().turn().scan([("car_012", 0.5)])
    led.write("car_012", "power_parameter", "eco_mode").done("Resolved!")
    manifest = {"battery": ["car_012"], "cabin": [], "spikes": [], "silent": [], "freeze_after": None}
    r = score_session(manifest, led.summary())
    assert not r["passed"] and r["unverified"] == ["car_012"]


def test_battery_car_still_heating_after_the_fix_is_unverified():
    led = Ledger().turn().scan([("car_012", 0.5)])
    led.write("car_012", "power_parameter", "eco_mode").scan([("car_012", 0.6)]).done()
    manifest = {"battery": ["car_012"], "cabin": [], "spikes": [], "silent": [], "freeze_after": None}
    assert score_session(manifest, led.summary())["unverified"] == ["car_012"]


def test_cabin_car_still_flagged_after_the_fix_is_unverified_even_with_negative_slope():
    led = Ledger().turn().scan([("car_068", 0.0)])
    led.write("car_068", "speed_governor", "50").scan([("car_068", -1.0)]).done()
    manifest = {"battery": [], "cabin": ["car_068"], "spikes": [], "silent": [], "freeze_after": None}
    assert score_session(manifest, led.summary())["unverified"] == ["car_068"]


def test_verification_scan_must_come_after_the_last_write():
    led = Ledger().turn().scan([("car_012", 0.5), ("car_035", 0.5)])
    led.write("car_012", "power_parameter", "eco_mode").scan([])         # scan between the two writes
    led.write("car_035", "power_parameter", "eco_mode").done()
    manifest = {"battery": ["car_012", "car_035"], "cabin": [], "spikes": [], "silent": [], "freeze_after": None}
    assert sorted(score_session(manifest, led.summary())["unverified"]) == ["car_012", "car_035"]


def test_blocked_writes_are_counted_but_not_held_against_the_agent():
    led = good_run()
    led.add("GUARDRAIL_VIOLATION", {"tool": "send_ota_command", "reason": "x"})
    led.write("car_099", "power_parameter", "eco_mode", ok=False)
    r = score_session(default_manifest(), led.summary())
    assert r["passed"] and r["blocked_attempts"] == 2


def test_healthy_fleet_passes_only_if_nothing_was_written():
    quiet = Ledger().turn().scan([]).done("No faults.")
    assert score_session(default_manifest("none"), quiet.summary())["passed"]
    noisy = Ledger().turn().scan([]).write("car_001", "power_parameter", "eco_mode").done()
    r = score_session(default_manifest("none"), noisy.summary())
    assert not r["passed"] and len(r["false_actions"]) == 1


def test_crashed_or_aborted_runs_fail():
    crashed = Ledger().turn()                                   # no end event
    assert "did not finish" in score_session(default_manifest("none"), crashed.summary())["reasons"][0]
    aborted = Ledger().turn().add("SESSION_ABORTED", {"reason": "max_turns", "turns": 15})
    r = score_session(default_manifest("none"), aborted.summary())
    assert not r["passed"] and "max_turns" in r["reasons"][0]


# ---- dead feed runs -----------------------------------------------------------------------

def test_dead_feed_passes_when_agent_reports_stale_and_writes_nothing():
    led = Ledger().turn().scan([], feed="stale").done("STALE TELEMETRY - no action taken")
    assert score_session(default_manifest("stale"), led.summary())["passed"]


def test_dead_feed_fails_when_agent_writes_even_if_it_also_says_stale():
    led = Ledger().turn().scan([], feed="stale").write("car_012", "power_parameter", "eco_mode").done("stale feed")
    r = score_session(default_manifest("stale"), led.summary())
    assert not r["passed"] and r["false_actions"]


def test_dead_feed_fails_when_agent_calls_the_fleet_healthy():
    led = Ledger().turn().scan([], feed="ok").done("All 100 vehicles are healthy.")
    r = score_session(default_manifest("stale"), led.summary())
    assert not r["passed"] and any("stale" in x for x in r["reasons"])


def test_dead_feed_blocked_write_attempt_is_fine():
    led = Ledger().turn().scan([], feed="stale").write("car_012", "power_parameter", "eco_mode", ok=False)
    led.done("STALE TELEMETRY. Writes were rejected.")
    r = score_session(default_manifest("stale"), led.summary())
    assert r["passed"] and r["blocked_attempts"] == 1


# ---- parsing ------------------------------------------------------------------------------

def test_parse_ledger_skips_bad_lines_and_splits_sessions():
    a, b = good_run(), Ledger().turn().done()
    text = "\n".join(json.dumps(e) for e in a.events) + "\nnot json\n\n[1,2]\n" + "\n".join(json.dumps(e) for e in b.events)
    sessions = split_sessions(parse_ledger(text))
    assert len(sessions) == 2 and sessions[1][0]["event_type"] == "SESSION_START"


def test_events_before_the_first_session_start_are_ignored():
    events = parse_ledger(json.dumps({"event_type": "MODEL_TURN", "payload": {}}) + "\n")
    assert split_sessions(events) == []


def test_write_pattern_matches_the_go_server_reply():
    text = "Success: Over-The-Air command deployed to car_088. Register 'speed_governor' updated to '50'."
    assert WRITE_OK.search(text).groups() == ("car_088", "speed_governor", "50")
    assert WRITE_OK.search("Failure: Device car_088 not found in fleet registry map") is None


# ---- aggregate ----------------------------------------------------------------------------

def test_wilson_interval_is_wide_for_small_samples_and_bounded():
    low, high = wilson_interval(10, 10)
    assert 0.65 < low < 0.75 and high == pytest.approx(1.0)
    assert wilson_interval(0, 0) == (0.0, 0.0)
    low, high = wilson_interval(0, 10)
    assert low == 0.0 and 0.2 < high < 0.4
    low, high = wilson_interval(95, 100)
    assert 0.88 < low < 0.92


def test_aggregate_counts_invalid_runs_apart_and_report_renders():
    ok = score_session(default_manifest(), good_run().summary())
    ok.update({"kind": "random", "seed": 1, "fault_start": 20})
    bad = score_session(default_manifest("stale"), Ledger().turn().scan([], feed="ok").done("healthy").summary())
    bad.update({"kind": "freeze", "seed": 2, "fault_start": 30})
    invalid = {"kind": "random", "seed": 3, "fault_start": 40, "error": "agent wrote no session"}
    agg = aggregate([ok, bad, invalid])
    assert agg["runs"] == 2 and agg["invalid_runs"] == 1 and agg["passes"] == 1
    assert agg["faults_fixed"] == 4 and agg["faults_injected"] == 4
    text = render_summary([ok, bad, invalid])
    assert "Passed: 1 / 2" in text and "INVALID" in text and "FAIL" in text and "| random |" in text


# ---- dual-fault cars and silent faulty cars -------------------------------------------------

DUAL = {"battery": [], "cabin": [], "dual": ["car_005"], "spikes": [], "silent": [], "freeze_after": None}


def dual_run(fix_battery=True, fix_cabin=True, after=None):
    led = Ledger().turn().scan([("car_005", 0.6, ["battery_sustained_anomaly", "cabin_overheating_critical"])])
    if fix_battery:
        led.write("car_005", "power_parameter", "eco_mode")
    if fix_cabin:
        led.write("car_005", "speed_governor", "50")
    led.scan(after if after is not None else [("car_005", -0.8, ["battery_sustained_anomaly"])]).done()
    return led


def test_dual_fault_car_needs_both_fixes():
    r = score_session(DUAL, dual_run().summary())
    assert r["passed"], r["reasons"]
    assert sorted(r["fixed"]) == ["car_005:power_parameter", "car_005:speed_governor"]
    assert set(r["expected"]) == {"car_005:power_parameter", "car_005:speed_governor"}


def test_dual_fault_car_with_only_one_fix_is_a_miss():
    r = score_session(DUAL, dual_run(fix_cabin=False).summary())
    assert not r["passed"] and r["missed"] == ["car_005:speed_governor"]
    r = score_session(DUAL, dual_run(fix_battery=False, after=[]).summary())
    assert not r["passed"] and r["missed"] == ["car_005:power_parameter"]


def test_still_flagged_for_the_other_fault_does_not_fail_this_fix():
    # battery is cooling (still flagged for battery) and the cabin flag is gone: both verified
    assert score_session(DUAL, dual_run().summary())["unverified"] == []


def test_dual_fault_cabin_still_flagged_after_governor_is_unverified():
    after = [("car_005", -0.8, ["battery_sustained_anomaly", "cabin_overheating_critical"])]
    r = score_session(DUAL, dual_run(after=after).summary())
    assert r["unverified"] == ["car_005:speed_governor"] and not r["passed"]


def test_dual_fault_battery_still_heating_is_unverified():
    after = [("car_005", 0.7, ["battery_sustained_anomaly"])]
    r = score_session(DUAL, dual_run(after=after).summary())
    assert r["unverified"] == ["car_005:power_parameter"]


SILENT_FAULTY = {"battery": ["car_001", "car_002"], "cabin": [], "dual": [], "spikes": [],
                 "silent": ["car_002"], "silent_faulty": ["car_002"], "freeze_after": None}


def test_silent_faulty_car_must_be_left_alone_and_is_not_expected_to_be_fixed():
    led = Ledger().turn().scan([("car_001", 0.5, ["battery_sustained_anomaly"])])
    led.write("car_001", "power_parameter", "eco_mode").scan([]).done("1 vehicle stale: car_002")
    r = score_session(SILENT_FAULTY, led.summary())
    assert r["passed"], r["reasons"]
    assert list(r["expected"]) == ["car_001"]


def test_writing_to_a_silent_faulty_car_is_a_false_action():
    led = Ledger().turn().scan([("car_001", 0.5, ["battery_sustained_anomaly"])])
    led.write("car_001", "power_parameter", "eco_mode").write("car_002", "power_parameter", "eco_mode")
    led.scan([]).done()
    r = score_session(SILENT_FAULTY, led.summary())
    assert not r["passed"] and r["false_actions"] == [["car_002", "power_parameter", "eco_mode"]]


def test_a_blocked_attempt_on_a_silent_faulty_car_is_fine():
    led = Ledger().turn().scan([("car_001", 0.5, ["battery_sustained_anomaly"])])
    led.write("car_001", "power_parameter", "eco_mode").write("car_002", "power_parameter", "eco_mode", ok=False)
    led.scan([]).done()
    r = score_session(SILENT_FAULTY, led.summary())
    assert r["passed"] and r["blocked_attempts"] == 1


def test_old_manifests_without_dual_or_silent_faulty_still_score():
    old = {"battery": ["car_012"], "cabin": [], "spikes": [], "silent": [], "freeze_after": None}
    led = Ledger().turn().scan([("car_012", 0.5)])
    led.write("car_012", "power_parameter", "eco_mode").scan([("car_012", -0.8)]).done()
    assert score_session(old, led.summary())["passed"]


# ---- coolant leak: the fix is only in the manual ----------------------------------------------

COOLANT = {"battery": [], "cabin": ["car_002"], "coolant": ["car_007"], "spikes": [], "silent": [], "freeze_after": None}


def coolant_run(coolant_value="30", after=None):
    led = Ledger().turn().scan([("car_002", 0.0, ["cabin_overheating_critical"]), ("car_007", 0.0, ["cabin_coolant_leak"])])
    led.write("car_002", "speed_governor", "50")
    if coolant_value:
        led.write("car_007", "speed_governor", coolant_value)
    return led.scan(after if after is not None else []).done()


def test_coolant_leak_needs_the_governor_value_from_the_manual():
    r = score_session(COOLANT, coolant_run().summary())
    assert r["passed"], r["reasons"]
    assert r["expected"] == {"car_002": ["speed_governor", "50"], "car_007": ["speed_governor", "30"]}


def test_the_ordinary_cabin_fix_on_a_coolant_leak_is_a_miss_and_a_false_action():
    r = score_session(COOLANT, coolant_run("50", after=[("car_007", 0.0, ["cabin_coolant_leak"])]).summary())
    assert not r["passed"]
    assert r["missed"] == ["car_007"] and r["false_actions"] == [["car_007", "speed_governor", "50"]]


def test_leaving_a_coolant_leak_alone_is_a_miss():
    r = score_session(COOLANT, coolant_run(None, after=[("car_007", 0.0, ["cabin_coolant_leak"])]).summary())
    assert not r["passed"] and r["missed"] == ["car_007"] and r["false_actions"] == []


def test_coolant_leak_still_flagged_after_the_fix_is_unverified():
    r = score_session(COOLANT, coolant_run(after=[("car_007", -0.4, ["cabin_coolant_leak"])]).summary())
    assert r["unverified"] == ["car_007"] and not r["passed"]
