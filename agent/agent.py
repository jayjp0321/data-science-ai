import json
import anthropic
import logging

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


# ---------------------------------------------------
# 🔥 LOGGING (ROOT HANDLED)
# ---------------------------------------------------
logger = logging.getLogger(__name__)
logger.propagate = True


# ---------------------------------------------------
# 🔥 GLOBAL CLIENTS
# ---------------------------------------------------
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
memory = ConversationMemory(MEMORY_WINDOW)


# ---------------------------------------------------
# 🔥 LOCATION HANDLING
# ---------------------------------------------------
def detect_location(query: str):
    query = query.lower()

    if "spain" in query:
        return "spain"

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


# ---------------------------------------------------
# 🔥 TOOL HELPERS
# ---------------------------------------------------
def sanitize_args(tool_name, args):
    tool_schemas = {
        "get_weather_forecast_tool": {"date"},
        "get_energy_forecast_tool": {"date"},
        "get_adjusted_forecast_tool": {"date"},
    }

    allowed = tool_schemas.get(tool_name, set())
    return {k: v for k, v in args.items() if k in allowed}


def extract_hourly_data(result_raw):
    try:
        for item in result_raw:
            if hasattr(item, "text"):
                data_dict = json.loads(item.text)

                rows = []
                for timestamp, value in data_dict.items():
                    hour = int(timestamp.split(" ")[1].split(":")[0])

                    rows.append({
                        "hour": hour,
                        "production_mw": value
                    })

                return rows

    except Exception as e:
        logger.error(f"[EXTRACT_ERROR] {str(e)}")

    return []


# ---------------------------------------------------
# 🔥 MCP CLIENT
# ---------------------------------------------------
async def start_mcp_client():
    transport = StdioTransport(
        command="python",
        args=["-m", "mcp_v2.server"]
    )

    mcp_client = Client(transport)
    await mcp_client.__aenter__()

    logger.info("[MCP] Server started ✅")
    return mcp_client


# ---------------------------------------------------
# 🔥 EVALUATOR
# ---------------------------------------------------
def evaluate_step(query, step, result_text, tool_outputs):

    if "adjusted_total_kwh" in result_text:
        return {"action": "stop"}

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=200,
        messages=[{
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
"""
        }]
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
# 🔥 CORE AGENT LOOP (ASYNC)- This is not being consumed in case of LLM token level output/response streaming
# ---------------------------------------------------
async def run_agent_async(query, mcp_client):

    memory.add("user", query)

    final_text = ""
    tool_outputs = {}

    # STEP 1: PLAN
    plan_text = create_plan(query)
    plan = parse_plan(plan_text)

    logger.info(f"[INITIAL PLAN] {plan}")

    current_plan = plan
    step_index = 0
    replan_count = 0
    MAX_REPLANS = 2

    while step_index < len(current_plan):

        step = current_plan[step_index]
        tool_name = step.get("tool")
        tool_input = step.get("args", {})

        # DATE NORMALIZATION
        if "date" in tool_input:
            date_str = tool_input["date"].lower().strip()
            today = datetime.today()

            if date_str == "tomorrow":
                tool_input["date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            elif date_str == "today":
                tool_input["date"] = today.strftime("%Y-%m-%d")
            elif date_str == "yesterday":
                tool_input["date"] = (today - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"[EXEC] {tool_name} | input={tool_input}")

        clean_args = sanitize_args(tool_name, tool_input)
        logger.info(f"[SANITIZED INPUT] {clean_args}")

        result = await mcp_client.call_tool(tool_name, clean_args)
        result_raw = result.content  # KEEP STRUCTURE
        result_text = "".join(
            item.text for item in result.content if hasattr(item, "text")
        )

        logger.info(f"[RESULT] {result_text}")

        #tool_outputs[tool_name] = result_text
        tool_outputs[tool_name] = {
            "text": result_text,
            "raw": result_raw,
            "structured": extract_hourly_data(result_raw)
        }
        # EVALUATION
        decision = evaluate_step(query, step, result_text, tool_outputs)
        logger.info(f"[DECISION] {decision}")

        if decision.get("action") == "stop":
            logger.info("[STOPPED EARLY]")
            break

        elif decision.get("action") == "replan":

            if replan_count >= MAX_REPLANS:
                logger.warning("[REPLAN LIMIT REACHED]")
                break

            replan_count += 1
            logger.info("[REPLANNING...]")

            new_plan_text = create_plan(query, tool_outputs)
            current_plan = parse_plan(new_plan_text)

            logger.info(f"[NEW PLAN] {current_plan}")

            step_index = 0
            continue

        else:
            step_index += 1
    llm_tool_outputs = { k: v["text"] for k, v in tool_outputs.items()}
    # FINAL RESPONSE
    final_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system="""
You are an energy AI analyst.

STRICT RULES (MANDATORY):
- All data is for Spain only
- Never mention any other location in output
- ALWAYS respond with Spain-based context
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
{llm_tool_outputs}

-----------------------------------

Generate the final answer using STRICT FORMAT.

## Summary
- Provide a concise analytical summary of solar production in Spain.

## Key Insights
- Provide EXACTLY 3 to 5 bullet points

## Data Analysis
- Explain patterns

## Conclusion
- Provide final interpretation
"""
            }
        ]
    )

    for block in final_response.content:
        if hasattr(block, "text"):
            final_text += block.text

    final_text = add_system_context(final_text, query)
    memory.add("assistant", final_text)
    return {
                "text": final_text,
                "data": tool_outputs
            }
    #return final_text


# ---------------------------------------------------
# 🔥 STREAMING AGENT
# ---------------------------------------------------
async def run_agent_stream(query, mcp_client):

    memory.add("user", query)

    tool_outputs = {}

    # -------------------------------
    # PLAN + EXECUTION
    # -------------------------------
    plan = parse_plan(create_plan(query))
    logger.info(f"[INITIAL PLAN] {plan}")

    for step in plan:

        tool_name = step.get("tool")
        tool_input = step.get("args", {})

        # DATE NORMALIZATION
        if "date" in tool_input:
            today = datetime.today()
            if tool_input["date"] == "tomorrow":
                tool_input["date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"[EXEC] {tool_name} | input={tool_input}")

        result = await mcp_client.call_tool(
            tool_name,
            sanitize_args(tool_name, tool_input)
        )

        result_raw = result.content
        result_text = "".join(
            item.text for item in result.content if hasattr(item, "text")
        )

        tool_outputs[tool_name] = {
            "text": result_text,
            "raw": result_raw,
            "structured": extract_hourly_data(result_raw)
        }

    llm_tool_outputs = {k: v["text"] for k, v in tool_outputs.items()}

    # -------------------------------
    # 🔥 STREAM LLM (STRUCTURED PROMPT)
    # -------------------------------
    final_text = ""
    last_token = None

    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system="""
You are an energy AI analyst.

STRICT RULES (MANDATORY):
- All data is for Spain only
- Never mention any other location
- Be precise and structured
""",
        messages=[{
            "role": "user",
            "content": f"""
User query:
{query}

Executed plan:
{plan}

Tool outputs:
{llm_tool_outputs}

-----------------------------------

Generate the final answer using STRICT FORMAT.
Always add on new line character after headings and bullet points.
For example, use: ## Summary\\n instead of ## Summary so that the frontend can stream and render in real-time.

## Summary
- Provide a concise analytical summary

## Key Insights
- Provide EXACTLY 3 to 5 bullet points

## Data Analysis
- Explain patterns

## Conclusion
- Provide final interpretation
"""
        }]
    ) as stream:

        for event in stream:

            logger.info(f"[RAW_EVENT] {event.type}")

            if event.type == "content_block_delta":
                if hasattr(event.delta, "text") and event.delta.text:

                    token = event.delta.text

                    logger.info(f"[STREAM_TOKEN] {token}")

                    final_text += token
                    yield token

        # for event in stream:

        #     logger.info(f"[RAW_EVENT] {event.type}")

        #     token = None

        #     # Primary
        #     if hasattr(event, "delta") and hasattr(event.delta, "text"):
        #         token = event.delta.text

        #     # Fallback
        #     elif hasattr(event, "text") and event.type == "text":
        #         token = event.text

        #     # 🔥 Deduplicate
        #     if token and token != last_token:
        #         last_token = token

        #         logger.info(f"[STREAM_TOKEN] {token}")
        #         final_text += token
        #         yield token

    # -------------------------------
    # FINALIZE
    # -------------------------------
    final_text = add_system_context(final_text, query)
    memory.add("assistant", final_text)

    yield "[END]"

    structured = tool_outputs.get(
        "get_energy_forecast_tool", {}
    ).get("structured", [])

    yield json.dumps({
        "type": "meta",
        "structured": structured
    })