"""Fleet simulator: streams telemetry for a simulated fleet into Redis at 1 Hz and reacts to the
registers the agent writes (power_parameter, speed_governor), so mitigations change the data.

    python fleet-simulator/simulator.py --seed 42 --fault-start-tick 60

Test layouts (see --profile): the original fixed cars, random cars per seed, no faults at all, only
sensor blips, and so on. --silent-cars makes some healthy cars stop reporting, and --freeze-after stops
the whole feed (the process keeps running, so Redis keeps the old, ageing data). --manifest writes the
ground truth to a JSON file so scripts/eval_runs.py can score an agent run.
"""
import argparse
import json
import sys
import time

import redis

from fleet_model import HEAT_PER_TICK, PROFILES, FleetModel, build_profile

# Keep this equal to HistoryWindow in mcp-server-go/server/anomaly.go.
HISTORY_WINDOW = 60
DEVICE_SET_KEY = "fleet:devices"


def reset_fleet(r):
    """Delete state left over from an earlier run (old OTA registers would hide new faults)."""
    for pattern in ("device:*", "logs:*"):
        for key in r.scan_iter(match=pattern, count=500):
            r.delete(key)
    r.delete(DEVICE_SET_KEY)


def read_overrides(r, device_ids):
    """Read the registers the agent can write, for every car, in one round trip."""
    pipe = r.pipeline(transaction=False)
    for device_id in device_ids:
        pipe.hmget(f"device:{device_id}", "power_parameter", "speed_governor")
    rows = pipe.execute()
    return {
        device_id: {"power_parameter": row[0], "speed_governor": row[1]}
        for device_id, row in zip(device_ids, rows)
    }


def write_tick(r, states, timestamp):
    """Write one tick for the whole fleet inside MULTI/EXEC, so each LPUSH+LTRIM pair is applied
    together and a reader never sees a list that has grown past HISTORY_WINDOW."""
    pipe = r.pipeline(transaction=True)
    for state in states:
        device_id = state["device_id"]
        pipe.hset(f"device:{device_id}", mapping={
            "device_id": device_id,
            "speed": str(state["speed"]),
            "battery_temp": str(state["battery_temp"]),
            "cabin_status": state["cabin_status"],
            "updated_at": str(timestamp),   # lets the server report how old a reading is
        })
        pipe.sadd(DEVICE_SET_KEY, device_id)
        pipe.lpush(f"logs:{device_id}", json.dumps({
            "timestamp": timestamp,
            "speed": state["speed"],
            "battery_temp": state["battery_temp"],
        }))
        pipe.ltrim(f"logs:{device_id}", 0, HISTORY_WINDOW - 1)
    pipe.execute()


def filter_states(states, tick, fault_start_tick, silent_ids, freeze_after):
    """Drop the readings that must not reach Redis on this tick.

    freeze_after: after this tick nothing is written (a dead feed). None = never freeze.
    silent_ids:   once faults start these cars stop reporting, so their last reading ages.
    """
    if freeze_after is not None and tick > freeze_after:
        return []
    if tick >= fault_start_tick and silent_ids:
        return [s for s in states if s["device_id"] not in silent_ids]
    return states


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=42, help="random seed; same seed gives the same run")
    p.add_argument("--cars", type=int, default=100)
    p.add_argument("--fault-start-tick", type=int, default=60,
                   help="faults begin after this many ticks (the detector needs a baseline first)")
    p.add_argument("--interval", type=float, default=1.0, help="seconds per tick")
    p.add_argument("--ticks", type=int, default=0, help="stop after this many ticks (0 = run forever)")
    p.add_argument("--no-reset", action="store_true", help="keep existing Redis state")
    p.add_argument("--profile", choices=PROFILES, default="default",
                   help="which cars get which fault: default = the original fixed cars, random = a new "
                        "layout per seed, none = healthy fleet, spikes_only, battery_only, cabin_only, dual, "
                        "manual_only = coolant leaks whose fix is only in the manual")
    p.add_argument("--silent-cars", type=int, default=0,
                   help="this many healthy cars stop reporting when faults start")
    p.add_argument("--silent-faulty", type=int, default=0,
                   help="this many FAULTY cars stop reporting when faults start (their fault is never visible)")
    p.add_argument("--heat-per-tick", type=float, default=HEAT_PER_TICK,
                   help="battery heating rate of faulty cars in degrees C per tick (default %(default)s); "
                        "below 0.3 the climb is slow enough to be hard to see")
    p.add_argument("--freeze-after", type=int, default=None,
                   help="stop writing telemetry after this tick (simulates a dead feed)")
    p.add_argument("--manifest", default=None, help="write the ground truth of this run to this JSON file")
    p.add_argument("--redis-host", default="localhost")
    p.add_argument("--redis-port", type=int, default=6379)
    return p.parse_args(argv)


def run_fleet_simulator(args, redis_client=None):
    r = redis_client
    if r is None:
        try:
            r = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)
            r.ping()
        except redis.ConnectionError:
            print("Error: Could not connect to Redis. Run 'make up' first.")
            sys.exit(1)

    if not args.no_reset:
        reset_fleet(r)

    scenarios, silent_ids = build_profile(args.profile, args.cars, args.seed, args.silent_cars, args.silent_faulty)
    model = FleetModel(cars=args.cars, seed=args.seed, fault_start_tick=args.fault_start_tick,
                       scenarios=scenarios, silent_ids=silent_ids, heat_per_tick=args.heat_per_tick)
    truth = model.manifest()
    truth.update({"seed": args.seed, "profile": args.profile, "cars": args.cars,
                  "freeze_after": args.freeze_after})
    if args.manifest:
        with open(args.manifest, "w", encoding="utf-8") as f:
            json.dump(truth, f, indent=2)
    print(f"Simulating {args.cars} cars (seed={args.seed}, profile={args.profile}). "
          f"Faults start at tick {args.fault_start_tick}.")
    print(f"Faulty cars: battery={truth['battery']} cabin={truth['cabin']} dual={truth['dual']} "
          f"coolant={truth['coolant']} spikes={truth['spikes']} silent={truth['silent']}")

    seen_mitigations = set()
    tick = 0
    while args.ticks == 0 or tick < args.ticks:
        started = time.time()
        overrides = read_overrides(r, model.device_ids)
        states = model.step(tick, overrides)
        states = filter_states(states, tick, args.fault_start_tick, model.silent_ids, args.freeze_after)
        if states:
            write_tick(r, states, int(started))
        elif args.freeze_after is not None and tick == args.freeze_after + 1:
            print(f"[tick {tick}] feed frozen: no more telemetry is written")

        for device_id, regs in overrides.items():
            for register in ("power_parameter", "speed_governor"):
                if regs[register] is not None and (device_id, register) not in seen_mitigations:
                    seen_mitigations.add((device_id, register))
                    print(f"[tick {tick}] {device_id}: {register} = {regs[register]}")

        if tick == args.fault_start_tick:
            print(f"[tick {tick}] faults are now active")
        tick += 1
        time.sleep(max(0.0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    run_fleet_simulator(parse_args())
