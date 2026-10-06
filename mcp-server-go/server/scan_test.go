package server

import (
	"fmt"
	"testing"
)

// healthy builds n vehicles with flat 30 C history and fresh data.
func healthy(n int) []DeviceReading {
	out := make([]DeviceReading, n)
	for i := range out {
		out[i] = DeviceReading{
			DeviceID:    fmt.Sprintf("car_%03d", i+1),
			Speed:       50,
			BatteryTemp: 30,
			CabinStatus: "nominal",
			AgeSeconds:  1,
			Temps:       flatSeries(60, 30),
		}
	}
	return out
}

func findByID(r ScanReport, id string) *Finding {
	for i := range r.Flagged {
		if r.Flagged[i].DeviceID == id {
			return &r.Flagged[i]
		}
	}
	return nil
}

func TestScanHealthyFleetFlagsNothing(t *testing.T) {
	r := BuildScanReport(healthy(100))
	if r.FeedStatus != FeedOK || len(r.Flagged) != 0 || r.Checked != 100 {
		t.Fatalf("status=%s flagged=%d checked=%d, want ok/0/100", r.FeedStatus, len(r.Flagged), r.Checked)
	}
}

// The seed-101 bug: the agent never looked at a battery at 47.9 C because of its own temperature
// filter. The scan checks every car, so the filter cannot hide a ramp.
func TestScanFindsEarlyRampBelowOldFortyDegreeFilter(t *testing.T) {
	fleet := healthy(100)
	fleet[11].Temps = join(flatSeries(40, 30), rampTail(30, 0.6, 20)) // car_012, now 42 C
	fleet[11].BatteryTemp = 42
	r := BuildScanReport(fleet)
	f := findByID(r, "car_012")
	if f == nil {
		t.Fatalf("car_012 (42 C and climbing) was not flagged: %+v", r)
	}
	if f.Classification != ClassSustainedAnomaly && f.Classification != ClassRisingTrend {
		t.Fatalf("classification = %s", f.Classification)
	}
	if len(r.Flagged) != 1 {
		t.Fatalf("flagged %d cars, want only car_012", len(r.Flagged))
	}
}

func TestScanFlagsCabinFaultAndBatteryFaultTogether(t *testing.T) {
	fleet := healthy(100)
	fleet[67].CabinStatus = "overheating_critical" // car_068
	fleet[67].Speed = 110
	fleet[34].Temps = join(flatSeries(50, 30), rampTail(30, 0.6, 10)) // car_035
	r := BuildScanReport(fleet)
	if len(r.Flagged) != 2 {
		t.Fatalf("flagged %d, want 2: %+v", len(r.Flagged), r.Flagged)
	}
	if f := findByID(r, "car_068"); f == nil || f.Issues[0] != "cabin_overheating_critical" {
		t.Fatalf("car_068 not flagged for cabin: %+v", f)
	}
	if findByID(r, "car_035") == nil {
		t.Fatal("car_035 not flagged")
	}
}

func TestScanFlagsSlowRampAsRisingTrend(t *testing.T) {
	fleet := healthy(100)
	fleet[11].Temps = join(flatSeries(55, 30), rampTail(30, 0.35, 5)) // classified rising_trend, not sustained
	r := BuildScanReport(fleet)
	f := findByID(r, "car_012")
	if f == nil || f.Classification != ClassRisingTrend || f.Issues[0] != "battery_rising_trend" {
		t.Fatalf("slow ramp not flagged as rising_trend: %+v", f)
	}
}

func TestScanListsLoneSpikeButDoesNotFlagIt(t *testing.T) {
	fleet := healthy(100)
	fleet[19].Temps = join(flatSeries(59, 30), []float64{42}) // car_020
	r := BuildScanReport(fleet)
	if len(r.Flagged) != 0 {
		t.Fatalf("lone spike was flagged: %+v", r.Flagged)
	}
	if len(r.TransientSpikes) != 1 || r.TransientSpikes[0] != "car_020" {
		t.Fatalf("spikes = %v, want [car_020]", r.TransientSpikes)
	}
}

// A battery that has been mitigated and is cooling must not stay flagged forever.
func TestScanDoesNotFlagCoolingVehicle(t *testing.T) {
	fleet := healthy(100)
	cooling := make([]float64, 20)
	for k := range cooling {
		cooling[k] = 38 - 0.8*float64(k)
	}
	fleet[11].Temps = join(flatSeries(40, 30), cooling)
	r := BuildScanReport(fleet)
	if findByID(r, "car_012") != nil {
		t.Fatal("cooling car_012 is still flagged")
	}
}

func TestScanReportsSlopeSoVerificationCanReadIt(t *testing.T) {
	fleet := healthy(100)
	fleet[11].Temps = repeat(85, 60) // hot plateau: still above the absolute limit
	cool := make([]float64, 8)
	for k := range cool {
		cool[k] = 85 - 0.8*float64(k+1)
	}
	fleet[11].Temps = join(repeat(85, 52), cool)
	r := BuildScanReport(fleet)
	f := findByID(r, "car_012")
	if f == nil {
		t.Fatal("hot car not flagged")
	}
	if f.Slope >= 0 {
		t.Fatalf("slope = %v, want negative while cooling", f.Slope)
	}
}

func TestScanWholeFeedStaleIsNotHealthy(t *testing.T) {
	fleet := healthy(100)
	for i := range fleet {
		fleet[i].AgeSeconds = 19
	}
	fleet[11].Temps = join(flatSeries(40, 30), rampTail(30, 0.6, 20))
	r := BuildScanReport(fleet)
	if r.FeedStatus != FeedStale {
		t.Fatalf("status = %s, want stale", r.FeedStatus)
	}
	if len(r.Flagged) != 0 {
		t.Fatal("stale feed must not produce flagged vehicles to act on")
	}
	if r.StaleCount != 100 || len(r.StaleDevices) != maxStaleIDsListed {
		t.Fatalf("stale_count=%d listed=%d", r.StaleCount, len(r.StaleDevices))
	}
}

func TestScanEmptyFleetIsStaleNotHealthy(t *testing.T) {
	r := BuildScanReport(nil)
	if r.FeedStatus != FeedEmpty || len(r.Flagged) != 0 {
		t.Fatalf("status = %s", r.FeedStatus)
	}
}

func TestScanFewStaleCarsDoNotShutDownTheFleet(t *testing.T) {
	fleet := healthy(100)
	fleet[3].AgeSeconds = 40
	fleet[4].AgeSeconds = -1
	fleet[11].Temps = join(flatSeries(40, 30), rampTail(30, 0.6, 20))
	r := BuildScanReport(fleet)
	if r.FeedStatus != FeedOK || r.StaleCount != 2 || r.Checked != 98 {
		t.Fatalf("status=%s stale=%d checked=%d", r.FeedStatus, r.StaleCount, r.Checked)
	}
	if findByID(r, "car_012") == nil {
		t.Fatal("car_012 should still be flagged")
	}
}

func TestScanNeverAnalysesAStaleCar(t *testing.T) {
	fleet := healthy(100)
	fleet[11].Temps = join(flatSeries(40, 30), rampTail(30, 0.6, 20))
	fleet[11].AgeSeconds = 30
	r := BuildScanReport(fleet)
	if findByID(r, "car_012") != nil {
		t.Fatal("stale car was analysed and flagged")
	}
	if len(r.StaleDevices) != 1 || r.StaleDevices[0] != "car_012" {
		t.Fatalf("stale devices = %v", r.StaleDevices)
	}
}

func TestScanExactlyHalfStaleIsStillOKButMoreThanHalfIsNot(t *testing.T) {
	fleet := healthy(10)
	for i := 0; i < 5; i++ {
		fleet[i].AgeSeconds = 60
	}
	if r := BuildScanReport(fleet); r.FeedStatus != FeedOK {
		t.Fatalf("5 of 10 stale: status = %s, want ok", r.FeedStatus)
	}
	fleet[5].AgeSeconds = 60
	if r := BuildScanReport(fleet); r.FeedStatus != FeedStale {
		t.Fatalf("6 of 10 stale: status = %s, want stale", r.FeedStatus)
	}
}

func TestScanDoesNotReorderItsInput(t *testing.T) {
	fleet := healthy(5)
	fleet[0], fleet[4] = fleet[4], fleet[0] // car_005 first, car_001 last
	fleet[4].CabinStatus = "overheating_critical"
	r := BuildScanReport(fleet)
	if fleet[0].DeviceID != "car_005" {
		t.Fatal("input slice was reordered")
	}
	if len(r.Flagged) != 1 || r.Flagged[0].DeviceID != "car_001" {
		t.Fatalf("flagged = %+v", r.Flagged)
	}
}

func TestIsFreshAndCheckFreshForWrite(t *testing.T) {
	cases := []struct {
		age   int64
		fresh bool
	}{{-1, false}, {0, true}, {1, true}, {15, true}, {16, false}, {19, false}, {3600, false}}
	for _, c := range cases {
		if IsFresh(c.age) != c.fresh {
			t.Errorf("IsFresh(%d) = %v, want %v", c.age, IsFresh(c.age), c.fresh)
		}
		err := CheckFreshForWrite(c.age)
		if c.fresh && err != nil {
			t.Errorf("CheckFreshForWrite(%d) rejected: %v", c.age, err)
		}
		if !c.fresh && err == nil {
			t.Errorf("CheckFreshForWrite(%d) allowed a stale or unknown reading", c.age)
		}
	}
}

func TestTempsFromLogsOrdersOldestFirstAndSkipsBadEntries(t *testing.T) {
	logs := []string{`{"battery_temp": 33}`, `not json`, `{"battery_temp": 32}`, `{"battery_temp": 31}`}
	got := TempsFromLogs(logs)
	want := []float64{31, 32, 33}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}
