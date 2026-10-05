import json
import random
import time
import sys
import redis

# The detector needs enough older readings to build a baseline.
HISTORY_WINDOW = 60


def run_fleet_simulator():
    """Simulates real-time telemetry metrics for an IoT vehicle fleet, writing state data to Redis."""
    try:
        # Establish connection pool to the localized Docker Redis instance
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
        print("Fleet Simulator successfully streaming telemetry logs into Redis...")
    except redis.ConnectionError:
        print("Error: Could not connect to Redis. Ensure you executed 'make up' or 'docker-compose up -d'.")
        sys.exit(1)

    total_vehicles = 100
    anomaly_indices = {12, 35, 68, 88}  # Evaluated as a O(1) lookup set instead of an itemized list

    print("Generating rolling vehicle parameters and historical log arrays...")

    while True:
        for idx in range(total_vehicles):
            device_id = f"car_{idx:03d}"
            redis_key = f"device:{device_id}"
            log_key = f"logs:{device_id}"

            # Establish standard nominal baseline operational envelopes
            speed = round(random.uniform(30.0, 55.0), 1)
            battery_temp = round(random.uniform(25.0, 38.0), 1)
            cabin_status = "nominal"

            # Inject target stress profiles into specific sample vectors
            if idx in anomaly_indices:
                speed = round(random.uniform(65.0, 78.0), 1)
                battery_temp = round(random.uniform(51.0, 58.0), 1)
                cabin_status = "overheating_critical"

            # 1. Write the current real-time state snapshot hash map
            r.hset(redis_key, mapping={
                "device_id": device_id,
                "speed": str(speed),
                "battery_temp": str(battery_temp),
                "cabin_status": cabin_status
            })

            # 2. Append to a rolling chronological list (constrained to the last HISTORY_WINDOW records)
            log_entry = json.dumps({
                "timestamp": int(time.time()),
                "speed": speed,
                "battery_temp": battery_temp
            })
            r.lpush(log_key, log_entry)
            r.ltrim(log_key, 0, HISTORY_WINDOW - 1)

            # 3. Read back tracking overrides sent down from the agent loop
            power_param = r.hget(redis_key, "power_parameter")
            if power_param == "eco_mode":
                print(f"[ALARM MITIGATED] {device_id} shifted to 'eco_mode'. Safety Governor Engaged.")

        # Stream interval heartbeat
        time.sleep(1.0)


if __name__ == "__main__":
    run_fleet_simulator()
