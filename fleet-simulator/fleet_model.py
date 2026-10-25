"""Pure fleet physics for the simulator. There is no Redis in this file, so it can be unit tested.

Each tick the model produces one telemetry reading per car. Cars follow one of four scenarios:

  nominal          healthy car, small sensor noise
  battery_runaway  after `fault_start_tick` the battery heats up every tick. If the car is set to
                   `eco_mode` the heating stops and the battery cools back down (closed loop).
  cabin_inverter   after `fault_start_tick` the cabin is 'overheating_critical' and the car speeds.
                   If a `speed_governor` is set the speed is capped and, a few ticks later, the
                   cabin status returns to 'nominal' (closed loop).
  transient_spike  one single hot reading every SPIKE_EVERY ticks. A correct agent must NOT react.
  dual_fault       both of the first two on the same car. It needs two different fixes (eco_mode AND a
                   speed governor), and each fix clears only its own half.
  coolant_leak     after `fault_start_tick` the cabin status is 'coolant_leak'. Only the manual gives the
                   fix: a speed governor of COOLANT_GOVERNOR_MAX km/h or lower. A higher governor (the 50 used
                   for cabin_inverter) or eco_mode does nothing, so an agent that ignores the manual fails.

`build_profile` chooses which cars get which scenario, so a test run can use the original fixed cars
("default") or a different random layout for every seed ("random"), with or without faults.
"""
import random
from dataclasses import dataclass

PROFILES = ("default", "random", "none", "spikes_only", "battery_only", "cabin_only", "dual", "manual_only")

NOMINAL = "nominal"
BATTERY_RUNAWAY = "battery_runaway"
CABIN_INVERTER = "cabin_inverter"
TRANSIENT_SPIKE = "transient_spike"
DUAL_FAULT = "dual_fault"   # one car with BOTH a battery runaway and a cabin inverter fault
COOLANT_LEAK = "coolant_leak"   # a cabin fault whose fix is written only in the manual

# Same four fault cars as the original simulator, plus two noise cars.
DEFAULT_SCENARIOS = {
    12: BATTERY_RUNAWAY,
    35: BATTERY_RUNAWAY,
    68: CABIN_INVERTER,
    88: CABIN_INVERTER,
    20: TRANSIENT_SPIKE,
    50: TRANSIENT_SPIKE,
}

HEAT_PER_TICK = 0.6        # degrees C gained per tick while a battery fault is active
COOL_PER_TICK = 0.8        # degrees C lost per tick once the car is in eco_mode
MAX_HEAT = 55.0            # the battery cannot heat beyond base temperature + this
SPIKE_SIZE = 12.0          # degrees C added for one reading of a transient spike
SPIKE_EVERY = 20           # ticks between transient spikes
CABIN_RECOVERY_TICKS = 5   # ticks with a governor set before the cabin status clears
COOLANT_GOVERNOR_MAX = 30  # a coolant leak clears only under a governor at or below this (km/h)
TEMP_NOISE = 0.15          # standard deviation of sensor noise, degrees C
SPEED_NOISE = 1.5


def build_profile(profile, cars, seed, silent_cars=0, silent_faulty=0):
    """Pick the scenario of every car. Returns (scenarios, silent_ids).

    scenarios     maps car index -> scenario name (cars that are not listed are healthy)
    silent_ids    device ids that stop reporting once faults start. `silent_cars` of them are healthy
                  cars; `silent_faulty` of them are faulty cars, whose fault the feed never shows.

    The layout comes from its own random generator, seeded by (profile, seed), so choosing a profile
    never changes the physics of a run and the same seed always gives the same layout. Older options
    draw numbers in the same order as before, so layouts of existing seeds do not change.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose one of {', '.join(PROFILES)}")
    layout_rng = random.Random(f"layout:{profile}:{seed}")

    def assign(counts):
        """counts: list of (scenario, how_many). Picks distinct cars and returns (scenarios, leftover indices)."""
        needed = sum(n for _, n in counts) + silent_cars
        if needed > cars:
            raise ValueError(f"profile needs {needed} cars but the fleet has only {cars}")
        chosen = layout_rng.sample(range(cars), needed)
        out, cursor = {}, 0
        for scenario, count in counts:
            for idx in chosen[cursor:cursor + count]:
                out[idx] = scenario
            cursor += count
        return out, chosen[cursor:]

    if profile == "default":
        scenarios = {i: s for i, s in DEFAULT_SCENARIOS.items() if i < cars}
        healthy = [i for i in range(cars) if i not in scenarios]
        if silent_cars > len(healthy):
            raise ValueError("not enough healthy cars to silence")
        silent_idx = layout_rng.sample(healthy, silent_cars)
    else:
        if profile == "none":
            counts = (0, 0, 0)
        elif profile == "spikes_only":
            counts = (0, 0, layout_rng.randint(1, 3))
        elif profile == "battery_only":
            counts = (layout_rng.randint(1, 3), 0, 0)
        elif profile == "cabin_only":
            counts = (0, layout_rng.randint(1, 3), 0)
        elif profile == "random":  # 0-3 of each kind, at least one real fault
            while True:
                counts = (layout_rng.randint(0, 3), layout_rng.randint(0, 3), layout_rng.randint(0, 3))
                if counts[0] + counts[1] > 0:
                    break
        if profile == "dual":      # 1-2 dual-fault cars, 1-2 battery, 0-2 cabin, 0-2 blips: at least 2 fault cars
            pairs = [(DUAL_FAULT, layout_rng.randint(1, 2)), (BATTERY_RUNAWAY, layout_rng.randint(1, 2)),
                     (CABIN_INVERTER, layout_rng.randint(0, 2)), (TRANSIENT_SPIKE, layout_rng.randint(0, 2))]
        elif profile == "manual_only":   # 1-2 coolant leaks next to 1-2 cabin and 1-2 battery faults, 0-2 blips
            pairs = [(COOLANT_LEAK, layout_rng.randint(1, 2)), (CABIN_INVERTER, layout_rng.randint(1, 2)),
                     (BATTERY_RUNAWAY, layout_rng.randint(1, 2)), (TRANSIENT_SPIKE, layout_rng.randint(0, 2))]
        else:
            pairs = list(zip((BATTERY_RUNAWAY, CABIN_INVERTER, TRANSIENT_SPIKE), counts))
        scenarios, silent_idx = assign(pairs)

    silent_ids = {f"car_{i:03d}" for i in silent_idx}

    if silent_faulty:
        fault_idx = sorted(i for i, s in scenarios.items() if s != TRANSIENT_SPIKE)
        if silent_faulty > len(fault_idx) - 1:
            raise ValueError(f"cannot silence {silent_faulty} of {len(fault_idx)} faulty cars: "
                             "at least one must keep reporting")
        silent_ids |= {f"car_{i:03d}" for i in layout_rng.sample(fault_idx, silent_faulty)}
    return scenarios, silent_ids


@dataclass
class CarState:
    device_id: str
    scenario: str
    base_temp: float
    base_speed: float
    heat: float = 0.0
    governed_ticks: int = 0


def _governor_limit(raw):
    """Parse a speed_governor register. Anything that is not a plain number is ignored."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class FleetModel:
    def __init__(self, cars=100, seed=42, fault_start_tick=60, scenarios=None, silent_ids=None,
                 heat_per_tick=HEAT_PER_TICK):
        self.rng = random.Random(seed)
        self.fault_start_tick = fault_start_tick
        self.heat_per_tick = heat_per_tick
        self.silent_ids = set(silent_ids or ())
        scenarios = DEFAULT_SCENARIOS if scenarios is None else scenarios
        self.cars = []
        for idx in range(cars):
            self.cars.append(CarState(
                device_id=f"car_{idx:03d}",
                scenario=scenarios.get(idx, NOMINAL),
                base_temp=self.rng.uniform(27.0, 35.0),
                base_speed=self.rng.uniform(32.0, 52.0),
            ))

    @property
    def device_ids(self):
        return [c.device_id for c in self.cars]

    def manifest(self):
        """Ground truth for this run: which cars carry which fault. The eval script scores against it."""
        def ids(scenario):
            return [c.device_id for c in self.cars if c.scenario == scenario]
        battery, cabin, dual = ids(BATTERY_RUNAWAY), ids(CABIN_INVERTER), ids(DUAL_FAULT)
        coolant = ids(COOLANT_LEAK)
        faulty = set(battery) | set(cabin) | set(dual) | set(coolant)
        return {
            "fault_start_tick": self.fault_start_tick,
            "battery": battery,
            "cabin": cabin,
            "dual": dual,                      # these cars need BOTH fixes
            "coolant": coolant,                # these need the governor value from the manual
            "spikes": ids(TRANSIENT_SPIKE),
            "silent": sorted(self.silent_ids),
            "silent_faulty": sorted(self.silent_ids & faulty),   # faulty cars whose fault the feed never shows
            "heat_per_tick": self.heat_per_tick,
        }

    def step(self, tick, overrides=None):
        """Advance one tick. `overrides` maps device_id -> {"power_parameter": ..., "speed_governor": ...}
        (the registers the agent can write). Returns one telemetry dict per car."""
        overrides = overrides or {}
        out = []
        for car in self.cars:
            regs = overrides.get(car.device_id) or {}
            eco_mode = regs.get("power_parameter") == "eco_mode"
            governor = _governor_limit(regs.get("speed_governor"))
            faulting = tick >= self.fault_start_tick

            temp = car.base_temp
            speed = car.base_speed + self.rng.gauss(0, SPEED_NOISE)
            cabin_status = "nominal"

            if car.scenario in (BATTERY_RUNAWAY, DUAL_FAULT) and faulting:
                if eco_mode:
                    car.heat = max(0.0, car.heat - COOL_PER_TICK)
                else:
                    car.heat = min(MAX_HEAT, car.heat + self.heat_per_tick)

            if car.scenario in (CABIN_INVERTER, DUAL_FAULT) and faulting:
                if governor is not None:
                    car.governed_ticks += 1
                if governor is not None and car.governed_ticks >= CABIN_RECOVERY_TICKS:
                    cabin_status = "nominal"
                else:
                    cabin_status = "overheating_critical"
                    speed = self.rng.uniform(65.0, 78.0)

            if car.scenario == COOLANT_LEAK and faulting:
                if governor is not None and governor <= COOLANT_GOVERNOR_MAX:
                    car.governed_ticks += 1
                if car.governed_ticks < CABIN_RECOVERY_TICKS:
                    cabin_status = "coolant_leak"

            temp += car.heat + self.rng.gauss(0, TEMP_NOISE)

            if (car.scenario == TRANSIENT_SPIKE and faulting
                    and (tick - self.fault_start_tick) % SPIKE_EVERY == 0):
                temp += SPIKE_SIZE

            if governor is not None:
                speed = min(speed, governor)

            out.append({
                "device_id": car.device_id,
                "speed": round(max(speed, 0.0), 1),
                "battery_temp": round(temp, 1),
                "cabin_status": cabin_status,
            })
        return out
