"""A rule-based agent with no model. It uses the same MCP tools, the same safety checks and the same
ledger as the Claude agent (main.py), so scripts/eval_runs.py can score both on the same cases.

Why it exists: the detection and the stale-data checks live in the Go server, so a few fixed rules can
act on what `scan_fleet` returns. Running the same evaluation with this agent shows what the model
adds (reading the manual, writing the report, handling odd situations) and what it costs: tokens and
seconds. It needs no API key and costs nothing.

    python agent-client-python/baseline_agent.py        # after `make build`, with Redis and the simulator running
    make eval ARGS="--agent baseline --runs 20"

The rules:
  1. scan_fleet. If feed_status is not "ok": report STALE TELEMETRY, change nothing, stop.
  2. For each flagged vehicle: a battery issue gets power_parameter=eco_mode, a critical cabin issue gets
     speed_governor=50. Every write passes the same two checks the Claude agent has (feed ok, valid payload).
  3. wait 8 s, scan again. Fix anything newly flagged (once). Stop when every fix is confirmed (cabin no
     longer flagged, battery no longer flagged or cooling) or after MAX_VERIFY_ROUNDS re-checks.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

from errors import describe_failure
from guardrails import check_feed_allows_writes, parse_feed_status, validate_ota_payload

VERIFY_WAIT_SECONDS = 8
MAX_VERIFY_ROUNDS = 4

# Where the run stands, so a crash can be written to the ledger as an aborted session.
SESSION = {"started": False, "status": "not_started"}


def log_agent_transaction(event_type, payload):
    """Append one event to the daily ledger. Same file and same layout as main.py writes."""
    os.makedirs("logs", exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join("logs", f"fleet_agent_ledger_{date_str}.jsonl")
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event_type": event_type, "payload": payload}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    if event_type == "SESSION_START":
        SESSION.update(started=True, status="running")
    elif event_type == "SESSION_COMPLETED":
        SESSION["status"] = "completed"
    elif event_type == "SESSION_ABORTED":
        SESSION["status"] = "aborted"


def field_of(obj, *names, default=None):
    """Read a field the MCP SDK spells differently across versions (snake_case in 2.x, camelCase in 1.x)."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def plan_actions(flagged, handled):
    """The writes to make for the flagged vehicles. `handled` holds (device, register) pairs already written.

    Returns a list of (device, register, value, kind). A vehicle with both a battery and a cabin issue
    gets both fixes; nothing is written twice."""
    actions = []
    for vehicle in flagged:
        device = vehicle.get("device_id")
        issues = [str(i) for i in (vehicle.get("issues") or [])]
        if any(i.startswith("battery_") for i in issues) and (device, "power_parameter") not in handled:
            actions.append((device, "power_parameter", "eco_mode", "battery"))
        if "cabin_overheating_critical" in issues and (device, "speed_governor") not in handled:
            actions.append((device, "speed_governor", "50", "cabin"))
    return actions


def unresolved(fixes, flagged):
    """Which fixed (device, kind) pairs are not confirmed by the newest scan."""
    by_device = {v.get("device_id"): v for v in flagged}
    bad = []
    for device, kind in fixes:
        vehicle = by_device.get(device)
        if vehicle is None:
            continue
        issues = [str(i) for i in (vehicle.get("issues") or [])]
        slope = vehicle.get("slope_per_reading")
        cooling = isinstance(slope, (int, float)) and slope < 0
        if kind == "cabin" and any(i.startswith("cabin_") for i in issues):
            bad.append((device, kind))
        elif kind == "battery" and any(i.startswith("battery_") for i in issues) and not cooling:
            bad.append((device, kind))
    return bad


async def call(session, tool, arguments):
    """Call one MCP tool and write the request and the response to the ledger. Returns (text, is_error)."""
    log_agent_transaction("TOOL_REQUESTED", {"tool": tool, "arguments": arguments})
    is_error = False
    try:
        result = await session.call_tool(tool, arguments=arguments)
        is_error = bool(field_of(result, "is_error", "isError", default=False))
        content = getattr(result, "content", None)
        text = getattr(content[0], "text", str(content[0])) if content else "Success: empty response."
    except Exception as exc:   # noqa: BLE001 - a failed tool call is data, not a crash
        is_error, text = True, f"Error executing tool payload: {exc}"
    log_agent_transaction("TOOL_RESPONSE", {"tool": tool, "result": text, "is_error": is_error})
    return text, is_error


def parse_scan(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def finish(turns, summary):
    print(summary)
    log_agent_transaction("SESSION_COMPLETED", {"turns": turns, "total_input_tokens": 0,
                                                "total_output_tokens": 0, "final_summary": summary})


async def run_with_session(session):
    """Run the rules once against an open MCP session."""
    log_agent_transaction("SESSION_START", {"user_intent": "rule-based baseline", "model": "baseline-rules"})
    scans = 0
    handled = set()          # (device, register) written once; never written twice
    fixes = []               # (device, kind) successfully written
    rejected = []            # human-readable notes about writes that were refused
    stale_devices = []
    spikes = []

    async def scan():
        nonlocal scans, stale_devices, spikes
        scans += 1
        text, _ = await call(session, "scan_fleet", {})
        data = parse_scan(text)
        stale_devices = data.get("stale_devices") or stale_devices
        spikes = data.get("transient_spikes_ignored") or spikes
        return data, parse_feed_status(text)

    data, feed = await scan()
    if feed != "ok":
        finish(scans, f"STALE TELEMETRY: feed_status={feed!r}. No vehicle was changed. "
                      f"{data.get('message', '')}".strip())
        return

    for _ in range(MAX_VERIFY_ROUNDS):
        for device, register, value, kind in plan_actions(data.get("flagged", []), handled):
            handled.add((device, register))
            payload = {"device_id": device, "parameter": register, "value": value}
            allowed, why = check_feed_allows_writes(feed)
            if allowed:
                allowed, why = validate_ota_payload(payload)
            if not allowed:
                log_agent_transaction("GUARDRAIL_VIOLATION", {"tool": "send_ota_command", "arguments": payload, "reason": why})
                rejected.append(f"{device} {register}: {why}")
                continue
            text, is_error = await call(session, "send_ota_command", payload)
            if is_error:
                rejected.append(f"{device} {register}: {text}")
            else:
                fixes.append((device, kind))

        if not fixes:
            break                                  # nothing was fixed (a healthy fleet, or every write refused)
        await call(session, "wait_for_telemetry", {"seconds": VERIFY_WAIT_SECONDS})
        data, feed = await scan()
        if feed != "ok":
            finish(scans, f"STALE TELEMETRY appeared while verifying (feed_status={feed!r}). No further changes were made.")
            return
        if not unresolved(fixes, data.get("flagged", [])) and not plan_actions(data.get("flagged", []), handled):
            break

    bad = set(unresolved(fixes, data.get("flagged", [])))
    lines = [f"Rule-based run: {scans} scans, {len(fixes)} fixes applied, feed {feed}."]
    for device, kind in fixes:
        lines.append(f"- {device} ({kind}): {'UNRESOLVED' if (device, kind) in bad else 'RESOLVED'}")
    if not fixes and not rejected:
        lines.append("No vehicle needed action.")
    lines += [f"- refused: {note}" for note in rejected]
    if stale_devices:
        lines.append(f"Stale vehicles left untouched: {', '.join(stale_devices)}")
    if spikes:
        lines.append(f"One-reading spikes ignored: {', '.join(spikes)}")
    finish(scans, "\n".join(lines))


async def main_async():
    # Imported here so the rules above can be tested without the MCP package.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command="./mcp-server-go/mcp-server-go-binary", args=[], env=os.environ.copy())
    print("Connecting to Go MCP Server infrastructure via Stdio channels...")
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await run_with_session(session)


def record_failure(exc):
    detail = describe_failure(exc)
    if SESSION["started"] and SESSION["status"] == "running":
        log_agent_transaction("SESSION_ABORTED", {"reason": "exception", "error": detail})
    elif not SESSION["started"]:
        log_agent_transaction("STARTUP_FAILED", {"error": detail})


def main():
    """Exit codes: 0 finished, 2 stopped early, 1 crashed, 130 Ctrl+C. Same meaning as main.py."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        if SESSION["started"] and SESSION["status"] == "running":
            log_agent_transaction("SESSION_ABORTED", {"reason": "interrupted"})
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:   # includes ExceptionGroup from the MCP client
        print(f"\nERROR: {describe_failure(exc)}", file=sys.stderr)
        record_failure(exc)
        return 1
    return 0 if SESSION["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
