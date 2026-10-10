import json
import subprocess
import sys
from pathlib import Path

import gen_detector_series as gen

ROOT = Path(__file__).resolve().parent.parent


def test_series_file_is_up_to_date():
    """The Go detector tests read testdata/detector_series.json. It must match what the simulator makes today."""
    assert gen.OUTPUT.read_text(encoding="utf-8") == gen.render(), \
        "testdata/detector_series.json is out of date: run python scripts/gen_detector_series.py"


def test_series_contents_cover_ramps_healthy_and_blips():
    data = json.loads(gen.OUTPUT.read_text(encoding="utf-8"))
    assert data["history_window"] == 60 and data["fault_start"] == 60
    kinds = {}
    for case in data["cases"]:
        kinds.setdefault(case["kind"], []).append(case)
    assert sorted(kinds) == ["healthy", "ramp", "spike"]
    assert {c["rate"] for c in kinds["ramp"]} == set(gen.RAMP_RATES)
    ramp = next(c for c in kinds["ramp"] if c["rate"] == 0.6 and c["seed"] == 1)
    assert ramp["temps"][-1] - ramp["temps"][59] > 30           # really heats after the fault starts
    assert max(kinds["healthy"][0]["temps"]) - min(kinds["healthy"][0]["temps"]) < 3
    blips = kinds["spike"][0]["temps"]
    assert max(blips) - sorted(blips)[len(blips) // 2] > 8      # the 12 C blip is there


def test_generator_is_deterministic():
    assert gen.render() == gen.render()


def test_check_flag_passes_on_a_current_file_and_the_script_runs():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_detector_series.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0 and "up to date" in result.stdout
