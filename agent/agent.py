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
# 🔥 EVALUATOR (continue / stop / replan)
# ---------------------------------------------------
def evaluate_step(query, step, result_text, tool_outputs):

    tool_name = step.get("tool")

    # ----------------------------------
    # ✅ HARD RULE (deterministic)
    # ----------------------------------
    if tool_name == "get_adjusted_forecast_tool":
        return {"action": "stop"}

    # ----------------------------------
    # Optional: detect final metrics
    # ----------------------------------
    if "adjusted_total_kwh" in result_text:
        return {"action": "stop"}

    # ----------------------------------
    # 🔥 FALLBACK → LLM evaluator
    # ----------------------------------
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
    return asyncio.run(_run_agent_async(query))


# ---------------------------------------------------
# 🔥 CORE AGENT LOOP
# ---------------------------------------------------
async def _run_agent_async(query):

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

    # -------------------------------
    # 🔥 MCP CLIENT
    # -------------------------------
    transport = StdioTransport(
        command="python",
        args=["-m", "mcp_v2.server"]
    )

    async with Client(transport) as mcp_client:

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
            # -------------------------------
            result = await mcp_client.call_tool(tool_name, tool_input)

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

Provide final answer with reasoning.
"""
            }
        ]
    )

    for block in final_response.content:
        if hasattr(block, "text"):
            final_text += block.text

    memory.add("assistant", final_text)

    return final_text