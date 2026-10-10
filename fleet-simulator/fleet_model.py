"""Pure fleet physics for the simulator.

Each tick the model produces one telemetry reading per car. Cars follow one of four scenarios:

  nominal          healthy car, small sensor noise
  battery_runaway  after `fault_start_tick` the battery heats up every tick. If the car is set to
                   `eco_mode` the heating stops and the battery cools back down (closed loop).
  cabin_inverter   after `fault_start_tick` the cabin is 'overheating_critical' and the car speeds.
                   If a `speed_governor` is set the speed is capped and, a few ticks later, the
                   cabin status returns to 'nominal' (closed loop).
  transient_spike  one single hot reading every SPIKE_EVERY ticks. A correct agent must NOT react.
"""
import random
from dataclasses import dataclass

NOMINAL = "nominal"
BATTERY_RUNAWAY = "battery_runaway"
CABIN_INVERTER = "cabin_inverter"
TRANSIENT_SPIKE = "transient_spike"

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
TEMP_NOISE = 0.15          # standard deviation of sensor noise, degrees C
SPEED_NOISE = 1.5


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
    def __init__(self, cars=100, seed=42, fault_start_tick=60, scenarios=None):
        self.rng = random.Random(seed)
        self.fault_start_tick = fault_start_tick
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

            if car.scenario == BATTERY_RUNAWAY and faulting:
                if eco_mode:
                    car.heat = max(0.0, car.heat - COOL_PER_TICK)
                else:
                    car.heat = min(MAX_HEAT, car.heat + HEAT_PER_TICK)

            if car.scenario == CABIN_INVERTER and faulting:
                if governor is not None:
                    car.governed_ticks += 1
                if governor is not None and car.governed_ticks >= CABIN_RECOVERY_TICKS:
                    cabin_status = "nominal"
                else:
                    cabin_status = "overheating_critical"
                    speed = self.rng.uniform(65.0, 78.0)

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
