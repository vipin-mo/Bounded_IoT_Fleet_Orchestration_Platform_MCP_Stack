.PHONY: build run simulator up down clean clean-logs test eval eval-baseline latency series

# Default task to build the native cross-platform Go binary
build:
	@echo "Compiling Go MCP Server natively for your host machine..."
	cd mcp-server-go && go build -o mcp-server-go-binary main.go

# Spin up the Redis Docker infrastructure
up:
	docker-compose up -d

# Spin down the infrastructure
down:
	docker-compose down

# Run the Fleet Simulator (pass options with ARGS, e.g. make simulator ARGS="--seed 7")
simulator:
	python fleet-simulator/simulator.py $(ARGS)

# Run the AI Orchestrator Agent (Depends on the Go server being pre-compiled)
run: build
	python agent-client-python/main.py

# Run unit tests (no Redis or API key needed)
test:
	cd mcp-server-go && go vet ./... && go test ./... -v
	python -m pytest -v

# Run the agent against many simulated fleets and score every run (needs Redis, the binary and an API key).
# Example: make eval ARGS="--runs 20 --seed-base 1000"
eval: build
	python scripts/eval_runs.py $(ARGS)

# The same evaluation with the rule-based agent: no API key, no cost. Compare it with `make eval`.
# Example: make eval-baseline ARGS="--runs 20 --seed-base 1000"
eval-baseline: build
	python scripts/eval_runs.py --agent baseline $(ARGS)

# How fast the Go detector notices a battery fault at each heating rate (no Redis, no key).
latency:
	cd mcp-server-go && go test ./server -run TestDetectionLatencyReport -v

# Rebuild testdata/detector_series.json after changing the simulator's battery physics.
series:
	python scripts/gen_detector_series.py

# System wide artifact cleanup
clean:
	@echo "Scouring temporary build files, binary artifacts, and cache pools..."
	rm -f mcp-server-go/mcp-server-go-binary
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.tmp" -delete

# Separate command to clear historical audit logs if necessary
clean-logs:
	@echo "Flushing structured transaction logs..."
	rm -rf logs/
