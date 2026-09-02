import asyncio
import os
import json
import re
import shutil
from datetime import datetime, timezone
from dotenv import load_dotenv
from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from prompts import SYSTEM_PROMPT

# Load environment configurations
load_dotenv()

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise ValueError("Missing ANTHROPIC_API_KEY in environment or .env file.")

# Initialize the Anthropic Client
anthropic_client = Anthropic()

# Target stable production model matching recent platform upgrades
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

def cleanup_workspace():
    """Removes temporary files and build artifacts to maintain system optimization."""
    print("Cleaning workspace temporary files...")
    temp_targets = ["__pycache__", ".pytest_cache", ".mcp_temp_cache"]
    for target in temp_targets:
        for root, dirs, _ in os.walk("."):
            for d in dirs:
                if d == target:
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)

    for file in os.listdir("."):
        if file.endswith(".tmp") or file.startswith(".gdb_history"):
            try:
                os.remove(file)
            except OSError:
                pass

def log_agent_transaction(event_type: str, payload: dict):
    """Appends agent execution tracks directly into a structured daily JSONL ledger file."""
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file_path = os.path.join(log_dir, f"fleet_agent_ledger_{date_str}.jsonl")

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload
    }
    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

def validate_ota_payload(tool_args: dict) -> tuple[bool, str]:
    """Validates structural safety rules on vehicle parameters prior to hardware deployment."""
    device_id = tool_args.get("device_id", "")
    parameter = tool_args.get("parameter", "")
    value = tool_args.get("value", "")

    # Ensure structural layout is completely satisfied
    if not device_id or not parameter or not value:
        return False, "Guardrail Violation: Missing structural payload parameters."

    if not re.match(r"^car_\d{3}$", device_id):
        return False, f"Guardrail Violation: Invalid Device Identifier format '{device_id}'."

    # Validate Power parameter path constraints
    if parameter == "power_parameter":
        if value != "eco_mode":
            return False, f"Guardrail Policy Violation: Destructive parameter configuration value '{value}' rejected."

    # Validate Cabin Overheating speed governor path constraints
    elif parameter == "speed_governor":
        if not value.isdigit() or not (20 <= int(value) <= 60):
            return False, f"Guardrail Policy Violation: Speed governor value must be a safe numeric limit between 20 and 60 km/h."

    else:
        return False, f"Guardrail Policy Violation: Direct write modification to protected internal register '{parameter}' rejected."

    return True, "Passed Guardrail Checks."


async def run_agent():
    cleanup_workspace()

    # Define standard input-output pipe routing configurations for the Go server binary
    server_params = StdioServerParameters(
        command="./mcp-server-go/mcp-server-go-binary",
        args=[],
        env=os.environ.copy()
    )

    print("Connecting to Go MCP Server infrastructure via Stdio channels...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Handshake complete. Connected successfully!")

            user_prompt = (
                "Scan the active vehicle fleet entries. Identify any devices demonstrating out-of-bounds "
                "telemetry flags, check their statistical ML Z-scores, query the manual, and apply appropriate mitigation governors."
            )
            log_agent_transaction("SESSION_START", {"user_intent": user_prompt})

            messages = [
                {"role": "user", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]

            while True:
                # Fetch available platform capabilities dynamically
                available_mcp_tools = await session.list_tools()
                anthropic_formatted_tools = [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema
                    }
                    for tool in available_mcp_tools.tools
                ]

                print("\nConsulting Claude regarding next operational steps...")
                response = anthropic_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=4000,
                    tools=anthropic_formatted_tools,
                    messages=messages
                )

                messages.append({"role": "assistant", "content": response.content})

                # Check if the agent has reached terminal conclusion
                if response.stop_reason == "end_turn":
                    text_outputs = [block.text for block in response.content if hasattr(block, 'text')]
                    final_answer = "\n".join(text_outputs)
                    print("\nFinal Context Output Matrix from Orchestrator:\n", final_answer)
                    log_agent_transaction("SESSION_COMPLETED", {"final_summary": final_answer})
                    break

                # Process parallel execution loops when tool steps are chosen
                elif response.stop_reason == "tool_use":
                    tool_blocks = [b for b in response.content if getattr(b, 'type', None) == "tool_use"]

                    async def execute_single_tool(block):
                        tool_name = block.name
                        tool_args = block.input
                        tool_id = block.id

                        log_agent_transaction("TOOL_REQUESTED", {"tool": tool_name, "arguments": tool_args})

                        if tool_name == "send_ota_command":
                            is_safe, error_msg = validate_ota_payload(tool_args)
                            if not is_safe:
                                print(f"[GUARDRAIL BLOCK] {error_msg}")
                                log_agent_transaction("GUARDRAIL_VIOLATION", {"tool": tool_name, "arguments": tool_args, "reason": error_msg})
                                return {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": json.dumps({"status": "rejected", "reason": error_msg})
                                }

                        try:
                            tool_result = await session.call_tool(tool_name, arguments=tool_args)
                            if hasattr(tool_result, 'content') and len(tool_result.content) > 0:
                                # Safe string property extraction using object fallbacks
                                content_block = tool_result.content[0]
                                result_text = getattr(content_block, 'text', str(content_block))
                            else:
                                result_text = "Success: Empty response content matrix returned."
                        except Exception as e:
                            result_text = f"Error executing tool payload: {str(e)}"

                        log_agent_transaction("TOOL_RESPONSE", {"tool": tool_name, "result": result_text})
                        return {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result_text
                        }

                    # Execute all tool requests concurrently to prevent thread stalling
                    tool_tasks = [execute_single_tool(block) for block in tool_blocks]
                    tool_results_content = await asyncio.gather(*tool_tasks)

                    messages.append({
                        "role": "user",
                        "content": tool_results_content
                    })

if __name__ == "__main__":
    asyncio.run(run_agent())
