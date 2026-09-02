package server

import (
	"encoding/json"
	"fmt"
	"math"
	"mcp-server-go/database"
	"os"
	"path/filepath"
	"strconv"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Structural schemas for arguments passed by the LLM Orchestrator
type FleetSnapshotArgs struct {
	MinSpeed float64
	MinTemp  float64
}

type OTACommandArgs struct {
	DeviceID  string
	Parameter string
	Value     string
}

type HistoricalLogsArgs struct {
	DeviceID string
}

func getFloat(m map[string]interface{}, key string) float64 {
	if val, ok := m[key]; ok {
		if f, ok := val.(float64); ok {
			return f
		}
	}
	return 0.0
}

func getString(m map[string]interface{}, key string) string {
	if val, ok := m[key]; ok {
		if s, ok := val.(string); ok {
			return s
		}
	}
	return ""
}

// HandleGetFleetSnapshot scans Redis hashes with structured validation protections
func HandleGetFleetSnapshot(arguments map[string]interface{}) (*mcp.CallToolResult, error) {
	args := FleetSnapshotArgs{
		MinSpeed: getFloat(arguments, "min_speed"),
		MinTemp:  getFloat(arguments, "min_temp"),
	}

	var matchingDevices []map[string]interface{}

	keys, err := database.RedisClient.Keys(database.Ctx, "device:*").Result()
	if err != nil {
		return nil, err
	}

	for _, key := range keys {
		data, err := database.RedisClient.HGetAll(database.Ctx, key).Result()
		if err != nil || len(data) == 0 {
			continue
		}

		speed, errSpeed := strconv.ParseFloat(data["speed"], 64)
		temp, errTemp := strconv.ParseFloat(data["battery_temp"], 64)

		// Skip record processing if underlying fields contain invalid configurations
		if errSpeed != nil || errTemp != nil {
			continue
		}

		if speed >= args.MinSpeed && temp >= args.MinTemp {
			matchingDevices = append(matchingDevices, map[string]interface{}{
				"device_id":    data["device_id"],
				"speed":        speed,
				"battery_temp": temp,
				"status":       data["cabin_status"],
			})
		}
	}

	resultBytes, _ := json.Marshal(matchingDevices)
	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{
				Text: string(resultBytes),
			},
		},
	}, nil
}

// HandleSendOTACommand alters dynamic fields inside the targeted fleet database container
func HandleSendOTACommand(arguments map[string]interface{}) (*mcp.CallToolResult, error) {
	args := OTACommandArgs{
		DeviceID:  getString(arguments, "device_id"),
		Parameter: getString(arguments, "parameter"),
		Value:     getString(arguments, "value"),
	}

	redisKey := fmt.Sprintf("device:%s", args.DeviceID)

	exists, _ := database.RedisClient.Exists(database.Ctx, redisKey).Result()
	if exists == 0 {
		return &mcp.CallToolResult{
			Content: []mcp.Content{
				&mcp.TextContent{
					Text: fmt.Sprintf("Failure: Device %s not found in fleet registry map", args.DeviceID),
				},
			},
		}, nil
	}

	// Dynamic register selection based on orchestrator parameter choices
	if err := database.RedisClient.HSet(database.Ctx, redisKey, args.Parameter, args.Value).Err(); err != nil {
		return nil, err
	}

	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{
				Text: fmt.Sprintf("Success: Over-The-Air command deployed to %s. Register '%s' updated to '%s'.", args.DeviceID, args.Parameter, args.Value),
			},
		},
	}, nil
}

// HandleGetHistoricalLogs reads string arrays out of targeted list elements
func HandleGetHistoricalLogs(arguments map[string]interface{}) (*mcp.CallToolResult, error) {
	args := HistoricalLogsArgs{
		DeviceID: getString(arguments, "device_id"),
	}

	logKey := fmt.Sprintf("logs:%s", args.DeviceID)
	logs, err := database.RedisClient.LRange(database.Ctx, logKey, 0, 9).Result()
	if err != nil {
		return nil, err
	}

	var logSummary string
	for _, entry := range logs {
		logSummary += entry + "\n"
	}

	if logSummary == "" {
		logSummary = fmt.Sprintf("No historical timeline logs found for tracking key %s", args.DeviceID)
	}

	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{
				Text: logSummary,
			},
		},
	}, nil
}

// HandleMLAnomalyAnalysis computes mathematical Z-Scores across runtime metrics windows
func HandleMLAnomalyAnalysis(arguments map[string]interface{}) (*mcp.CallToolResult, error) {
	deviceID := getString(arguments, "device_id")
	logKey := fmt.Sprintf("logs:%s", deviceID)

	logs, err := database.RedisClient.LRange(database.Ctx, logKey, 0, 9).Result()
	if err != nil || len(logs) < 3 {
		return &mcp.CallToolResult{
			Content: []mcp.Content{
				&mcp.TextContent{
					Text: "Insufficient data windows for mathematical evaluation.",
				},
			},
		}, nil
	}

	var temps []float64
	var sum float64

	for _, entry := range logs {
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(entry), &parsed); err == nil {
			if val, ok := parsed["battery_temp"]; ok {
				var t float64
				switch v := val.(type) {
				case float64:
					t = v
				case string:
					t, _ = strconv.ParseFloat(v, 64)
				}
				if t > 0 {
					temps = append(temps, t)
					sum += t
				}
			}
		}
	}

	if len(temps) < 3 {
		return &mcp.CallToolResult{
			Content: []mcp.Content{
				&mcp.TextContent{
					Text: "Insufficient structural historical float fields extracted.",
				},
			},
		}, nil
	}

	mean := sum / float64(len(temps))
	var varianceSum float64
	for _, t := range temps {
		varianceSum += math.Pow(t-mean, 2)
	}
	stdDev := math.Sqrt(varianceSum / float64(len(temps)))

	if stdDev == 0 {
		stdDev = 0.01
	}

	latestData, _ := database.RedisClient.HGetAll(database.Ctx, fmt.Sprintf("device:%s", deviceID)).Result()
	latestTemp, _ := strconv.ParseFloat(latestData["battery_temp"], 64)

	zScore := (latestTemp - mean) / stdDev
	status := "nominal"
	if zScore > 2.5 {
		status = "anomaly_detected"
	}

	responsePayload := map[string]interface{}{
		"device_id":         deviceID,
		"rolling_mean_temp": math.Round(mean*100) / 100,
		"current_temp":      latestTemp,
		"computed_z_score":  math.Round(zScore*100) / 100,
		"ml_classification": status,
	}

	resultBytes, _ := json.Marshal(responsePayload)
	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{
				Text: string(resultBytes),
			},
		},
	}, nil
}

// HandleManualVectorSearch locates and streams manual data files across nested targets
func HandleManualVectorSearch(arguments map[string]interface{}) (*mcp.CallToolResult, error) {
	query := getString(arguments, "query")
	manualPath := "./agent-client-python/vehicle_fault_manual.md"

	if _, err := os.Stat(manualPath); os.IsNotExist(err) {
		manualPath = filepath.Join("..", "agent-client-python", "vehicle_fault_manual.md")
	}

	content, err := os.ReadFile(manualPath)
	if err != nil {
		return &mcp.CallToolResult{
			Content: []mcp.Content{
				&mcp.TextContent{
					Text: "System Error: Maintenance manual documentation store could not be located.",
				},
			},
		}, nil
	}

	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{
				Text: fmt.Sprintf("Extracted Relevant Technical Manual References for query '%s':\n\n%s", query, string(content)),
			},
		},
	}, nil
}
