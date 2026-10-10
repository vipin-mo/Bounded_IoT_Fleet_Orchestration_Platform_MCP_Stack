"""Proves the Go server rejects unsafe writes even when the Python guardrail is bypassed.

Needs Redis running (make up), the simulator running at least once, and the
Go binary built (make build). No API key is used.

    python scripts/bad_ota_demo.py
"""
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

UNSAFE_CALLS = [
    {"device_id": "car_012", "parameter": "speed_governor", "value": "500"},
    {"device_id": "car_012", "parameter": "battery_temp", "value": "10"},
    {"device_id": "car_012", "parameter": "power_parameter", "value": "turbo"},
    {"device_id": "car_012\n", "parameter": "speed_governor", "value": "50"},
]


def first_text(result):
    return result.content[0].text if result.content else "(empty)"


async def main():
    params = StdioServerParameters(command="./mcp-server-go/mcp-server-go-binary", args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for args in UNSAFE_CALLS:
                result = await session.call_tool("send_ota_command", arguments=args)
                print(f"{args}\n   -> {first_text(result)}\n")


if __name__ == "__main__":
    asyncio.run(main())
