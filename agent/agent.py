import json
import anthropic
import asyncio
from services.solar_adjustment_service import SolarAdjustmentService
from agent.memory import ConversationMemory
from configs.settings import (
    ANTHROPIC_API_KEY,
    MODEL_NAME,
    MAX_TOKENS,
    MEMORY_WINDOW
)

#from fastmcp import MCPClient
from fastmcp.client import Client
from fastmcp.client.transports.stdio import StdioTransport

# -------------------------------
# MCP CLIENT
# -------------------------------

transport = StdioTransport(
    command="python",
    args=["-m", "mcp_v2.server"]
)

mcp_client = Client(transport)


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
memory = ConversationMemory(MEMORY_WINDOW)


# -------------------------------
# SYSTEM PROMPT
# -------------------------------
SYSTEM_PROMPT = """
You are an energy AI agent.

You have access to tools:
- get_weather_forecast_tool

Use tools whenever required.

If the user asks about weather or solar production,
you MUST call tools before answering.

Always base your answer on tool results.
"""


# -------------------------------
# JSON SAFE HELPER
# -------------------------------
def make_json_safe(obj):
    import pandas as pd

    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif hasattr(obj, "item"):
        return obj.item()
    else:
        return obj

# ✅ ENTRY POINT (used by main.py)
def run_agent(query):
    return asyncio.run(_run_agent_async(query))

# -------------------------------
#  ACTUAL LOGIC (async)
# -------------------------------
async def _run_agent_async(query):

    memory.add("user", query)

    final_text = ""
    tool_outputs = {}

    async with mcp_client:

        while True:

            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=MAX_TOKENS,
                tools=await mcp_client.list_tools(),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *memory.get()
                ]
            )

            tool_used = False

            for block in response.content:

                if block.type == "text":
                    final_text += block.text

                elif block.type == "tool_use":

                    tool_used = True

                    tool_name = block.name
                    tool_input = block.input

                    print(f"[MCP TOOL CALL] {tool_name} | input={tool_input}")

                    result = await mcp_client.call_tool(tool_name, tool_input)

                    print(f"[MCP RESULT] {result}")

                    tool_outputs[tool_name] = result

                    memory.add("assistant", response.content)

                    memory.add("user", [{
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(make_json_safe(result))
                    }])

            if not tool_used:
                break

    # Fusion logic remains same
    adjuster = SolarAdjustmentService()

    energy_result = tool_outputs.get("get_energy_forecast_tool")
    weather_result = tool_outputs.get("get_weather_forecast_tool")

    if energy_result and weather_result:
        adjusted_result = adjuster.adjust_forecast(
            energy_result,
            weather_result
        )

        final_text += "\n\nAdjusted Forecast:\n"
        final_text += json.dumps(make_json_safe(adjusted_result), indent=2)

    memory.add("assistant", final_text)

    return final_text