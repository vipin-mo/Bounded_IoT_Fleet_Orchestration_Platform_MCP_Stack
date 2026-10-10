package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type otaCase struct {
	Name      string `json:"name"`
	DeviceID  string `json:"device_id"`
	Parameter string `json:"parameter"`
	Value     string `json:"value"`
	Valid     bool   `json:"valid"`
}

func TestValidateOTACommandSharedCases(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "ota_cases.json"))
	if err != nil {
		t.Fatalf("cannot read shared cases: %v", err)
	}
	var cases []otaCase
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatalf("cannot parse shared cases: %v", err)
	}
	if len(cases) < 25 {
		t.Fatalf("expected at least 25 shared cases, found %d", len(cases))
	}

	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			err := ValidateOTACommand(c.DeviceID, c.Parameter, c.Value)
			if c.Valid && err != nil {
				t.Fatalf("expected valid, got error: %v", err)
			}
			if !c.Valid && err == nil {
				t.Fatalf("expected rejection for device=%q parameter=%q value=%q", c.DeviceID, c.Parameter, c.Value)
			}
		})
	}
}
