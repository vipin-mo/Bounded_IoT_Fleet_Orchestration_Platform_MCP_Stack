package server

import (
	"math"
	"testing"
)

// flatSeries returns n readings that wiggle +/-0.2 around base (like a healthy sensor).
func flatSeries(n int, base float64) []float64 {
	out := make([]float64, n)
	for i := range out {
		if i%2 == 0 {
			out[i] = base - 0.2
		} else {
			out[i] = base + 0.2
		}
	}
	return out
}

// rampTail returns count readings that climb by step each reading, starting just above base.
func rampTail(base, step float64, count int) []float64 {
	out := make([]float64, count)
	for k := 1; k <= count; k++ {
		out[k-1] = base + step*float64(k)
	}
	return out
}

func repeat(value float64, count int) []float64 {
	out := make([]float64, count)
	for i := range out {
		out[i] = value
	}
	return out
}

func join(parts ...[]float64) []float64 {
	var out []float64
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

func TestAnalyzeTemperatureSeriesClassification(t *testing.T) {
	cooling := make([]float64, 20)
	for k := range cooling {
		cooling[k] = 40 - 0.8*float64(k)
	}

	tests := []struct {
		name  string
		temps []float64
		want  string
	}{
		{"too few readings", flatSeries(RecentCount+MinBaselineCount-1, 30), ClassInsufficientData},
		{"empty series", nil, ClassInsufficientData},
		{"healthy sensor noise", flatSeries(60, 30), ClassNominal},
		{"single spike on the newest reading", join(flatSeries(59, 30), []float64{42}), ClassTransientSpike},
		{"five readings jump and stay high", join(flatSeries(55, 30), repeat(40, 5)), ClassSustainedAnomaly},
		{"fast ramp (0.6 C per reading)", join(flatSeries(55, 30), rampTail(30, 0.6, 5)), ClassSustainedAnomaly},
		{"slow ramp (0.35 C per reading)", join(flatSeries(55, 30), rampTail(30, 0.35, 5)), ClassRisingTrend},
		{"two high readings in a row", join(flatSeries(58, 30), repeat(40, 2)), ClassRisingTrend},
		{"cooling after mitigation", join(flatSeries(40, 30), cooling), ClassNominal},
		{"hot plateau pulls baseline up but is above absolute limit", repeat(85, 60), ClassSustainedAnomaly},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := AnalyzeTemperatureSeries(tc.temps)
			if got.Classification != tc.want {
				t.Fatalf("classification = %q, want %q (z=%.2f medianZ=%.2f slope=%.3f)",
					got.Classification, tc.want, got.ZScore, got.RecentMedianZScore, got.SlopePerReading)
			}
		})
	}
}

func TestRampWithContaminatedBaselineIsNotASpike(t *testing.T) {
	for _, rampReadings := range []int{33, 34, 35, 36} {
		temps := join(flatSeries(20, 30), rampTail(30, 0.6, rampReadings))
		got := AnalyzeTemperatureSeries(temps)
		if got.Classification == ClassTransientSpike || got.Classification == ClassNominal {
			t.Fatalf("ramp of %d readings classified %q (z=%.2f slope=%.3f), want rising_trend or sustained_anomaly",
				rampReadings, got.Classification, got.ZScore, got.SlopePerReading)
		}
	}
}

// The newest readings must not be part of their own baseline. If they were, a real jump would
// drag the mean and standard deviation up with it and hide itself.
func TestBaselineExcludesRecentReadings(t *testing.T) {
	got := AnalyzeTemperatureSeries(join(flatSeries(55, 30), repeat(40, 5)))
	if math.Abs(got.BaselineMean-30) > 0.1 {
		t.Fatalf("baseline mean = %.2f, want about 30 (recent readings leaked into the baseline)", got.BaselineMean)
	}
}

// A detector that includes the current reading in a 10-point window can never score above 3.
// This test fails if the detector goes back to that design.
func TestScoreCanExceedOldCeiling(t *testing.T) {
	got := AnalyzeTemperatureSeries(join(flatSeries(59, 30), []float64{42}))
	if got.ZScore <= 3.0 {
		t.Fatalf("z-score = %.2f, want > 3.0", got.ZScore)
	}
}

// With a 0.01 floor, a 1 C wiggle on a quiet sensor would score about 100. The 0.5 C floor keeps it at 2.
func TestStdDevFloorPreventsFalseAlarm(t *testing.T) {
	quiet := make([]float64, 59)
	for i := range quiet {
		if i%2 == 0 {
			quiet[i] = 29.99
		} else {
			quiet[i] = 30.01
		}
	}
	got := AnalyzeTemperatureSeries(join(quiet, []float64{31.0}))
	if got.Classification != ClassNominal {
		t.Fatalf("classification = %q, want %q", got.Classification, ClassNominal)
	}
	if math.Abs(got.ZScore-2.0) > 0.05 {
		t.Fatalf("z-score = %.3f, want about 2.0", got.ZScore)
	}
}

// The reading AFTER a spike still has the spike inside the recent window. It must read as nominal,
// not as a "rising trend" (a plain least-squares slope gets this wrong).
func TestSpikeAgingOutOfWindowIsNominal(t *testing.T) {
	temps := join(flatSeries(58, 30), []float64{42}, []float64{30})
	got := AnalyzeTemperatureSeries(temps)
	if got.Classification != ClassNominal {
		t.Fatalf("classification = %q, want %q (slope=%.3f)", got.Classification, ClassNominal, got.SlopePerReading)
	}
}

func TestMedianAndSlope(t *testing.T) {
	if got := median([]float64{5, 1, 3}); got != 3 {
		t.Fatalf("median odd = %v, want 3", got)
	}
	if got := median([]float64{4, 1, 3, 2}); got != 2.5 {
		t.Fatalf("median even = %v, want 2.5", got)
	}
	if got := slopePerReading([]float64{1, 2, 3, 4, 5}); math.Abs(got-1) > 1e-9 {
		t.Fatalf("slope = %v, want 1", got)
	}
	if got := slopePerReading([]float64{7, 7, 7}); got != 0 {
		t.Fatalf("flat slope = %v, want 0", got)
	}
	// A lone spike must not look like a climb.
	if got := slopePerReading([]float64{0, 0, 0, 12, 0}); got != 0 {
		t.Fatalf("slope with one stray reading = %v, want 0", got)
	}
	if got := slopePerReading([]float64{0, 0, 0, 0, 12}); got != 0 {
		t.Fatalf("slope with one stray newest reading = %v, want 0", got)
	}
}
