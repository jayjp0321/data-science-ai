# agent.py (UPDATED)

import json
import anthropic
import logging

from async_lru import alru_cache

from agent.memory import ConversationMemory
from agent.planner import create_plan, parse_plan
from agent.context_resolver import ContextResolver
from agent.memory import StructuredMemory

from configs.settings import ANTHROPIC_API_KEY, MODEL_NAME, MAX_TOKENS, MEMORY_WINDOW

from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)
logger.propagate = True

MCP_CLIENT = None

# ---------------------------------------------------
# 🔥 GLOBAL STATE
# ---------------------------------------------------
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
memory = ConversationMemory(MEMORY_WINDOW)
structured_mem = StructuredMemory()
context_resolver = ContextResolver(structured_mem)


# ---------------------------------------------------
# 🔥 HELPERS (unchanged)
# ---------------------------------------------------
def detect_location(query: str):
    query = query.lower()
    if "spain" in query:
        return "spain"
    for loc in ["india", "usa", "germany", "france", "uk"]:
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

                    rows.append({"hour": hour, "production_mw": value})

                return rows

    except Exception as e:
        logger.error(f"[EXTRACT_ERROR] {str(e)}")

    return []


from datetime import datetime, timedelta


def _normalize_date(args: dict) -> dict:
    """
    Ensures 'date' is always present and normalized to YYYY-MM-DD.
    """

    if not args:
        args = {}

    date = args.get("date")
    today = datetime.today()

    # ----------------------------------------
    # 🔥 Handle missing date
    # ----------------------------------------
    if not date:
        normalized = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        return {"date": normalized}

    date = str(date).lower()

    # ----------------------------------------
    # 🔥 Relative terms
    # ----------------------------------------
    if date == "today":
        normalized = today.strftime("%Y-%m-%d")

    elif date == "tomorrow":
        normalized = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    elif date == "yesterday":
        normalized = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    # ----------------------------------------
    # 🔥 Already correct format
    # ----------------------------------------
    else:
        # assume it's already YYYY-MM-DD
        normalized = date

    return {"date": normalized}


# ---------------------------------------------------
# 🔥 MCP CLIENT
# ---------------------------------------------------
async def start_mcp_client():
    global MCP_CLIENT

    transport = StdioTransport(command="python", args=["-m", "mcp_v2.server"])
    MCP_CLIENT = Client(transport)

    await MCP_CLIENT.__aenter__()

    logger.info("[MCP] Server started ✅")

    return MCP_CLIENT  # optional (can keep for compatibility)


# ---------------------------------------------------
# 🔥 EVALUATOR
# ---------------------------------------------------
def evaluate_step(query, step, result_text, tool_outputs):

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
""",
            }
        ],
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
# 🔥 TOOL CALL (CACHED)
# ---------------------------------------------------


@alru_cache(maxsize=32)
async def _call_tool_cached(tool_name: str, date: str):

    logger.info(f"[TOOL CALL] {tool_name} | date={date}")

    result = await MCP_CLIENT.call_tool(tool_name, {"date": date})

    # ----------------------------------------
    # 🔥 HANDLE CallToolResult OBJECT
    # ----------------------------------------
    if hasattr(result, "content"):
        text = str(result.content)
    elif hasattr(result, "output"):
        text = str(result.output)
    else:
        text = str(result)

    return {"text": text, "structured": []}  # you can improve later


# ---------------------------------------------------
# 🔥 CACHE LOGGING
# ---------------------------------------------------
def _log_cache_event(tool, date, before, after):
    if after.hits > before.hits:
        logger.info(f"[CACHE HIT] {tool} | date={date}")
    else:
        logger.info(f"[CACHE MISS] {tool} | date={date}")


# ---------------------------------------------------
# 🔥 STRUCTURED EXTRACTION (TOOL-AWARE)
# ---------------------------------------------------
def extract_structured(tool_name, result_raw):
    try:
        for item in result_raw:

            if not hasattr(item, "text"):
                continue

            data = json.loads(item.text)

            rows = []

            # -------------------------------
            # 🔥 HELPER: Extract hour safely
            # -------------------------------
            def extract_hour(k):
                try:
                    # Case: "2026-04-05 08:00:00" or "2026-04-05 08:00"
                    if " " in k:
                        return int(k.split(" ")[1].split(":")[0])

                    # Case: "08:00" or "08:00:00"
                    if ":" in k:
                        return int(k.split(":")[0])

                    # Case: "8"
                    return int(k)

                except Exception:
                    return None

            # -------------------------------
            # ENERGY TOOL
            # -------------------------------
            if tool_name == "get_energy_forecast_tool":

                # 🔥 Drill into nested key if present (e.g. {"hourly": {...}, "total": ...})
                energy_source = (
                    data.get("hourly")
                    if isinstance(data, dict) and "hourly" in data
                    else data
                )

                if isinstance(energy_source, dict):
                    for k, v in energy_source.items():
                        hour = extract_hour(k)
                        if hour is not None:
                            rows.append({"hour": hour, "production_mw": v})

                elif isinstance(energy_source, list):
                    for row in energy_source:
                        hour = row.get("hour")

                        if isinstance(hour, str) and ":" in hour:
                            hour = int(hour.split(":")[0])

                        value = row.get("production_mw") or row.get("value")

                        if hour is not None:
                            rows.append({"hour": int(hour), "production_mw": value})

                # Fallback: top-level dict with non-nested timestamps
                elif isinstance(data, dict):
                    for k, v in data.items():
                        hour = extract_hour(k)
                        if hour is not None:
                            rows.append({"hour": hour, "production_mw": v})

                return rows

            # -------------------------------
            # WEATHER TOOL
            # -------------------------------
            elif tool_name == "get_weather_forecast_tool":

                # 🔥 Drill into "hourly" key if present
                # Shape: {"date": "...", "avg_temperature": ..., "avg_cloud_cover": ..., "hourly": {"2026-04-05 00:00:00": 17.2, ...}}
                hourly_source = (
                    data.get("hourly")
                    if isinstance(data, dict) and "hourly" in data
                    else data
                )

                avg_temperature = (
                    data.get("avg_temperature") if isinstance(data, dict) else None
                )
                avg_cloud_cover = (
                    data.get("avg_cloud_cover") if isinstance(data, dict) else None
                )

                if isinstance(hourly_source, dict):
                    for k, v in hourly_source.items():
                        hour = extract_hour(k)
                        if hour is not None:
                            rows.append(
                                {
                                    "hour": hour,
                                    "temperature": v,
                                    "avg_temperature": avg_temperature,
                                    "avg_cloud_cover": avg_cloud_cover,
                                }
                            )

                elif isinstance(hourly_source, list):
                    for row in hourly_source:
                        raw_hour = (
                            row.get("hour")
                            or row.get("time")
                            or row.get("timestamp")
                            or row.get("datetime")
                        )
                        if raw_hour is None:
                            continue

                        hour = extract_hour(str(raw_hour))
                        if hour is None:
                            continue

                        rows.append(
                            {
                                "hour": hour,
                                "temperature": (
                                    row.get("temperature")
                                    or row.get("value")
                                    or row.get("cloud_cover")
                                    or row.get("irradiance")
                                ),
                                "avg_temperature": avg_temperature,
                                "avg_cloud_cover": avg_cloud_cover,
                            }
                        )

                return rows

            # -------------------------------
            # ADJUSTED TOOL
            # -------------------------------
            elif tool_name == "get_adjusted_forecast_tool":

                # 🔥 Top-level summary fields — attach to every row
                adjusted_total_kwh = (
                    data.get("adjusted_total_kwh") if isinstance(data, dict) else None
                )
                base_total_kwh = (
                    data.get("base_total_kwh") if isinstance(data, dict) else None
                )
                adjustment_factor = (
                    data.get("adjustment_factor") if isinstance(data, dict) else None
                )
                cloud_cover = (
                    data.get("cloud_cover") if isinstance(data, dict) else None
                )

                # 🔥 Drill into "adjusted_hourly_kwh" (actual key from tool)
                # Fallback to "hourly" or top-level dict
                adjusted_source = (
                    data.get("adjusted_hourly_kwh") or data.get("hourly")
                    if isinstance(data, dict)
                    else data
                )

                if isinstance(adjusted_source, dict):
                    for k, v in adjusted_source.items():
                        hour = extract_hour(k)
                        if hour is not None:
                            rows.append(
                                {
                                    "hour": hour,
                                    "adjusted_kwh": v,
                                    "adjusted_total_kwh": adjusted_total_kwh,
                                    "base_total_kwh": base_total_kwh,
                                    "adjustment_factor": adjustment_factor,
                                    "cloud_cover": cloud_cover,
                                }
                            )

                elif isinstance(adjusted_source, list):
                    for row in adjusted_source:
                        hour = row.get("hour")
                        if isinstance(hour, str) and ":" in hour:
                            hour = int(hour.split(":")[0])
                        value = (
                            row.get("adjusted_kwh")
                            or row.get("adjusted_mw")
                            or row.get("value")
                        )
                        if hour is not None:
                            rows.append(
                                {
                                    "hour": int(hour),
                                    "adjusted_kwh": value,
                                    "adjusted_total_kwh": adjusted_total_kwh,
                                    "base_total_kwh": base_total_kwh,
                                    "adjustment_factor": adjustment_factor,
                                    "cloud_cover": cloud_cover,
                                }
                            )

                return rows

    except Exception as e:
        logger.error(f"[EXTRACT_ERROR][{tool_name}] {str(e)}")

    return []


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

        # tool_outputs[tool_name] = result_text
        tool_outputs[tool_name] = {
            "text": result_text,
            "raw": result_raw,
            "structured": extract_hourly_data(result_raw),
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
    llm_tool_outputs = {k: v["text"] for k, v in tool_outputs.items()}
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
""",
            }
        ],
    )

    for block in final_response.content:
        if hasattr(block, "text"):
            final_text += block.text

    final_text = add_system_context(final_text, query)
    memory.add("assistant", final_text)
    return {"text": final_text, "data": tool_outputs}
    # return final_text


# ---------------------------------------------------
# 🔥 CORE STREAMING AGENT (FIXED)
# ---------------------------------------------------
async def run_agent_stream(query, mcp_client):

    memory.add("user", query)
    tool_outputs = {}

    # ---------------------------------------------------
    # 🔥 STEP 1: RESOLVE CONTEXT (MEMORY-FIRST)
    # ---------------------------------------------------
    resolution = context_resolver.resolve(query)

    res_type = resolution["resolution"]
    date = resolution["date"]
    required_tools = resolution.get("required_tools", [])

    logger.info(
        f"[RESOLVER] type={res_type} | date={date} | "
        f"required={required_tools} | "
        f"missing={resolution.get('missing_tools', [])}"
    )

    # ---------------------------------------------------
    # 🔥 STEP 2: HANDLE RESOLUTION TYPES
    # ---------------------------------------------------

    # ✅ DIRECT HIT → NO TOOL CALLS
    if res_type == "direct":
        logger.info("[AGENT] DIRECT → using memory only")

        tool_outputs = resolution["cached_outputs"]

    # ✅ PARTIAL → FETCH ONLY MISSING
    elif res_type == "ambiguous":
        logger.info("[AGENT] AMBIGUOUS → partial fetch")

        # load cached
        tool_outputs.update(resolution["cached_outputs"])

        # fetch missing
        for tool_name in resolution["missing_tools"]:
            before = _call_tool_cached.cache_info()

            output = await _call_tool_cached(tool_name, date)

            _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())

            tool_outputs[tool_name] = output
            structured_mem.store(tool_name, date, output)

    # ❌ MISS → FULL PLANNER
    else:
        logger.info("[AGENT] MISS → planner execution")

        plan = parse_plan(create_plan(query))
        logger.info(f"[PLAN] {plan}")

        for step in plan:
            tool_name = step.get("tool")
            tool_input = _normalize_date(step.get("args", {}))
            date = tool_input.get("date", date)

            before = _call_tool_cached.cache_info()

            output = await _call_tool_cached(tool_name, date)

            _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())

            tool_outputs[tool_name] = output
            structured_mem.store(tool_name, date, output)

    # ---------------------------------------------------
    # 🔥 SAFETY CHECK
    # ---------------------------------------------------
    if not tool_outputs:
        logger.warning("[AGENT] No tool outputs found — forcing fallback")
        return

    # ---------------------------------------------------
    # 🔥 STEP 3: LLM RESPONSE
    # ---------------------------------------------------
    llm_tool_outputs = {k: v.get("text", "") for k, v in tool_outputs.items()}
    final_text = ""

    resolver_note = (
        "Note: Answer derived fully from memory (no new tool calls)."
        if res_type == "direct"
        else ""
    )

    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system="""
You are an energy AI analyst.
STRICT RULES:
- All data is for Spain only
- Be precise and structured
""",
        messages=[
            {
                "role": "user",
                "content": f"""
User query:
{query}

{resolver_note}

Tool outputs:
{llm_tool_outputs}

-----------------------------------

## Summary
## Key Insights
## Data Analysis
## Conclusion
""",
            }
        ],
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta":
                if hasattr(event.delta, "text") and event.delta.text:
                    token = event.delta.text
                    final_text += token
                    yield token

    # ---------------------------------------------------
    # 🔥 FINALIZE
    # ---------------------------------------------------
    final_text = add_system_context(final_text, query)
    memory.add("assistant", final_text)

    yield "[END]"

    # ---------------------------------------------------
    # 🔥 META
    # ---------------------------------------------------
    info = _call_tool_cached.cache_info()

    yield json.dumps(
        {
            "type": "meta",
            "resolver": resolution,
            "cache_stats": {
                "hits": info.hits,
                "misses": info.misses,
                "size": info.currsize,
                "maxsize": info.maxsize,
            },
        }
    )
