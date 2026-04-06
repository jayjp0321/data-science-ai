import anthropic
import json
from datetime import datetime, timedelta

from configs.settings import MODEL_NAME, MAX_TOKENS, ANTHROPIC_API_KEY
from mcp_core.server.registry import list_tools


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _get_today_dates():
    today_dt = datetime.today()
    today = today_dt.strftime("%Y-%m-%d")
    tomorrow = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    return today, tomorrow


# ---------------------------------------------------
# 🔥 MAIN PLANNER
# ---------------------------------------------------


# Prompt for planner LLM. Emphasizes strict tool usage rules and date handling.

PLANNER_SYSTEM_PROMPT = """
You are an energy planning agent for Spain.
Your responsibilities:
- Understand the user query deeply
- Decide optimal tool usage
- Prefer best tool instead of combining manually
 
You have access to these tools:
- get_weather_forecast_tool: fetches hourly weather data (temperature, cloud cover)
- get_energy_forecast_tool: fetches hourly solar energy production forecast in MW
- get_adjusted_forecast_tool: fetches weather-adjusted solar production (accounts for cloud cover impact)
 
STRICT RULES:
1. For weather queries → use ONLY get_weather_forecast_tool
2. For solar/energy queries → use get_energy_forecast_tool. If adjusted output is also needed, add get_adjusted_forecast_tool.
3. For impact/combined queries (e.g. "impact of weather on solar", "how does weather affect production") → 
   use ALL THREE tools in this order:
   1. get_weather_forecast_tool
   2. get_energy_forecast_tool  
   3. get_adjusted_forecast_tool
4. Always use date format YYYY-MM-DD. Resolve relative dates (today, tomorrow) before planning.
5. NEVER invent tools

6. If replanning:
   - Fix previous mistakes
   - Avoid repeating same wrong tool
   - Choose better tool if available
 
Return a JSON array of steps. Example for impact query:
[
  {"tool": "get_weather_forecast_tool",   "args": {"date": "2026-04-05"}},
  {"tool": "get_energy_forecast_tool",    "args": {"date": "2026-04-05"}},
  {"tool": "get_adjusted_forecast_tool",  "args": {"date": "2026-04-05"}}
]
"""


def create_plan(query, tool_outputs=None):
    """
    Generates a tool execution plan using LLM.
    Supports both initial planning and replanning.
    """

    tools = list_tools()
    today, tomorrow = _get_today_dates()

    # 🔥 Add context for replanning
    context_block = ""
    if tool_outputs:
        context_block = f"""
Previous tool outputs:
{json.dumps(tool_outputs, indent=2)}
"""

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=PLANNER_SYSTEM_PROMPT,
        #         system="""
        # You are an intelligent AI planner for an MCP-based agent.
        # Your responsibilities:
        # - Understand the user query deeply
        # - Decide optimal tool usage
        # - Prefer best tool instead of combining manually
        # Available tools (IMPORTANT):
        # - get_weather_forecast_tool → weather data
        # - get_energy_forecast_tool → solar forecast
        # - get_adjusted_forecast_tool → weather-adjusted forecast (BEST for combined reasoning)
        # Planning rules:
        # 1. If query is ONLY weather → use get_weather_forecast_tool
        # 2. If query is ONLY solar production → use get_energy_forecast_tool
        # 3. If query involves weather impact on solar:
        #    → PREFER get_adjusted_forecast_tool (DO NOT manually combine unless necessary)
        # 4. Use multiple tools ONLY if required
        # 5. Always extract date in YYYY-MM-DD format
        # 6. NEVER invent tools
        # 7. If replanning:
        #    - Fix previous mistakes
        #    - Avoid repeating same wrong tool
        #    - Choose better tool if available
        # Output format (STRICT JSON ONLY):
        # [
        #   {"tool": "tool_name", "args": {...}}
        # ]
        # NO explanation. NO markdown.
        # """,
        messages=[
            {
                "role": "user",
                "content": f"""
User query:
{query}

Today's date: {today}
Tomorrow: {tomorrow}

{context_block}

Available tools:
{json.dumps(tools, indent=2)}

Instructions:
- Convert "today" → {today}
- Convert "tomorrow" → {tomorrow}
- Use real dates only
- Weather API supports near-term forecast only

Return ONLY JSON list.
""",
            }
        ],
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    print("\n[PLANNER RAW OUTPUT]:", text)

    return text


# ---------------------------------------------------
# 🔥 PLAN PARSER (ROBUST)
# ---------------------------------------------------
def parse_plan(plan_text):
    try:
        cleaned = plan_text.strip()

        # Remove markdown if present
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "")
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

        parsed = json.loads(cleaned)

        # ✅ Validate structure
        if not isinstance(parsed, list):
            raise ValueError("Plan is not a list")

        for step in parsed:
            if "tool" not in step:
                raise ValueError("Missing tool key")

            if "args" not in step:
                step["args"] = {}

        return parsed

    except Exception as e:
        print("[PLANNER PARSE ERROR]:", e)
        return []
