import json
import anthropic
import asyncio

from agent.memory import ConversationMemory
from agent.planner import create_plan, parse_plan

from configs.settings import (
    ANTHROPIC_API_KEY,
    MODEL_NAME,
    MAX_TOKENS,
    MEMORY_WINDOW
)

from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from datetime import datetime, timedelta


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
memory = ConversationMemory(MEMORY_WINDOW)

# ---------------------------------------------------
# 🔥 GLOBALS
# ---------------------------------------------------
_mcp_client = None
_loop = None

# ---------------------------------------------------
# 🔥 CLEANUP, Helper function to ensure cleanup server
# ---------------------------------------------------
def _cleanup_mcp():
    global _mcp_client, _loop
    if _mcp_client and _loop:
        _loop.run_until_complete(_mcp_client.__aexit__(None, None, None))

# Helper function to ensure system context is included in the final response, especially regarding location limitations
# Detect location from query (can be improved with better NLP or a dedicated tool)
def detect_location(query: str):
    query = query.lower()

    if "spain" in query:
        return "spain"

    # naive detection (can be improved later)
    known_locations = ["india", "usa", "germany", "france", "uk"]
    for loc in known_locations:
        if loc in query:
            return loc

    return None

def add_system_context(final_text, query):
    location = detect_location(query)

    note = "\n\n---\n📍 **System Context**:\nThis system is calibrated for **Spain**.\n"

    if location and location != "spain":
        note += f"⚠️ Requested: {location.title()} → Using Spain data instead.\n"

    return final_text + note

def sanitize_args(tool_name, args):
    tool_schemas = {
        "get_weather_forecast_tool": {"date"},
        "get_energy_forecast_tool": {"date"},
        "get_adjusted_forecast_tool": {"date"},
    }

    allowed = tool_schemas.get(tool_name, set())
    return {k: v for k, v in args.items() if k in allowed}

# ---------------------------------------------------
# 🔥 EVALUATOR (continue / stop / replan)
# ---------------------------------------------------
def evaluate_step(query, step, result_text, tool_outputs):

    tool_name = step.get("tool")

    if tool_name == "get_adjusted_forecast_tool":
        return {"action": "stop"}

    if "adjusted_total_kwh" in result_text:
        return {"action": "stop"}

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": f"""
User query:
{query}

Executed step:
{step}

Tool result:
{result_text}

Return STRICT JSON:
{{"action": "continue" | "stop" | "replan"}}

Rules:
- stop if enough info
- continue if more tools needed
- replan if wrong tool
"""
            }
        ]
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    try:
        return json.loads(text)
    except:
        return {"action": "continue"}

# ---------------------------------------------------
# 🔥 MAIN ENTRY
# ---------------------------------------------------
def run_agent(query):
    global _mcp_client, _loop

    if _loop is None:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_start_mcp_client())  # ← start ONCE

    return _loop.run_until_complete(_run_agent_async(query, _mcp_client))

# ---------------------------------------------------
# 🔥 START MCP CLIENT ONCE
# ---------------------------------------------------
async def _start_mcp_client():
    global _mcp_client

    transport = StdioTransport(
        command="python",
        args=["-m", "mcp_v2.server"]
    )

    _mcp_client = Client(transport)
    await _mcp_client.__aenter__()  # ← MCP server starts here, ONCE
    print("[MCP] Server started and ready ✅")

# ---------------------------------------------------
# 🔥 CORE AGENT LOOP
# ---------------------------------------------------
async def _run_agent_async(query, mcp_client):  # ← receives persistent client

    memory.add("user", query)

    final_text = ""
    tool_outputs = {}

    # -------------------------------
    # 🔥 STEP 1: INITIAL PLAN
    # -------------------------------
    plan_text = create_plan(query)
    plan = parse_plan(plan_text)

    print("[INITIAL PLAN]", plan)

    current_plan = plan
    step_index = 0
    replan_count = 0
    MAX_REPLANS = 2

    # ❌ REMOVED: transport = StdioTransport(...)
    # ❌ REMOVED: async with Client(transport) as mcp_client:
    # ✅ Using the persistent mcp_client passed as parameter

    while step_index < len(current_plan):

        step = current_plan[step_index]
        tool_name = step.get("tool")
        tool_input = step.get("args", {})

        # -------------------------------
        # 🔥 DATE NORMALIZATION
        # -------------------------------
        if "date" in tool_input:
            date_str = tool_input["date"].lower().strip()
            today = datetime.today()

            if date_str == "tomorrow":
                tool_input["date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            elif date_str == "today":
                tool_input["date"] = today.strftime("%Y-%m-%d")
            elif date_str == "yesterday":
                tool_input["date"] = (today - timedelta(days=1)).strftime("%Y-%m-%d")

        print(f"[EXEC] {tool_name} | input={tool_input}")

        # -------------------------------
        # 🔥 MCP TOOL CALL
        # ✅ using persistent mcp_client directly
        # -------------------------------
        clean_args = sanitize_args(tool_name, tool_input)

        print(f"[SANITIZED INPUT] {clean_args}")

        result = await mcp_client.call_tool(tool_name, clean_args)
        # result = await mcp_client.call_tool(tool_name, tool_input)

        result_text = "".join(
            item.text for item in result.content if hasattr(item, "text")
        )

        print(f"[RESULT] {result_text}")

        tool_outputs[tool_name] = result_text

        # -------------------------------
        # 🔥 EVALUATE STEP
        # -------------------------------
        decision = evaluate_step(query, step, result_text, tool_outputs)

        print(f"[DECISION] {decision}")

        # -------------------------------
        # 🔥 DECISION HANDLING
        # -------------------------------
        if decision.get("action") == "stop":
            print("[STOPPED EARLY]")
            break

        elif decision.get("action") == "replan":

            if replan_count >= MAX_REPLANS:
                print("[REPLAN LIMIT REACHED]")
                break

            replan_count += 1
            print("[REPLANNING...]")

            new_plan_text = create_plan(query, tool_outputs)
            current_plan = parse_plan(new_plan_text)

            print("[NEW PLAN]", current_plan)

            step_index = 0
            continue

        else:
            step_index += 1

    # -------------------------------
    # 🔥 FINAL RESPONSE
    # -------------------------------
    final_response = client.messages.create(
                    model=MODEL_NAME,
                    max_tokens=MAX_TOKENS,
                    temperature=0, # Deterministic final answer
                    # ✅ SYSTEM = HARD CONTROL
                    system="""
                You are an energy AI analyst.

                STRICT RULES (MANDATORY):

                - All data is for Spain only
                - Never mention any other location in output
                - Even if user asks for Delhi, India, etc:
                    → DO NOT mention it
                    → ALWAYS respond with Spain-based context

                - You MUST NOT generate:
                    "Weather in Delhi"
                    "Solar output in India"

                - ALWAYS say:
                    "Weather in Spain"
                    "Solar production in Spain"

                - Location is NOT user-controllable

                - Be precise, structured, and analytical
                """,

                    messages=[
                        {
                            "role": "user",
                            "content": f"""
                                    User query:
                                    {query}

                                    Executed plan:
                                    {current_plan}

                                    Tool outputs:
                                    {tool_outputs}

                                    -----------------------------------

                                    Generate the final answer using STRICT FORMAT.

                                    ## Summary
                                    - Provide a concise analytical summary of solar production in Spain.

                                    ## Key Insights
                                    - Provide EXACTLY 3 to 5 bullet points
                                    - Each must be derived from tool outputs
                                    - Do NOT leave empty
                                    - Do NOT write placeholders like "1."

                                    ## Data Analysis
                                    - Explain patterns (peak hours, decline, anomalies)

                                    ## Conclusion
                                    - Provide final interpretation

                                    MANDATORY RULES:
                                    - Never skip any section
                                    - Never leave a section empty
                                    - Do not rename section headers
                                    - Do not add extra sections
                                    """
                        }
                    ]
                )

    for block in final_response.content:
        if hasattr(block, "text"):
            final_text += block.text

        
    final_text = add_system_context(final_text, query)    
    memory.add("assistant", final_text)
    return final_text