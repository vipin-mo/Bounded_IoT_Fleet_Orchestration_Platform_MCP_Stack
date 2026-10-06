package server

import (
	"encoding/json"
	"fmt"
	"sort"
)

// MaxTelemetryAgeSeconds is how old a vehicle's last reading may be before the server treats it as
// stale. Telemetry arrives once per second, so 15 s means about 15 missed readings.
const MaxTelemetryAgeSeconds = 15

// Feed status values returned by scan_fleet.
const (
	FeedOK    = "ok"
	FeedStale = "stale" // most of the fleet has not reported recently: the feed is down
	FeedEmpty = "empty" // no vehicles registered at all
)

// maxStaleIDsListed keeps the reply small when the whole feed is down.
const maxStaleIDsListed = 10

// DeviceReading is everything the scan needs to know about one vehicle.
type DeviceReading struct {
	DeviceID       string
	Speed          float64
	BatteryTemp    float64
	CabinStatus    string
	PowerParameter string
	SpeedGovernor  string
	AgeSeconds     int64     // seconds since the last telemetry write; -1 = unknown
	Temps          []float64 // battery history, oldest -> newest
}

// Finding is one vehicle that needs the agent's attention.
type Finding struct {
	DeviceID       string   `json:"device_id"`
	Issues         []string `json:"issues"`
	Classification string   `json:"battery_classification"`
	BatteryTemp    float64  `json:"battery_temp"`
	ZScore         float64  `json:"computed_z_score"`
	Slope          float64  `json:"slope_per_reading"`
	Speed          float64  `json:"speed"`
	CabinStatus    string   `json:"cabin_status"`
	PowerParameter string   `json:"power_parameter"`
	SpeedGovernor  string   `json:"speed_governor"`
	AgeSeconds     int64    `json:"age_seconds"`
}

// ScanReport is the reply of scan_fleet.
type ScanReport struct {
	FeedStatus       string    `json:"feed_status"`
	FleetSize        int       `json:"fleet_size"`
	Checked          int       `json:"checked"`
	InsufficientData int       `json:"insufficient_data"`
	StaleCount       int       `json:"stale_count"`
	StaleDevices     []string  `json:"stale_devices"`
	TransientSpikes  []string  `json:"transient_spikes_ignored"`
	Flagged          []Finding `json:"flagged"`
	Message          string    `json:"message"`
}

// IsFresh reports whether a reading age counts as recent. Unknown age (-1) is not fresh.
func IsFresh(ageSeconds int64) bool {
	return ageSeconds >= 0 && ageSeconds <= MaxTelemetryAgeSeconds
}

// CheckFreshForWrite is the server-side guard on send_ota_command: never change the settings of a
// vehicle whose data we cannot trust. Unknown age is refused too (fail closed).
func CheckFreshForWrite(ageSeconds int64) error {
	if ageSeconds < 0 {
		return fmt.Errorf("no telemetry timestamp for this vehicle; refusing to write on unknown data")
	}
	if ageSeconds > MaxTelemetryAgeSeconds {
		return fmt.Errorf("telemetry is %d s old (limit %d s); refusing to write on stale data", ageSeconds, MaxTelemetryAgeSeconds)
	}
	return nil
}

// TempsFromLogs turns Redis log entries (newest first, JSON) into temperatures ordered oldest -> newest.
// Entries that are not valid JSON are skipped.
func TempsFromLogs(logs []string) []float64 {
	temps := make([]float64, 0, len(logs))
	for i := len(logs) - 1; i >= 0; i-- {
		var entry struct {
			BatteryTemp float64 `json:"battery_temp"`
		}
		if err := json.Unmarshal([]byte(logs[i]), &entry); err != nil {
			continue
		}
		temps = append(temps, entry.BatteryTemp)
	}
	return temps
}

// BuildScanReport checks every vehicle and returns only the ones that need action.
//
// Rules:
//   - A vehicle with stale or unknown age is never analysed. It is listed under stale_devices,
//     because old numbers can look healthy (or sick) for the wrong reason.
//   - If most of the fleet is stale, feed_status is "stale" and nothing is flagged: the feed is down
//     and the agent must report that instead of acting.
//   - A fresh vehicle is flagged when its battery is a sustained_anomaly or rising_trend, or its
//     cabin status is anything other than "nominal". Lone spikes are listed separately, not flagged.
func BuildScanReport(devices []DeviceReading) ScanReport {
	report := ScanReport{
		FleetSize:       len(devices),
		StaleDevices:    []string{},
		TransientSpikes: []string{},
		Flagged:         []Finding{},
	}

	if len(devices) == 0 {
		report.FeedStatus = FeedEmpty
		report.Message = "STALE TELEMETRY: no vehicles are registered. The feed is down or Redis was reset. Report this and take no action."
		return report
	}

	sorted := make([]DeviceReading, len(devices))
	copy(sorted, devices)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].DeviceID < sorted[j].DeviceID })

	var fresh []DeviceReading
	for _, d := range sorted {
		if IsFresh(d.AgeSeconds) {
			fresh = append(fresh, d)
		} else {
			report.StaleCount++
			if len(report.StaleDevices) < maxStaleIDsListed {
				report.StaleDevices = append(report.StaleDevices, d.DeviceID)
			}
		}
	}

	// Majority stale = the feed is down. Using "fewer than half fresh" keeps one or two silent
	// vehicles from shutting down the whole fleet.
	if len(fresh)*2 < len(sorted) {
		report.FeedStatus = FeedStale
		report.Message = fmt.Sprintf("STALE TELEMETRY: %d of %d vehicles have not reported in the last %d s. Report this and take no action.",
			report.StaleCount, len(sorted), MaxTelemetryAgeSeconds)
		return report
	}

	report.FeedStatus = FeedOK
	report.Checked = len(fresh)

	for _, d := range fresh {
		res := AnalyzeTemperatureSeries(d.Temps)
		var issues []string

		switch res.Classification {
		case ClassSustainedAnomaly, ClassRisingTrend:
			issues = append(issues, "battery_"+res.Classification)
		case ClassTransientSpike:
			report.TransientSpikes = append(report.TransientSpikes, d.DeviceID)
		case ClassInsufficientData:
			report.InsufficientData++
		}
		if d.CabinStatus != "" && d.CabinStatus != "nominal" {
			issues = append(issues, "cabin_"+d.CabinStatus)
		}
		if len(issues) == 0 {
			continue
		}

		report.Flagged = append(report.Flagged, Finding{
			DeviceID:       d.DeviceID,
			Issues:         issues,
			Classification: res.Classification,
			BatteryTemp:    d.BatteryTemp,
			ZScore:         round2(res.ZScore),
			Slope:          round2(res.SlopePerReading),
			Speed:          d.Speed,
			CabinStatus:    d.CabinStatus,
			PowerParameter: d.PowerParameter,
			SpeedGovernor:  d.SpeedGovernor,
			AgeSeconds:     d.AgeSeconds,
		})
	}

	report.Message = fmt.Sprintf("Checked %d vehicles: %d need attention, %d lone spikes ignored, %d stale.",
		report.Checked, len(report.Flagged), len(report.TransientSpikes), report.StaleCount)
	return report
}
