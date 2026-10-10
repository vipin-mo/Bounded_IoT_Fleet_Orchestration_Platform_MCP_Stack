package server

import (
	"math"
	"sort"
)

// Detector settings. Telemetry arrives once per second, so one "reading" is one second.
const (
	// HistoryWindow is how many readings are kept per vehicle (the simulator trims to this size).
	HistoryWindow = 60
	// RecentCount is how many of the newest readings count as "current".
	RecentCount = 5
	// MinBaselineCount is how many older readings are needed to build a baseline.
	MinBaselineCount = 10
	// StdDevFloor (degrees C) stops tiny sensor noise from producing huge z-scores.
	StdDevFloor = 0.5
	// ZScoreThreshold is the distance from the baseline (in standard deviations) that counts as abnormal.
	ZScoreThreshold = 2.5
	// RisingSlopeLimit (degrees C per reading) flags a steady climb that has not yet crossed the threshold.
	RisingSlopeLimit = 0.3
	// AbsoluteTempLimit (degrees C) is a hard ceiling: a plateau this hot is abnormal even if it
	// has been hot long enough to pull the baseline up with it.
	AbsoluteTempLimit = 60.0
)

// Classification values returned to the agent.
const (
	ClassInsufficientData = "insufficient_data"
	ClassNominal          = "nominal"
	ClassTransientSpike   = "transient_spike"
	ClassSustainedAnomaly = "sustained_anomaly"
	ClassRisingTrend      = "rising_trend"
)

// AnomalyResult is the outcome of analysing one vehicle's battery temperature history.
type AnomalyResult struct {
	Samples            int
	BaselineMean       float64
	BaselineStdDev     float64
	LatestTemp         float64
	ZScore             float64 // newest reading vs baseline
	RecentMedianZScore float64 // median of the newest RecentCount readings vs baseline
	SlopePerReading    float64 // robust (Theil-Sen) slope over the newest RecentCount readings
	Classification     string
}

// AnalyzeTemperatureSeries classifies a battery temperature series ordered oldest -> newest.
//
// The newest RecentCount readings are compared against the OLDER readings only. Including the
// newest reading in its own baseline would cap the z-score: with a 10-point window the largest
// possible z-score is 3, so a real runaway could never be told apart from noise.
//
// Rules, checked in this order:
//  1. sustained_anomaly: the median of the recent readings is above the threshold (or above the
//     absolute limit). One odd reading cannot move a median, so this means the heating is real.
//  2. transient_spike: the newest reading is above the threshold, the one before it was not, AND
//     the recent slope is flat. The slope test matters: when a slow ramp has already pulled the
//     baseline up, the first reading to cross the threshold looks like a spike, but a ramp has a
//     steady positive slope and a lone spike does not (the slope is robust to one stray reading).
//  3. rising_trend: the newest reading is above the threshold without being a lone spike, or the
//     recent slope exceeds RisingSlopeLimit.
//  4. nominal: everything else, including cooling after a mitigation.
func AnalyzeTemperatureSeries(temps []float64) AnomalyResult {
	n := len(temps)
	res := AnomalyResult{Samples: n}
	if n > 0 {
		res.LatestTemp = temps[n-1]
	}
	if n < RecentCount+MinBaselineCount {
		res.Classification = ClassInsufficientData
		return res
	}

	baseline := temps[:n-RecentCount]
	recent := temps[n-RecentCount:]

	mean, std := meanAndStdDev(baseline)
	if std < StdDevFloor {
		std = StdDevFloor
	}
	recentMedian := median(recent)
	previousZ := (temps[n-2] - mean) / std

	res.BaselineMean = mean
	res.BaselineStdDev = std
	res.ZScore = (res.LatestTemp - mean) / std
	res.RecentMedianZScore = (recentMedian - mean) / std
	res.SlopePerReading = slopePerReading(recent)

	switch {
	case res.RecentMedianZScore > ZScoreThreshold || recentMedian >= AbsoluteTempLimit:
		res.Classification = ClassSustainedAnomaly
	case res.ZScore > ZScoreThreshold && previousZ <= ZScoreThreshold && res.SlopePerReading <= RisingSlopeLimit:
		res.Classification = ClassTransientSpike
	case res.ZScore > ZScoreThreshold || res.SlopePerReading > RisingSlopeLimit:
		res.Classification = ClassRisingTrend
	default:
		res.Classification = ClassNominal
	}
	return res
}

func meanAndStdDev(values []float64) (float64, float64) {
	var sum float64
	for _, v := range values {
		sum += v
	}
	mean := sum / float64(len(values))

	var squares float64
	for _, v := range values {
		squares += (v - mean) * (v - mean)
	}
	return mean, math.Sqrt(squares / float64(len(values)))
}

func median(values []float64) float64 {
	sorted := make([]float64, len(values))
	copy(sorted, values)
	sort.Float64s(sorted)
	mid := len(sorted) / 2
	if len(sorted)%2 == 1 {
		return sorted[mid]
	}
	return (sorted[mid-1] + sorted[mid]) / 2
}

// slopePerReading is the Theil-Sen slope of values against their position (0, 1, 2, ...): the
// median of the slopes between every pair of points. Unlike a least-squares line, one stray
// reading cannot tilt it, so a lone spike inside the window is not mistaken for a climb.
func slopePerReading(values []float64) float64 {
	var slopes []float64
	for i := 0; i < len(values); i++ {
		for j := i + 1; j < len(values); j++ {
			slopes = append(slopes, (values[j]-values[i])/float64(j-i))
		}
	}
	if len(slopes) == 0 {
		return 0
	}
	return median(slopes)
}
