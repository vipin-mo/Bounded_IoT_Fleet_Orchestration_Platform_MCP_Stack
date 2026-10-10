"""Write testdata/detector_series.json: battery-temperature series from the simulator, for the Go detector.

The Go test `TestDetectorOnSimulatedSeries` reads this file, so the real detector is tested on the
simulator's own physics: ramps at different heating rates, healthy cars, and sensor blips. The file is
generated, never edited by hand. A Python test fails if it is out of date.

    python scripts/gen_detector_series.py            # rewrite the file
    python scripts/gen_detector_series.py --check    # exit 1 if the file is out of date
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fleet-simulator"))
from fleet_model import BATTERY_RUNAWAY, TRANSIENT_SPIKE, FleetModel  # noqa: E402

OUTPUT = ROOT / "testdata" / "detector_series.json"

FAULT_START = 60                                  # ticks of healthy readings before the fault begins
RAMP_RATES = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.60]   # degrees C per tick (0.6 is the default)
RAMP_SEEDS = range(1, 11)
RAMP_TICKS = 160
HEALTHY_SEEDS = range(1, 21)
SPIKE_SEEDS = range(1, 11)
QUIET_TICKS = 200


def one_car_series(seed, ticks, scenario, heat_per_tick=0.6):
    scenarios = {} if scenario is None else {0: scenario}
    model = FleetModel(cars=1, seed=seed, fault_start_tick=FAULT_START, scenarios=scenarios,
                       heat_per_tick=heat_per_tick)
    return [model.step(t)[0]["battery_temp"] for t in range(ticks)]


def build():
    cases = []
    for rate in RAMP_RATES:
        for seed in RAMP_SEEDS:
            cases.append({"kind": "ramp", "rate": rate, "seed": seed,
                          "temps": one_car_series(seed, RAMP_TICKS, BATTERY_RUNAWAY, rate)})
    for seed in HEALTHY_SEEDS:
        cases.append({"kind": "healthy", "seed": seed, "temps": one_car_series(seed, QUIET_TICKS, None)})
    for seed in SPIKE_SEEDS:
        cases.append({"kind": "spike", "seed": seed, "temps": one_car_series(seed, QUIET_TICKS, TRANSIENT_SPIKE)})
    return {"history_window": 60, "fault_start": FAULT_START, "cases": cases}


def render():
    return json.dumps(build(), separators=(",", ":")) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the file on disk is out of date")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print(f"{OUTPUT} is out of date. Run: python scripts/gen_detector_series.py")
            return 1
        print("up to date")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(text) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
