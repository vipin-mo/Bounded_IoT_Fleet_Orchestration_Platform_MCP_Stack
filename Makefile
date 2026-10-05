.PHONY: build run simulator up down clean clean-logs test

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

# Run unit tests
test:
	cd mcp-server-go && go vet ./... && go test ./... -v
	python -m pytest -v

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
