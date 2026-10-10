package server

import (
	"fmt"
	"regexp"
	"strconv"
)

// Writable registers and their allowed values.
const (
	ParamPowerParameter = "power_parameter"
	ParamSpeedGovernor  = "speed_governor"
	PowerModeEco        = "eco_mode"
	MinSpeedGovernor    = 20
	MaxSpeedGovernor    = 60
)

var (
	// Go's \d and $ are strict (ASCII digits, end of text only), but [0-9] makes that explicit.
	deviceIDPattern   = regexp.MustCompile(`^car_[0-9]{3}$`)
	speedValuePattern = regexp.MustCompile(`^[0-9]{1,3}$`)
)

// ValidateOTACommand is the server-side safety check. It runs even if a client skips its own
// guardrail, so a caller that talks to this server directly still cannot write an unsafe value.
func ValidateOTACommand(deviceID, parameter, value string) error {
	if deviceID == "" || parameter == "" || value == "" {
		return fmt.Errorf("device_id, parameter and value are all required")
	}
	if !deviceIDPattern.MatchString(deviceID) {
		return fmt.Errorf("invalid device_id %q", deviceID)
	}

	switch parameter {
	case ParamPowerParameter:
		if value != PowerModeEco {
			return fmt.Errorf("power_parameter only accepts %q, got %q", PowerModeEco, value)
		}
	case ParamSpeedGovernor:
		if !speedValuePattern.MatchString(value) {
			return fmt.Errorf("speed_governor must be a whole number, got %q", value)
		}
		limit, err := strconv.Atoi(value)
		if err != nil {
			return fmt.Errorf("speed_governor must be a whole number, got %q", value)
		}
		if limit < MinSpeedGovernor || limit > MaxSpeedGovernor {
			return fmt.Errorf("speed_governor must be between %d and %d km/h, got %d", MinSpeedGovernor, MaxSpeedGovernor, limit)
		}
	default:
		return fmt.Errorf("register %q is protected and cannot be written", parameter)
	}
	return nil
}
