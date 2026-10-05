import json

import fakeredis
import pytest

import simulator
from fleet_model import (
    BATTERY_RUNAWAY, CABIN_INVERTER, TRANSIENT_SPIKE, DEFAULT_SCENARIOS,
    MAX_HEAT, SPIKE_EVERY, FleetModel,
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
