.PHONY: build run simulator up down clean clean-logs

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

# Run the Fleet Simulator
simulator:
	python fleet-simulator/simulator.py

# Run the AI Orchestrator Agent (Depends on the Go server being pre-compiled)
run: build
	python agent-client-python/main.py

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
