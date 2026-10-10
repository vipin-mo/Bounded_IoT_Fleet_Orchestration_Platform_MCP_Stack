import json

import fakeredis
import pytest

import simulator
from fleet_model import (
    BATTERY_RUNAWAY, CABIN_INVERTER, TRANSIENT_SPIKE, DEFAULT_SCENARIOS, PROFILES,
    MAX_HEAT, SPIKE_EVERY, FleetModel, build_profile,
)

FAULT_START = 30


def run(model, ticks, overrides_for=None, start=0):
    """Run `ticks` ticks and return a list (one entry per tick) of {device_id: reading}."""
    history = []
    for tick in range(start, start + ticks):
        overrides = overrides_for(tick) if overrides_for else None
        history.append({s["device_id"]: s for s in model.step(tick, overrides)})
    return history


def series(history, device_id, key):
    return [h[device_id][key] for h in history]


def test_same_seed_gives_identical_runs():
    a = run(FleetModel(seed=7, fault_start_tick=FAULT_START), 80)
    b = run(FleetModel(seed=7, fault_start_tick=FAULT_START), 80)
    c = run(FleetModel(seed=8, fault_start_tick=FAULT_START), 80)
    assert a == b
    assert a != c


def test_healthy_cars_stay_in_normal_band():
    history = run(FleetModel(fault_start_tick=FAULT_START), 150)
    healthy = [d for i, d in enumerate(FleetModel().device_ids) if i not in DEFAULT_SCENARIOS]
    for device_id in healthy:
        temps = series(history, device_id, "battery_temp")
        assert 25.0 < min(temps) and max(temps) < 38.0
        assert set(series(history, device_id, "cabin_status")) == {"nominal"}


def test_battery_fault_is_flat_then_ramps_and_caps():
    model = FleetModel(fault_start_tick=FAULT_START)
    history = run(model, 140)
    temps = series(history, "car_012", "battery_temp")
    base = min(temps[:FAULT_START])
    assert max(temps[:FAULT_START]) - base < 1.5                # flat before the fault
    assert temps[FAULT_START + 10] - base > 4.0                 # ramping after it
    assert max(temps) <= base + MAX_HEAT + 2.0                  # capped
    assert series(history, "car_012", "cabin_status")[-1] == "nominal"


def test_eco_mode_stops_heating_and_cools_the_battery():
    model = FleetModel(fault_start_tick=FAULT_START)
    eco_from = FAULT_START + 20

    def overrides(tick):
        return {"car_012": {"power_parameter": "eco_mode"}} if tick >= eco_from else None

    history = run(model, 120, overrides)
    temps = series(history, "car_012", "battery_temp")
    peak = max(temps)
    assert temps[eco_from + 5] < temps[eco_from]                # already falling after 5 ticks
    assert temps[-1] < peak - 8.0                               # and far below the peak at the end
    # a sibling with no mitigation keeps heating
    assert series(history, "car_035", "battery_temp")[-1] > temps[-1] + 8.0


def test_cabin_fault_then_governor_clears_status_and_caps_speed():
    model = FleetModel(fault_start_tick=FAULT_START)
    gov_from = FAULT_START + 10

    def overrides(tick):
        return {"car_068": {"speed_governor": "50"}} if tick >= gov_from else None

    history = run(model, 80, overrides)
    status = series(history, "car_068", "cabin_status")
    speed = series(history, "car_068", "speed")
    assert status[FAULT_START + 5] == "overheating_critical"
    assert speed[FAULT_START + 5] >= 65.0
    assert max(speed[gov_from:]) <= 50.0                        # capped at once
    assert status[gov_from + 10] == "nominal"                   # cleared after the recovery delay
    assert series(history, "car_088", "cabin_status")[-1] == "overheating_critical"  # no governor, still faulty


def test_transient_spike_is_one_reading_only():
    model = FleetModel(fault_start_tick=FAULT_START)
    history = run(model, FAULT_START + 3 * SPIKE_EVERY + 1)
    temps = series(history, "car_020", "battery_temp")
    base = sorted(temps[:FAULT_START])[FAULT_START // 2]
    hot = [i for i, t in enumerate(temps) if t - base > 8.0]
    assert hot == [FAULT_START + k * SPIKE_EVERY for k in range(4)]


def test_garbage_governor_value_is_ignored():
    model = FleetModel(fault_start_tick=FAULT_START)
    history = run(model, 40, lambda t: {"car_000": {"speed_governor": "fast"}})
    assert all(isinstance(s, float) for s in series(history, "car_000", "speed"))


# ---- Redis writer (fakeredis; no server needed) -------------------------------------------

@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


def test_write_tick_keeps_history_window_and_registers_devices(redis_client):
    model = FleetModel(cars=10, fault_start_tick=FAULT_START)
    for tick in range(simulator.HISTORY_WINDOW + 25):
        simulator.write_tick(redis_client, model.step(tick), timestamp=1_700_000_000 + tick)

    assert redis_client.llen("logs:car_003") == simulator.HISTORY_WINDOW
    newest = json.loads(redis_client.lindex("logs:car_003", 0))
    assert newest["timestamp"] == 1_700_000_000 + simulator.HISTORY_WINDOW + 24
    assert redis_client.smembers(simulator.DEVICE_SET_KEY) == set(model.device_ids)
    assert redis_client.hget("device:car_003", "cabin_status") == "nominal"
    assert redis_client.hget("device:car_003", "updated_at") == str(1_700_000_000 + simulator.HISTORY_WINDOW + 24)


def test_agent_registers_survive_telemetry_writes_and_are_read_back(redis_client):
    model = FleetModel(cars=10, fault_start_tick=FAULT_START)
    simulator.write_tick(redis_client, model.step(0), timestamp=1)
    redis_client.hset("device:car_001", "power_parameter", "eco_mode")   # what the Go server does
    simulator.write_tick(redis_client, model.step(1), timestamp=2)

    overrides = simulator.read_overrides(redis_client, model.device_ids)
    assert overrides["car_001"]["power_parameter"] == "eco_mode"
    assert overrides["car_002"]["power_parameter"] is None


def test_reset_fleet_clears_old_state(redis_client):
    model = FleetModel(cars=5, fault_start_tick=FAULT_START)
    simulator.write_tick(redis_client, model.step(0), timestamp=1)
    redis_client.hset("device:car_001", "power_parameter", "eco_mode")
    simulator.reset_fleet(redis_client)
    assert redis_client.keys("*") == []


# ---- Test layouts (profiles) --------------------------------------------------------------

def count(scenarios, kind):
    return sum(1 for s in scenarios.values() if s == kind)


def test_default_profile_is_the_original_fixed_layout_and_keeps_old_runs_identical():
    scenarios, silent = build_profile("default", 100, seed=999)
    assert scenarios == DEFAULT_SCENARIOS and silent == set()
    old = run(FleetModel(seed=7, fault_start_tick=FAULT_START), 80)
    new = run(FleetModel(seed=7, fault_start_tick=FAULT_START, scenarios=scenarios), 80)
    assert old == new


@pytest.mark.parametrize("profile", PROFILES)
def test_profiles_are_deterministic_and_use_distinct_cars(profile):
    a = build_profile(profile, 100, seed=11, silent_cars=4)
    b = build_profile(profile, 100, seed=11, silent_cars=4)
    assert a == b
    scenarios, silent = a
    assert len(silent) == 4
    assert not (silent & {f"car_{i:03d}" for i in scenarios})      # silent cars are healthy cars
    assert all(0 <= i < 100 for i in scenarios)


def test_random_profile_changes_with_the_seed_and_always_has_a_real_fault():
    layouts = set()
    for seed in range(60):
        scenarios, _ = build_profile("random", 100, seed)
        assert count(scenarios, BATTERY_RUNAWAY) + count(scenarios, CABIN_INVERTER) >= 1
        layouts.add(tuple(sorted(scenarios.items())))
    assert len(layouts) > 40


def test_profile_kinds_match_their_names():
    for seed in range(20):
        none, _ = build_profile("none", 100, seed)
        spikes, _ = build_profile("spikes_only", 100, seed)
        battery, _ = build_profile("battery_only", 100, seed)
        cabin, _ = build_profile("cabin_only", 100, seed)
        assert none == {}
        assert set(spikes.values()) == {TRANSIENT_SPIKE}
        assert set(battery.values()) == {BATTERY_RUNAWAY}
        assert set(cabin.values()) == {CABIN_INVERTER}


def test_choosing_a_profile_does_not_change_the_starting_conditions_of_cars():
    # base temperature and speed come from the physics generator. The layout uses its own generator,
    # so every profile starts every car from the same values for the same seed.
    default = FleetModel(seed=5, scenarios=build_profile("default", 100, 5)[0])
    random_ = FleetModel(seed=5, scenarios=build_profile("random", 100, 5)[0])
    none = FleetModel(seed=5, scenarios=build_profile("none", 100, 5)[0])
    for i in range(100):
        assert default.cars[i].base_temp == random_.cars[i].base_temp == none.cars[i].base_temp
        assert default.cars[i].base_speed == random_.cars[i].base_speed == none.cars[i].base_speed


def test_profile_errors():
    with pytest.raises(ValueError):
        build_profile("chaos", 100, 1)
    with pytest.raises(ValueError):
        build_profile("random", 5, 1, silent_cars=10)
    with pytest.raises(ValueError):
        build_profile("default", 30, 1, silent_cars=29)


def test_manifest_lists_the_ground_truth():
    scenarios, silent = build_profile("default", 100, 1, silent_cars=3)
    manifest = FleetModel(seed=1, fault_start_tick=40, scenarios=scenarios, silent_ids=silent).manifest()
    assert manifest["battery"] == ["car_012", "car_035"]
    assert manifest["cabin"] == ["car_068", "car_088"]
    assert manifest["spikes"] == ["car_020", "car_050"]
    assert len(manifest["silent"]) == 3 and manifest["fault_start_tick"] == 40


# ---- Silent cars, frozen feed and the run loop (fakeredis) --------------------------------

def test_filter_states_rules():
    states = [{"device_id": "car_001"}, {"device_id": "car_002"}]
    assert simulator.filter_states(states, 5, 20, {"car_002"}, None) == states            # before faults
    assert simulator.filter_states(states, 20, 20, {"car_002"}, None) == [states[0]]      # silent now
    assert simulator.filter_states(states, 30, 20, set(), 25) == []                       # frozen
    assert simulator.filter_states(states, 25, 20, set(), 25) == states                   # last live tick
    assert simulator.filter_states(states, 99, 20, {"car_002"}, None) == [states[0]]


def test_run_loop_with_silent_cars_frozen_feed_and_manifest(redis_client, tmp_path):
    manifest = tmp_path / "truth.json"
    args = simulator.parse_args([
        "--cars", "30", "--seed", "3", "--profile", "random", "--fault-start-tick", "20",
        "--ticks", "40", "--interval", "0", "--silent-cars", "3", "--freeze-after", "30",
        "--manifest", str(manifest),
    ])
    simulator.run_fleet_simulator(args, redis_client=redis_client)

    truth = json.loads(manifest.read_text())
    assert truth["profile"] == "random" and truth["freeze_after"] == 30 and len(truth["silent"]) == 3
    healthy = next(d for d in (f"car_{i:03d}" for i in range(30))
                   if d not in truth["silent"] + truth["battery"] + truth["cabin"] + truth["spikes"])
    assert redis_client.llen(f"logs:{healthy}") == 31                       # ticks 0..30, then frozen
    for silent in truth["silent"]:
        assert redis_client.llen(f"logs:{silent}") == 20                    # ticks 0..19, then silent
    assert len(redis_client.smembers(simulator.DEVICE_SET_KEY)) == 30        # silent cars stay registered
