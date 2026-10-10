package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// The series in testdata/detector_series.json are made by the Python simulator (scripts/gen_detector_series.py).
// Running the real Go detector over them checks it against the simulator's own physics, not only against
// hand-made numbers: ramps at several heating rates, healthy cars, and one-reading sensor blips.

type seriesCase struct {
	Kind  string    `json:"kind"`
	Rate  float64   `json:"rate"`
	Seed  int       `json:"seed"`
	Temps []float64 `json:"temps"`
}

type seriesFile struct {
	HistoryWindow int          `json:"history_window"`
	FaultStart    int          `json:"fault_start"`
	Cases         []seriesCase `json:"cases"`
}

func loadSeries(t *testing.T) seriesFile {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "detector_series.json"))
	if err != nil {
		t.Fatalf("cannot read detector_series.json: %v (run: python scripts/gen_detector_series.py)", err)
	}
	var f seriesFile
	if err := json.Unmarshal(raw, &f); err != nil {
		t.Fatal(err)
	}
	if f.HistoryWindow != HistoryWindow {
		t.Fatalf("series were made for a history window of %d, the detector uses %d", f.HistoryWindow, HistoryWindow)
	}
	return f
}

func isFlagged(class string) bool {
	return class == ClassSustainedAnomaly || class == ClassRisingTrend
}

// classifyEveryTick runs the detector the way the server does: at each tick it sees the newest
// HistoryWindow readings. It returns the result at every tick.
func classifyEveryTick(temps []float64) []AnomalyResult {
	out := make([]AnomalyResult, len(temps))
	for tick := range temps {
		start := tick + 1 - HistoryWindow
		if start < 0 {
			start = 0
		}
		out[tick] = AnalyzeTemperatureSeries(temps[start : tick+1])
	}
	return out
}

// firstFlagged returns the first tick (at or after `from`) at which the vehicle would be flagged, or -1.
func firstFlagged(results []AnomalyResult, from int) int {
	for tick := from; tick < len(results); tick++ {
		if isFlagged(results[tick].Classification) {
			return tick
		}
	}
	return -1
}

func TestDetectorOnSimulatedSeries(t *testing.T) {
	f := loadSeries(t)
	for _, c := range f.Cases {
		results := classifyEveryTick(c.Temps)
		switch c.Kind {
		case "healthy":
			for tick, r := range results {
				if isFlagged(r.Classification) || r.Classification == ClassTransientSpike {
					t.Fatalf("healthy car (seed %d) was %s at tick %d (temp %.1f)", c.Seed, r.Classification, tick, c.Temps[tick])
				}
			}
		case "spike":
			for tick, r := range results {
				if isFlagged(r.Classification) {
					t.Fatalf("sensor-blip car (seed %d) was flagged as %s at tick %d", c.Seed, r.Classification, tick)
				}
			}
		case "ramp":
			if first := firstFlagged(results, 0); first >= 0 && first < f.FaultStart {
				t.Fatalf("ramp %.2f seed %d flagged at tick %d, before the fault began at %d", c.Rate, c.Seed, first, f.FaultStart)
			}
			if firstFlagged(results, f.FaultStart) < 0 {
				t.Errorf("ramp %.2f C/tick seed %d was never flagged in %d ticks", c.Rate, c.Seed, len(c.Temps))
			}
		}
	}
}

// maxLatency is the slowest the detector may be, in ticks after the fault begins, at each heating rate.
// The values are the slowest measured latency (docs/DETECTION_LATENCY.md) plus about 3 ticks of margin. If the detector is
// changed and gets slower, this test fails and the table must be looked at again.
var maxLatency = map[float64]int{0.10: 21, 0.15: 14, 0.20: 12, 0.25: 10, 0.30: 8, 0.35: 8, 0.40: 6, 0.60: 5}

func TestDetectionLatencyIsBounded(t *testing.T) {
	f := loadSeries(t)
	for _, c := range f.Cases {
		if c.Kind != "ramp" {
			continue
		}
		bound, ok := maxLatency[c.Rate]
		if !ok {
			t.Fatalf("no latency bound for rate %.2f", c.Rate)
		}
		first := firstFlagged(classifyEveryTick(c.Temps), f.FaultStart)
		if first < 0 {
			continue // reported by TestDetectorOnSimulatedSeries
		}
		if latency := first - f.FaultStart; latency > bound {
			t.Errorf("ramp %.2f C/tick seed %d flagged %d ticks after the fault began, bound is %d", c.Rate, c.Seed, latency, bound)
		}
	}
}

// TestDetectionLatencyReport prints the latency table. Run it with:
//
//	go test ./server -run TestDetectionLatencyReport -v
func TestDetectionLatencyReport(t *testing.T) {
	f := loadSeries(t)
	byRate := map[float64][]int{}
	rise := map[float64][]float64{}
	for _, c := range f.Cases {
		if c.Kind != "ramp" {
			continue
		}
		first := firstFlagged(classifyEveryTick(c.Temps), f.FaultStart)
		if first < 0 {
			byRate[c.Rate] = append(byRate[c.Rate], -1)
			continue
		}
		byRate[c.Rate] = append(byRate[c.Rate], first-f.FaultStart)
		rise[c.Rate] = append(rise[c.Rate], c.Temps[first]-c.Temps[f.FaultStart-1])
	}
	rates := make([]float64, 0, len(byRate))
	for r := range byRate {
		rates = append(rates, r)
	}
	sort.Float64s(rates)
	t.Logf("rate C/tick | runs | missed | latency ticks: min / median / max | rise at detection C (median)")
	for _, r := range rates {
		lat := append([]int(nil), byRate[r]...)
		sort.Ints(lat)
		missed := 0
		var seen []int
		for _, l := range lat {
			if l < 0 {
				missed++
			} else {
				seen = append(seen, l)
			}
		}
		rises := append([]float64(nil), rise[r]...)
		sort.Float64s(rises)
		if len(seen) == 0 {
			t.Logf("%11.2f | %4d | %6d | never flagged", r, len(lat), missed)
			continue
		}
		t.Logf("%11.2f | %4d | %6d | %d / %d / %d | %.1f", r, len(lat), missed, seen[0], seen[len(seen)/2], seen[len(seen)-1], rises[len(rises)/2])
	}
}
