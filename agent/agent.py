import json
from services.solar_adjustment_service import SolarAdjustmentService
import anthropic
from agent.planner import create_plan, parse_plan
from agent.memory import ConversationMemory
from mcp_core.client.client import call_tool
from configs.settings import (
    ANTHROPIC_API_KEY,
    MODEL_NAME,
    MAX_TOKENS,
    MEMORY_WINDOW
)


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
memory = ConversationMemory(MEMORY_WINDOW)
#solar_adjustment_service = SolarAdjustmentService()

def make_json_safe(obj):
    import pandas as pd

    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif hasattr(obj, "item"):  # numpy
        return obj.item()
    else:
        return obj
    
def run_agent(query):

    memory.add("user", query)

    # -------------------------------
    # Step 1: Create plan
    # -------------------------------
    plan_text = create_plan(query)
    plan = parse_plan(plan_text)
    tool_results_blocks = []

    # -------------------------------
    # Step 2: Execute tools
    # -------------------------------
    results = []

    for step in plan:
        tool_name = step.get("tool")
        args = step.get("args", {})

        result = call_tool(tool_name, args)

        if result.get("status") == "failed":
            return f"Tool `{tool_name}` failed: {result.get('error')}"

        results.append({
            "tool": tool_name,
            "input": args,
            "output": result
        })
    # Make results JSON serializable
    safe_results = make_json_safe(results)
    # -------------------------------
    # Step 3: Final reasoning (MCP style)
    # -------------------------------
    adjuster = SolarAdjustmentService()

    energy_result = None
    weather_result = None

    for r in results:
        if "get_energy_forecast" in r["tool"]:
            energy_result = r["output"]
        elif "get_weather_data" in r["tool"]:
            weather_result = r["output"]

    adjusted_result = None

    if energy_result and weather_result:
        adjusted_result = adjuster.adjust_forecast(
            energy_result,
            weather_result
        )
    
    safe_energy = make_json_safe(energy_result)
    safe_weather = make_json_safe(weather_result)
    safe_adjusted = make_json_safe(adjusted_result)

    final_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[
            *memory.get(),
            {
                "role": "user",
                "content": f"""
                            You are an intelligent energy analyst.

                            User query:
                            {query}

                            Base forecast (ML model output):
                            {json.dumps(safe_energy, indent=2)}

                            Weather data:
                            {json.dumps(safe_weather, indent=2)}

                            Weather-adjusted forecast:
                            {json.dumps(safe_adjusted, indent=2)}

                            Instructions:
                            - Combine insights from all tools
                            - Explain reasoning clearly
                            - Correlate weather and solar production
                            - Highlight the difference between base and adjusted forecast
                            - Quantify the impact of weather (if possible)
                            - Use domain reasoning (cloud cover → irradiance → solar output)

                            Output format:
                            - Summary
                            - Key insights
                            - Reasoning
                            """
            }
        ]
    )
    
    # -------------------------------
    # Step 4: Extract response
    # -------------------------------
    final_text = ""
    for block in final_response.content:
        if hasattr(block, "text"):
            final_text += block.text

    memory.add("assistant", final_text)

    return final_text