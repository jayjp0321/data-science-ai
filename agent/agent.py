# # agent.py (MEMORY-AWARE ARCHITECTURE)
# # Implements: Context Resolver → Memory Lookup → Direct/Ambiguous/Miss flow
# # Preserves: Data/Table/Chart/Analytics from old agent

# import json
# import anthropic
# import logging
# import pandas as pd

# from async_lru import alru_cache
# from datetime import datetime, timedelta

# from agent.memory import ConversationMemory, StructuredMemory
# from agent.planner import create_plan, parse_plan
# from agent.context_resolver import ContextResolver
# from configs.settings import ANTHROPIC_API_KEY, MODEL_NAME, MAX_TOKENS, MEMORY_WINDOW

# from fastmcp.client import Client
# from fastmcp.client.transports import StdioTransport


# logger = logging.getLogger(__name__)
# logger.propagate = True

# MCP_CLIENT = None

# # ---------------------------------------------------
# # 🔥 GLOBAL STATE
# # ---------------------------------------------------
# client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
# memory = ConversationMemory(MEMORY_WINDOW)
# structured_mem = StructuredMemory()
# context_resolver = ContextResolver(structured_mem)

# # ---------------------------------------------------
# # 🔥 SYSTEM PROMPT (shared by stream + non-stream)
# # CRITICAL: explicit prohibition on hallucinating tool output
# # ---------------------------------------------------
# SYSTEM_PROMPT = """
# You are an energy AI analyst for Spain.

# STRICT RULES — MUST FOLLOW:
# 1. All analysis is for Spain only. Never mention other countries.
# 2. Answer ONLY from the tool data provided in this conversation context.
# 3. NEVER generate, simulate, or reproduce tool names, tool calls, raw JSON,
#    or structured data blocks in your response. Do not output anything like
#    "get_energy_prices_tool {...}" or "Structured Data: [...]".
# 4. Do not invent, speculate, or extrapolate data that was not returned by a tool.
# 5. If tool data shows an error, report it clearly and concisely.
# 6. Be precise, structured, and analytical in your final answer.
# 7. Format your response using markdown headings and bullet points only.
# """


# # ---------------------------------------------------
# # 🔥 MCP CLIENT
# # ---------------------------------------------------
# async def start_mcp_client():
#     global MCP_CLIENT

#     transport = StdioTransport(command="python", args=["-m", "mcp_v2.server"])
#     MCP_CLIENT = Client(transport)

#     await MCP_CLIENT.__aenter__()

#     logger.info("[MCP] Server started ✅")
#     return MCP_CLIENT


# # ---------------------------------------------------
# # 🔥 HELPERS
# # ---------------------------------------------------
# def detect_location(query: str) -> str | None:
#     q = query.lower()
#     if "spain" in q:
#         return "spain"
#     for loc in ["india", "usa", "germany", "france", "uk"]:
#         if loc in q:
#             return loc
#     return None


# def add_system_context(final_text: str, query: str) -> str:
#     location = detect_location(query)
#     note = "\n\n---\n📍 **System Context**:\nThis system is calibrated for **Spain**.\n"
#     if location and location != "spain":
#         note += f"⚠️ Requested: {location.title()} → Using Spain data instead.\n"
#     return final_text + note


# def make_json_safe(obj):
#     """Recursively makes an object JSON serializable (handles pandas Timestamps, numpy types)."""
#     if isinstance(obj, dict):
#         return {str(k): make_json_safe(v) for k, v in obj.items()}
#     elif isinstance(obj, list):
#         return [make_json_safe(v) for v in obj]
#     elif isinstance(obj, pd.Timestamp):
#         return str(obj)
#     elif hasattr(obj, "item"):  # numpy scalar
#         return obj.item()
#     return obj


# def sanitize_args(tool_name: str, args: dict) -> dict:
#     tool_schemas = {
#         "get_weather_forecast_tool": {"date"},
#         "get_energy_forecast_tool": {"date"},
#         "get_adjusted_forecast_tool": {"date"},
#     }
#     allowed = tool_schemas.get(tool_name, set())
#     return {k: v for k, v in args.items() if k in allowed}


# def _normalize_date(args: dict) -> dict:
#     """Ensures 'date' is present and normalized to YYYY-MM-DD."""
#     if not args:
#         args = {}

#     date = args.get("date")
#     today = datetime.today()

#     if not date:
#         return {"date": (today + timedelta(days=1)).strftime("%Y-%m-%d")}

#     date = str(date).lower()

#     if date == "today":
#         normalized = today.strftime("%Y-%m-%d")
#     elif date == "tomorrow":
#         normalized = (today + timedelta(days=1)).strftime("%Y-%m-%d")
#     elif date == "yesterday":
#         normalized = (today - timedelta(days=1)).strftime("%Y-%m-%d")
#     else:
#         normalized = date  # assume YYYY-MM-DD

#     return {"date": normalized}


# def _build_llm_messages(query: str, tool_outputs: dict, resolver_note: str):
#     """
#     Constructs messages payload for LLM.

#     Tool outputs are injected as a SINGLE user-turn context block —
#     NOT as assistant messages — so the LLM cannot continue/mimic them
#     and hallucinate fake tool calls or raw JSON in its reply.
#     """

#     # ----------------------------------------
#     # 🔥 BUILD TOOL CONTEXT AS PLAIN TEXT
#     # Presented as part of the user message so the LLM
#     # treats it as input data, not something it generated.
#     # ----------------------------------------
#     tool_context_parts = []
#     for tool_name, output in tool_outputs.items():
#         text = output.get("text", "")
#         # Strip the raw JSON blob — give LLM only the parsed summary text.
#         # The structured rows are used by the frontend, not the LLM.
#         tool_context_parts.append(f"[Data from {tool_name}]\n{text}")

#     tool_context = (
#         "\n\n".join(tool_context_parts)
#         if tool_context_parts
#         else "No tool data available."
#     )

#     resolver_section = f"\n{resolver_note}\n" if resolver_note else ""

#     messages = [
#         {
#             "role": "user",
#             "content": (
#                 f"{resolver_section}"
#                 f"Tool Data (use this ONLY — do not reproduce raw JSON or tool names in your response):\n\n"
#                 f"{tool_context}\n\n"
#                 f"---\n"
#                 f"User Question: {query}\n\n"
#                 f"Answer the question above using only the tool data provided. "
#                 f"Use markdown. Do not output any tool names, JSON, or raw data blocks."
#             ),
#         }
#     ]

#     return messages


# # ---------------------------------------------------
# # 🔥 STRUCTURED DATA EXTRACTION (TOOL-AWARE)
# # Preserved from original agent — feeds Data/Table/Chart/Analytics
# # ---------------------------------------------------
# def extract_structured(tool_name: str, result_raw) -> list:
#     try:
#         for item in result_raw:
#             if not hasattr(item, "text"):
#                 continue

#             data = json.loads(item.text)
#             rows = []

#             def extract_hour(k):
#                 try:
#                     if " " in str(k):
#                         return int(str(k).split(" ")[1].split(":")[0])
#                     if ":" in str(k):
#                         return int(str(k).split(":")[0])
#                     return int(k)
#                 except Exception:
#                     return None

#             # ---- ENERGY TOOL ----
#             if tool_name == "get_energy_forecast_tool":
#                 energy_source = (
#                     data.get("hourly")
#                     if isinstance(data, dict) and "hourly" in data
#                     else data
#                 )
#                 if isinstance(energy_source, dict):
#                     for k, v in energy_source.items():
#                         hour = extract_hour(k)
#                         if hour is not None:
#                             rows.append({"hour": hour, "production_mw": v})
#                 elif isinstance(energy_source, list):
#                     for row in energy_source:
#                         hour = row.get("hour")
#                         if isinstance(hour, str) and ":" in hour:
#                             hour = int(hour.split(":")[0])
#                         value = row.get("production_mw") or row.get("value")
#                         if hour is not None:
#                             rows.append({"hour": int(hour), "production_mw": value})
#                 return rows

#             # ---- WEATHER TOOL ----
#             elif tool_name == "get_weather_forecast_tool":
#                 hourly_source = (
#                     data.get("hourly")
#                     if isinstance(data, dict) and "hourly" in data
#                     else data
#                 )
#                 avg_temperature = (
#                     data.get("avg_temperature") if isinstance(data, dict) else None
#                 )
#                 avg_cloud_cover = (
#                     data.get("avg_cloud_cover") if isinstance(data, dict) else None
#                 )

#                 if isinstance(hourly_source, dict):
#                     for k, v in hourly_source.items():
#                         hour = extract_hour(k)
#                         if hour is not None:
#                             rows.append(
#                                 {
#                                     "hour": hour,
#                                     "temperature": v,
#                                     "avg_temperature": avg_temperature,
#                                     "avg_cloud_cover": avg_cloud_cover,
#                                 }
#                             )
#                 elif isinstance(hourly_source, list):
#                     for row in hourly_source:
#                         raw_hour = (
#                             row.get("hour")
#                             or row.get("time")
#                             or row.get("timestamp")
#                             or row.get("datetime")
#                         )
#                         if raw_hour is None:
#                             continue
#                         hour = extract_hour(str(raw_hour))
#                         if hour is None:
#                             continue
#                         rows.append(
#                             {
#                                 "hour": hour,
#                                 "temperature": (
#                                     row.get("temperature")
#                                     or row.get("value")
#                                     or row.get("cloud_cover")
#                                     or row.get("irradiance")
#                                 ),
#                                 "avg_temperature": avg_temperature,
#                                 "avg_cloud_cover": avg_cloud_cover,
#                             }
#                         )
#                 return rows

#             # ---- ADJUSTED TOOL ----
#             elif tool_name == "get_adjusted_forecast_tool":
#                 adjusted_total_kwh = (
#                     data.get("adjusted_total_kwh") if isinstance(data, dict) else None
#                 )
#                 base_total_kwh = (
#                     data.get("base_total_kwh") if isinstance(data, dict) else None
#                 )
#                 adjustment_factor = (
#                     data.get("adjustment_factor") if isinstance(data, dict) else None
#                 )
#                 cloud_cover = (
#                     data.get("cloud_cover") if isinstance(data, dict) else None
#                 )

#                 adjusted_source = (
#                     data.get("adjusted_hourly_kwh") or data.get("hourly")
#                     if isinstance(data, dict)
#                     else data
#                 )

#                 if isinstance(adjusted_source, dict):
#                     for k, v in adjusted_source.items():
#                         hour = extract_hour(k)
#                         if hour is not None:
#                             rows.append(
#                                 {
#                                     "hour": hour,
#                                     "adjusted_kwh": v,
#                                     "adjusted_total_kwh": adjusted_total_kwh,
#                                     "base_total_kwh": base_total_kwh,
#                                     "adjustment_factor": adjustment_factor,
#                                     "cloud_cover": cloud_cover,
#                                 }
#                             )
#                 elif isinstance(adjusted_source, list):
#                     for row in adjusted_source:
#                         hour = row.get("hour")
#                         if isinstance(hour, str) and ":" in hour:
#                             hour = int(hour.split(":")[0])
#                         value = (
#                             row.get("adjusted_kwh")
#                             or row.get("adjusted_mw")
#                             or row.get("value")
#                         )
#                         if hour is not None:
#                             rows.append(
#                                 {
#                                     "hour": int(hour),
#                                     "adjusted_kwh": value,
#                                     "adjusted_total_kwh": adjusted_total_kwh,
#                                     "base_total_kwh": base_total_kwh,
#                                     "adjustment_factor": adjustment_factor,
#                                     "cloud_cover": cloud_cover,
#                                 }
#                             )
#                 return rows

#     except Exception as e:
#         logger.error(f"[EXTRACT_ERROR][{tool_name}] {str(e)}")

#     return []


# def extract_hourly_data(result_raw) -> list:
#     """Legacy extractor for backwards compatibility."""
#     try:
#         for item in result_raw:
#             if hasattr(item, "text"):
#                 data_dict = json.loads(item.text)
#                 rows = []
#                 for timestamp, value in data_dict.items():
#                     hour = int(timestamp.split(" ")[1].split(":")[0])
#                     rows.append({"hour": hour, "production_mw": value})
#                 return rows
#     except Exception as e:
#         logger.error(f"[EXTRACT_ERROR] {str(e)}")
#     return []


# # ---------------------------------------------------
# # 🔥 ANALYTICS HELPERS (from old agent)
# # ---------------------------------------------------
# def build_analytics_payload(tool_outputs: dict) -> dict:
#     """
#     Builds structured analytics data for Data/Table/Chart consumption.
#     Merges structured rows from all tools into a unified payload.
#     """
#     analytics = {
#         "energy": [],
#         "weather": [],
#         "adjusted": [],
#         "summary": {},
#     }

#     for tool_name, output in tool_outputs.items():
#         structured = output.get("structured", [])
#         raw = output.get("raw")

#         # Re-extract if structured is empty but raw exists
#         if not structured and raw:
#             structured = extract_structured(tool_name, raw)

#         if tool_name == "get_energy_forecast_tool":
#             analytics["energy"] = structured
#         elif tool_name == "get_weather_forecast_tool":
#             analytics["weather"] = structured
#         elif tool_name == "get_adjusted_forecast_tool":
#             analytics["adjusted"] = structured

#             # Pull summary fields from first row
#             if structured:
#                 first = structured[0]
#                 analytics["summary"] = {
#                     "adjusted_total_kwh": first.get("adjusted_total_kwh"),
#                     "base_total_kwh": first.get("base_total_kwh"),
#                     "adjustment_factor": first.get("adjustment_factor"),
#                     "cloud_cover": first.get("cloud_cover"),
#                 }

#     return analytics


# # ---------------------------------------------------
# # 🔥 TOOL CALL (CACHED)
# # ---------------------------------------------------
# @alru_cache(maxsize=32)
# async def _call_tool_cached(tool_name: str, date: str) -> dict:
#     logger.info(f"[TOOL CALL] {tool_name} | date={date}")

#     result = await MCP_CLIENT.call_tool(tool_name, {"date": date})

#     # Parse raw content
#     if hasattr(result, "content"):
#         raw = result.content
#         text = "".join(item.text for item in raw if hasattr(item, "text"))
#     elif hasattr(result, "output"):
#         raw = result.output
#         text = str(raw)
#     else:
#         raw = []
#         text = str(result)

#     structured = extract_structured(tool_name, raw) if raw else []

#     return {"text": text, "raw": raw, "structured": structured}


# def _log_cache_event(tool: str, date: str, before, after):
#     if after.hits > before.hits:
#         logger.info(f"[CACHE HIT] {tool} | date={date}")
#     else:
#         logger.info(f"[CACHE MISS] {tool} | date={date}")


# # ---------------------------------------------------
# # 🔥 EVALUATOR (for non-streaming path)
# # ---------------------------------------------------
# def evaluate_step(query: str, step: dict, result_text: str, tool_outputs: dict) -> dict:
#     if "adjusted_total_kwh" in result_text:
#         return {"action": "stop"}

#     response = client.messages.create(
#         model=MODEL_NAME,
#         max_tokens=200,
#         messages=[
#             {
#                 "role": "user",
#                 "content": f"""
# User query:
# {query}

# Executed step:
# {step}

# Tool result:
# {result_text}

# Return STRICT JSON:
# {{"action": "continue" | "stop" | "replan"}}
# """,
#             }
#         ],
#     )

#     text = "".join(block.text for block in response.content if hasattr(block, "text"))
#     try:
#         return json.loads(text)
#     except Exception:
#         return {"action": "continue"}


# # ---------------------------------------------------
# # 🔥 LLM PROMPT BUILDER
# # Shared by both stream and non-stream paths
# # ---------------------------------------------------
# def _json_safe_meta(obj):
#     """Recursively make objects JSON serializable (handles datetime, etc.)."""
#     if isinstance(obj, dict):
#         return {k: _json_safe_meta(v) for k, v in obj.items()}
#     elif isinstance(obj, list):
#         return [_json_safe_meta(v) for v in obj]
#     elif isinstance(obj, datetime):
#         return obj.isoformat()
#     return obj


# # ---------------------------------------------------
# # 🔥 NON-STREAMING AGENT (with full analytics payload)
# # ---------------------------------------------------
# async def run_agent_async(query: str, mcp_client=None) -> dict:
#     """
#     Non-streaming agent. Returns:
#     {
#         "text": str,               # LLM response
#         "data": dict,              # raw tool outputs keyed by tool name
#         "analytics": dict,         # structured energy/weather/adjusted rows + summary
#         "resolver": dict,          # resolution metadata
#         "cache_stats": dict,
#     }
#     """
#     memory.add("user", query)
#     tool_outputs = {}

#     # ---------------------------------------------------
#     # STEP 1: RESOLVE CONTEXT (MEMORY-FIRST)
#     # ---------------------------------------------------
#     resolution = context_resolver.resolve(query)
#     res_type = resolution["resolution"]
#     date = resolution["date"]
#     required_tools = resolution.get("required_tools", [])

#     logger.info(
#         f"[RESOLVER] type={res_type} | date={date} | "
#         f"required={required_tools} | missing={resolution.get('missing_tools', [])}"
#     )

#     # ---------------------------------------------------
#     # STEP 2: ROUTE BY RESOLUTION TYPE
#     # ---------------------------------------------------

#     # ✅ DIRECT HIT — memory only
#     if res_type == "direct":
#         logger.info("[AGENT] DIRECT → using memory only")
#         tool_outputs = resolution["cached_outputs"]

#     # ✅ AMBIGUOUS — partial fetch (only missing tools)
#     elif res_type == "ambiguous":
#         logger.info("[AGENT] AMBIGUOUS → partial fetch")
#         tool_outputs.update(resolution["cached_outputs"])

#         for tool_name in resolution["missing_tools"]:
#             before = _call_tool_cached.cache_info()
#             output = await _call_tool_cached(tool_name, date)
#             _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())
#             tool_outputs[tool_name] = output
#             structured_mem.store(tool_name, date, output)

#     # ❌ MISS — full planner execution with evaluator loop
#     else:
#         logger.info("[AGENT] MISS → planner execution")

#         plan_text = create_plan(query)
#         plan = parse_plan(plan_text)
#         logger.info(f"[INITIAL PLAN] {plan}")

#         current_plan = plan
#         step_index = 0
#         replan_count = 0
#         MAX_REPLANS = 2

#         while step_index < len(current_plan):
#             step = current_plan[step_index]
#             tool_name = step.get("tool")
#             tool_input = _normalize_date(step.get("args", {}))
#             date = tool_input.get("date", date)

#             logger.info(f"[EXEC] {tool_name} | input={tool_input}")

#             before = _call_tool_cached.cache_info()
#             output = await _call_tool_cached(tool_name, date)
#             _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())

#             tool_outputs[tool_name] = output
#             structured_mem.store(tool_name, date, output)

#             result_text = output.get("text", "")
#             decision = evaluate_step(query, step, result_text, tool_outputs)
#             logger.info(f"[DECISION] {decision}")

#             if decision.get("action") == "stop":
#                 logger.info("[STOPPED EARLY]")
#                 break
#             elif decision.get("action") == "replan":
#                 if replan_count >= MAX_REPLANS:
#                     logger.warning("[REPLAN LIMIT REACHED]")
#                     break
#                 replan_count += 1
#                 logger.info("[REPLANNING...]")
#                 current_plan = parse_plan(create_plan(query, tool_outputs))
#                 logger.info(f"[NEW PLAN] {current_plan}")
#                 step_index = 0
#                 continue
#             else:
#                 step_index += 1

#     # ---------------------------------------------------
#     # SAFETY CHECK
#     # ---------------------------------------------------
#     if not tool_outputs:
#         logger.warning("[AGENT] No tool outputs — aborting")
#         return {
#             "text": "No data available.",
#             "data": {},
#             "analytics": {},
#             "resolver": resolution,
#         }

#     # ---------------------------------------------------
#     # STEP 3: ANALYTICS PAYLOAD (Data/Table/Chart)
#     # ---------------------------------------------------
#     analytics = build_analytics_payload(tool_outputs)

#     # ---------------------------------------------------
#     # STEP 4: LLM FINAL RESPONSE
#     # ---------------------------------------------------
#     resolver_note = (
#         "Note: Answer derived fully from memory (no new tool calls)."
#         if res_type == "direct"
#         else ""
#     )

#     final_response = client.messages.create(
#         model=MODEL_NAME,
#         max_tokens=MAX_TOKENS,
#         temperature=0,
#         system=SYSTEM_PROMPT,
#         messages=_build_llm_messages(query, tool_outputs, resolver_note),
#     )

#     final_text = "".join(
#         block.text for block in final_response.content if hasattr(block, "text")
#     )
#     final_text = add_system_context(final_text, query)
#     memory.add("assistant", final_text)

#     info = _call_tool_cached.cache_info()

#     return _json_safe_meta(
#         {
#             "text": final_text,
#             "data": {
#                 k: {sk: sv for sk, sv in v.items() if sk != "raw"}
#                 for k, v in tool_outputs.items()
#             },
#             "analytics": analytics,
#             "resolver": resolution,
#             "cache_stats": {
#                 "hits": info.hits,
#                 "misses": info.misses,
#                 "size": info.currsize,
#                 "maxsize": info.maxsize,
#             },
#         }
#     )


# # ---------------------------------------------------
# # 🔥 STREAMING AGENT (MEMORY-AWARE)
# # ---------------------------------------------------
# async def run_agent_stream(query: str, mcp_client=None):
#     """
#     Streaming agent. Yields:
#       - str tokens (LLM response text)
#       - "[END]" sentinel
#       - JSON string with type="meta" containing resolver, analytics, cache_stats
#     """
#     memory.add("user", query)
#     tool_outputs = {}

#     # ---------------------------------------------------
#     # STEP 1: RESOLVE CONTEXT (MEMORY-FIRST)
#     # ---------------------------------------------------
#     resolution = context_resolver.resolve(query)
#     res_type = resolution["resolution"]
#     date = resolution["date"]
#     required_tools = resolution.get("required_tools", [])

#     logger.info(
#         f"[RESOLVER] type={res_type} | date={date} | "
#         f"required={required_tools} | missing={resolution.get('missing_tools', [])}"
#     )

#     # ---------------------------------------------------
#     # STEP 2: ROUTE BY RESOLUTION TYPE
#     # ---------------------------------------------------

#     # ✅ DIRECT HIT — memory only, no tool calls
#     if res_type == "direct":
#         logger.info("[AGENT] DIRECT → using memory only")
#         tool_outputs = resolution["cached_outputs"]

#     # ✅ AMBIGUOUS — only fetch missing tools
#     elif res_type == "ambiguous":
#         logger.info("[AGENT] AMBIGUOUS → partial fetch")
#         tool_outputs.update(resolution["cached_outputs"])

#         for tool_name in resolution["missing_tools"]:
#             before = _call_tool_cached.cache_info()
#             output = await _call_tool_cached(tool_name, date)
#             _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())
#             tool_outputs[tool_name] = output
#             structured_mem.store(tool_name, date, output)

#     # ❌ MISS — full planner execution
#     else:
#         logger.info("[AGENT] MISS → planner execution")

#         plan = parse_plan(create_plan(query))
#         logger.info(f"[PLAN] {plan}")

#         for step in plan:
#             tool_name = step.get("tool")
#             tool_input = _normalize_date(step.get("args", {}))
#             date = tool_input.get("date", date)

#             before = _call_tool_cached.cache_info()
#             output = await _call_tool_cached(tool_name, date)
#             _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())

#             tool_outputs[tool_name] = output
#             structured_mem.store(tool_name, date, output)

#     # ---------------------------------------------------
#     # SAFETY CHECK
#     # ---------------------------------------------------
#     if not tool_outputs:
#         logger.warning("[AGENT] No tool outputs — aborting stream")
#         yield "[END]"
#         return

#     # ---------------------------------------------------
#     # STEP 3: ANALYTICS PAYLOAD (Data/Table/Chart)
#     # ---------------------------------------------------
#     analytics = build_analytics_payload(tool_outputs)

#     # ---------------------------------------------------
#     # STEP 4: STREAM LLM RESPONSE
#     # ---------------------------------------------------
#     resolver_note = (
#         "Note: Answer derived fully from memory (no new tool calls)."
#         if res_type == "direct"
#         else ""
#     )

#     final_text = ""

#     with client.messages.stream(
#         model=MODEL_NAME,
#         max_tokens=MAX_TOKENS,
#         temperature=0,
#         system=SYSTEM_PROMPT,
#         messages=_build_llm_messages(query, tool_outputs, resolver_note),
#     ) as stream:
#         for event in stream:
#             if event.type == "content_block_delta":
#                 if hasattr(event.delta, "text") and event.delta.text:
#                     token = event.delta.text
#                     final_text += token
#                     yield token

#     # ---------------------------------------------------
#     # FINALIZE
#     # ---------------------------------------------------
#     final_text = add_system_context(final_text, query)
#     memory.add("assistant", final_text)

#     yield "[END]"

#     # ---------------------------------------------------
#     # META — resolver + analytics + cache (consumed by frontend)
#     # ---------------------------------------------------
#     info = _call_tool_cached.cache_info()

#     yield json.dumps(
#         _json_safe_meta(
#             {
#                 "type": "meta",
#                 "resolver": resolution,
#                 "analytics": analytics,
#                 "cache_stats": {
#                     "hits": info.hits,
#                     "misses": info.misses,
#                     "size": info.currsize,
#                     "maxsize": info.maxsize,
#                 },
#             }
#         )
#     )


# agent.py (MEMORY-AWARE ARCHITECTURE)
# Implements: Context Resolver → Memory Lookup → Direct/Ambiguous/Miss flow
# Preserves: Data/Table/Chart/Analytics from old agent

import json
import anthropic
import logging
import pandas as pd
import re

from async_lru import alru_cache
from datetime import datetime, timedelta

from agent.memory import ConversationMemory, StructuredMemory
from agent.planner import create_plan, parse_plan
from agent.context_resolver import ContextResolver
from configs.settings import ANTHROPIC_API_KEY, MODEL_NAME, MAX_TOKENS, MEMORY_WINDOW
from agent.context_resolver import extract_date
from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport


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
# 🔥 SYSTEM PROMPT (shared by stream + non-stream)
# ---------------------------------------------------
SYSTEM_PROMPT = """
You are an energy AI analyst for Spain.

STRICT RULES — MUST FOLLOW:
1. All analysis is for Spain only. Never mention other countries.
2. Answer ONLY from the tool data provided in this conversation context.
3. NEVER generate, simulate, or reproduce tool names, tool calls, raw JSON,
   or structured data blocks in your response. Do not output anything like
   "get_energy_prices_tool {...}" or "Structured Data: [...]".
4. Do not invent, speculate, or extrapolate data that was not returned by a tool.
5. If tool data shows an error, report it clearly and concisely.
6. Be precise, structured, and analytical in your final answer.
7. Format your response using markdown headings and bullet points only.
8. Answer ONLY what the user asked. If they ask a single specific question
   (e.g. peak hour, peak temperature, min price), give a SHORT focused answer.
   Do NOT dump the full forecast. Do NOT add unrequested sections.
"""

# ---------------------------------------------------
# 🔥 CONVERSATIONAL QUERY DETECTION
# Returns True  → short/specific question, suppress analytics
# Returns False → full data/forecast request, show analytics
# ---------------------------------------------------

FULL_DATA_KEYWORDS = [
    "forecast",
    "full",
    "all",
    "table",
    "chart",
    "graph",
    "show me",
    "give me",
    "data",
    "analysis",
    "breakdown",
    "hourly",
    "detail",
    "report",
    "summary",
]

CONVERSATIONAL_PATTERNS = [
    r"^peak\b",
    r"^what is\b",
    r"^what('s| is)\b",
    r"^when\b",
    r"^how (hot|cold|warm|much|many|high|low)\b",
    r"^(min|max|average|avg|best|worst|cheapest|most expensive)\b",
    r"^is (it|the|there)\b",
    r"^tell me (the|about the)?\s*(peak|min|max|best|cheapest)",
]


def is_conversational_query(query: str) -> bool:
    """
    True  → specific/follow-up question → suppress table+chart+analytics
    False → full data request → show analytics
    """
    q = query.strip().lower()

    # Explicit full-data request always shows analytics
    for kw in FULL_DATA_KEYWORDS:
        if kw in q:
            logger.info(f"[CONVERSATIONAL] False — matched full-data keyword: '{kw}'")
            return False

    # Short query (≤ 6 words) → conversational
    if len(q.split()) <= 6:
        logger.info("[CONVERSATIONAL] True — short query")
        return True

    # Pattern match
    for pattern in CONVERSATIONAL_PATTERNS:
        if re.match(pattern, q):
            logger.info(f"[CONVERSATIONAL] True — matched pattern: {pattern}")
            return True

    logger.info("[CONVERSATIONAL] False — no match, defaulting to show analytics")
    return False


# ---------------------------------------------------
# 🔥 MCP CLIENT
# ---------------------------------------------------
async def start_mcp_client():
    global MCP_CLIENT

    transport = StdioTransport(command="python", args=["-m", "mcp_v2.server"])
    MCP_CLIENT = Client(transport)

    await MCP_CLIENT.__aenter__()

    logger.info("[MCP] Server started ✅")
    return MCP_CLIENT


# ---------------------------------------------------
# 🔥 HELPERS
# ---------------------------------------------------
def detect_location(query: str) -> str | None:
    q = query.lower()
    if "spain" in q:
        return "spain"
    for loc in ["india", "usa", "germany", "france", "uk"]:
        if loc in q:
            return loc
    return None


def add_system_context(final_text: str, query: str) -> str:
    location = detect_location(query)
    note = "\n\n---\n📍 **System Context**:\nThis system is calibrated for **Spain**.\n"
    if location and location != "spain":
        note += f"⚠️ Requested: {location.title()} → Using Spain data instead.\n"
    return final_text + note


def make_json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif hasattr(obj, "item"):
        return obj.item()
    return obj


def sanitize_args(tool_name: str, args: dict) -> dict:
    tool_schemas = {
        "get_weather_forecast_tool": {"date"},
        "get_energy_forecast_tool": {"date"},
        "get_adjusted_forecast_tool": {"date"},
    }
    allowed = tool_schemas.get(tool_name, set())
    return {k: v for k, v in args.items() if k in allowed}


def _normalize_date(args: dict) -> dict:
    if not args:
        args = {}
    date = args.get("date")
    today = datetime.today()
    if not date:
        return {"date": (today + timedelta(days=1)).strftime("%Y-%m-%d")}
    date = str(date).lower()
    if date == "today":
        normalized = today.strftime("%Y-%m-%d")
    elif date == "tomorrow":
        normalized = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif date == "yesterday":
        normalized = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        normalized = date
    return {"date": normalized}


def _build_llm_messages(query: str, tool_outputs: dict, resolver_note: str):
    """
    Tool outputs injected as a user-turn context block — NOT as assistant
    messages — so the LLM cannot mimic/continue them.
    """
    tool_context_parts = []
    for tool_name, output in tool_outputs.items():
        text = output.get("text", "")
        tool_context_parts.append(f"[Data from {tool_name}]\n{text}")

    tool_context = (
        "\n\n".join(tool_context_parts)
        if tool_context_parts
        else "No tool data available."
    )
    resolver_section = f"\n{resolver_note}\n" if resolver_note else ""

    return [
        {
            "role": "user",
            "content": (
                f"{resolver_section}"
                f"Tool Data (reference only — do NOT reproduce as JSON or tool names):\n\n"
                f"{tool_context}\n\n"
                f"---\n"
                f"User Question: {query}\n\n"
                f"Answer ONLY the specific question asked. "
                f"If it is a simple/specific question (e.g. peak hour, peak temp, min price), "
                f"give a SHORT direct answer only — do NOT include the full forecast or "
                f"unrequested sections. Use markdown. No raw data, no tool names, no JSON."
            ),
        }
    ]


# ---------------------------------------------------
# 🔥 STRUCTURED DATA EXTRACTION (TOOL-AWARE)
# ---------------------------------------------------
def extract_structured(tool_name: str, result_raw) -> list:
    try:
        for item in result_raw:
            if not hasattr(item, "text"):
                continue

            data = json.loads(item.text)
            rows = []

            def extract_hour(k):
                try:
                    if " " in str(k):
                        return int(str(k).split(" ")[1].split(":")[0])
                    if ":" in str(k):
                        return int(str(k).split(":")[0])
                    return int(k)
                except Exception:
                    return None

            if tool_name == "get_energy_forecast_tool":
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
                return rows

            elif tool_name == "get_weather_forecast_tool":
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

            elif tool_name == "get_adjusted_forecast_tool":
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


def extract_hourly_data(result_raw) -> list:
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


def build_clarification_question(candidates: list[dict]) -> str:
    TOOL_LABELS = {
        "get_energy_forecast_tool": "solar production",
        "get_adjusted_forecast_tool": "adjusted solar production",
        "get_weather_forecast_tool": "weather",
    }

    options = []
    seen = set()

    for c in candidates:
        tool = c["tool"]
        label = TOOL_LABELS.get(tool, tool)

        if label not in seen:
            seen.add(label)
            options.append(label)

    if not options:
        return "Can you clarify what you mean?"

    formatted = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])

    return f"""Which result are you referring to?

{formatted}"""


# ---------------------------------------------------
# 🔥 ANALYTICS PAYLOAD BUILDER
# ---------------------------------------------------
def build_analytics_payload(tool_outputs: dict) -> dict:
    analytics = {"energy": [], "weather": [], "adjusted": [], "summary": {}}

    for tool_name, output in tool_outputs.items():
        structured = output.get("structured", [])
        raw = output.get("raw")
        if not structured and raw:
            structured = extract_structured(tool_name, raw)

        if tool_name == "get_energy_forecast_tool":
            analytics["energy"] = structured
        elif tool_name == "get_weather_forecast_tool":
            analytics["weather"] = structured
        elif tool_name == "get_adjusted_forecast_tool":
            analytics["adjusted"] = structured
            if structured:
                first = structured[0]
                analytics["summary"] = {
                    "adjusted_total_kwh": first.get("adjusted_total_kwh"),
                    "base_total_kwh": first.get("base_total_kwh"),
                    "adjustment_factor": first.get("adjustment_factor"),
                    "cloud_cover": first.get("cloud_cover"),
                }

    return analytics


# ---------------------------------------------------
# 🔥 TOOL CALL (CACHED)
# ---------------------------------------------------
@alru_cache(maxsize=32)
async def _call_tool_cached(tool_name: str, date: str) -> dict:
    logger.info(f"[TOOL CALL] {tool_name} | date={date}")

    result = await MCP_CLIENT.call_tool(tool_name, {"date": date})

    if hasattr(result, "content"):
        raw = result.content
        text = "".join(item.text for item in raw if hasattr(item, "text"))
    elif hasattr(result, "output"):
        raw = result.output
        text = str(raw)
    else:
        raw = []
        text = str(result)

    structured = extract_structured(tool_name, raw) if raw else []
    return {"text": text, "raw": raw, "structured": structured}


def _log_cache_event(tool: str, date: str, before, after):
    if after.hits > before.hits:
        logger.info(f"[CACHE HIT] {tool} | date={date}")
    else:
        logger.info(f"[CACHE MISS] {tool} | date={date}")


# ---------------------------------------------------
# 🔥 EVALUATOR
# ---------------------------------------------------
def evaluate_step(query: str, step: dict, result_text: str, tool_outputs: dict) -> dict:
    if "adjusted_total_kwh" in result_text:
        return {"action": "stop"}

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": f"""User query:\n{query}\n\nExecuted step:\n{step}\n\nTool result:\n{result_text}\n\nReturn STRICT JSON:\n{{"action": "continue" | "stop" | "replan"}}""",
            }
        ],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    try:
        return json.loads(text)
    except Exception:
        return {"action": "continue"}


# ---------------------------------------------------
# 🔥 JSON SAFE META
# ---------------------------------------------------
def _json_safe_meta(obj):
    if isinstance(obj, dict):
        return {k: _json_safe_meta(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_json_safe_meta(v) for v in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# ---------------------------------------------------
# 🔥 NON-STREAMING AGENT
# ---------------------------------------------------
async def run_agent_async(query: str, mcp_client=None) -> dict:
    memory.add("user", query)
    tool_outputs = {}

    resolution = context_resolver.resolve(query)
    # ---------------------------------------------------
    # 🔥 HANDLE AMBIGUITY
    # ---------------------------------------------------
    if resolution["resolution"] == "ambiguous":
        question = build_clarification_question(resolution["candidates"])

        logger.info("[AGENT] AMBIGUOUS → asking clarification")

        memory.add("assistant", question)

        return {
            "text": question,
            "structured": [],
            "meta": {
                "resolution": "ambiguous",
                "candidates": resolution["candidates"],
            },
        }
    res_type = resolution["resolution"]
    date = resolution["date"]
    required_tools = resolution.get("required_tools", [])

    logger.info(
        f"[RESOLVER] type={res_type} | date={date} | "
        f"required={required_tools} | missing={resolution.get('missing_tools', [])}"
    )

    if res_type == "direct":
        logger.info("[AGENT] DIRECT → using memory only")
        tool_outputs = resolution["cached_outputs"]

    elif res_type == "ambiguous":
        logger.info("[AGENT] AMBIGUOUS → partial fetch")
        tool_outputs.update(resolution["cached_outputs"])
        for tool_name in resolution["missing_tools"]:
            before = _call_tool_cached.cache_info()
            output = await _call_tool_cached(tool_name, date)
            _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())
            tool_outputs[tool_name] = output
            structured_mem.store(tool_name, date, output)

    else:
        logger.info("[AGENT] MISS → planner execution")
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
            tool_input = _normalize_date(step.get("args", {}))
            date = tool_input.get("date", date)

            before = _call_tool_cached.cache_info()
            output = await _call_tool_cached(tool_name, date)
            _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())

            tool_outputs[tool_name] = output
            structured_mem.store(tool_name, date, output)

            result_text = output.get("text", "")
            decision = evaluate_step(query, step, result_text, tool_outputs)
            logger.info(f"[DECISION] {decision}")

            if decision.get("action") == "stop":
                break
            elif decision.get("action") == "replan":
                if replan_count >= MAX_REPLANS:
                    break
                replan_count += 1
                current_plan = parse_plan(create_plan(query, tool_outputs))
                step_index = 0
                continue
            else:
                step_index += 1

    if not tool_outputs:
        return {
            "text": "No data available.",
            "data": {},
            "analytics": {},
            "resolver": resolution,
        }

    # 🔑 Suppress analytics for conversational queries
    conversational = is_conversational_query(query)
    analytics = {} if conversational else build_analytics_payload(tool_outputs)
    logger.info(
        f"[ANALYTICS] conversational={conversational} show_analytics={not conversational}"
    )

    resolver_note = (
        "Note: Answer derived fully from memory (no new tool calls)."
        if res_type == "direct"
        else ""
    )

    final_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=_build_llm_messages(query, tool_outputs, resolver_note),
    )

    final_text = "".join(
        block.text for block in final_response.content if hasattr(block, "text")
    )
    final_text = add_system_context(final_text, query)
    memory.add("assistant", final_text)

    info = _call_tool_cached.cache_info()

    return _json_safe_meta(
        {
            "text": final_text,
            "data": {
                k: {sk: sv for sk, sv in v.items() if sk != "raw"}
                for k, v in tool_outputs.items()
            },
            "analytics": analytics,
            "show_analytics": not conversational,
            "resolver": resolution,
            "cache_stats": {
                "hits": info.hits,
                "misses": info.misses,
                "size": info.currsize,
                "maxsize": info.maxsize,
            },
        }
    )


# ---------------------------------------------------
# 🔥 STREAMING AGENT (MEMORY-AWARE)
# ---------------------------------------------------
# async def run_agent_stream(query: str, mcp_client=None):
#     """
#     Yields:
#       - str tokens
#       - "[END]" sentinel
#       - JSON meta string with show_analytics flag
#     """
#     memory.add("user", query)
#     tool_outputs = {}

#     resolution = context_resolver.resolve(query)
#     res_type = resolution["resolution"]
#     date = resolution["date"]
#     required_tools = resolution.get("required_tools", [])

#     logger.info(
#         f"[RESOLVER] type={res_type} | date={date} | "
#         f"required={required_tools} | missing={resolution.get('missing_tools', [])}"
#     )

#     if res_type == "direct":
#         logger.info("[AGENT] DIRECT → using memory only")
#         tool_outputs = resolution["cached_outputs"]

#     elif res_type == "ambiguous":
#         logger.info("[AGENT] AMBIGUOUS → partial fetch")
#         tool_outputs.update(resolution["cached_outputs"])
#         for tool_name in resolution["missing_tools"]:
#             before = _call_tool_cached.cache_info()
#             output = await _call_tool_cached(tool_name, date)
#             _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())
#             tool_outputs[tool_name] = output
#             structured_mem.store(tool_name, date, output)

#     else:
#         logger.info("[AGENT] MISS → planner execution")
#         plan = parse_plan(create_plan(query))
#         logger.info(f"[PLAN] {plan}")

#         for step in plan:
#             tool_name = step.get("tool")
#             tool_input = _normalize_date(step.get("args", {}))
#             date = tool_input.get("date", date)

#             before = _call_tool_cached.cache_info()
#             output = await _call_tool_cached(tool_name, date)
#             _log_cache_event(tool_name, date, before, _call_tool_cached.cache_info())

#             tool_outputs[tool_name] = output
#             structured_mem.store(tool_name, date, output)

#     if not tool_outputs:
#         logger.warning("[AGENT] No tool outputs — aborting stream")
#         yield "[END]"
#         return

#     # 🔑 Suppress analytics for conversational queries
#     conversational = is_conversational_query(query)
#     analytics = {} if conversational else build_analytics_payload(tool_outputs)
#     logger.info(
#         f"[ANALYTICS] conversational={conversational} show_analytics={not conversational}"
#     )

#     resolver_note = (
#         "Note: Answer derived fully from memory (no new tool calls)."
#         if res_type == "direct"
#         else ""
#     )

#     final_text = ""

#     with client.messages.stream(
#         model=MODEL_NAME,
#         max_tokens=MAX_TOKENS,
#         temperature=0,
#         system=SYSTEM_PROMPT,
#         messages=_build_llm_messages(query, tool_outputs, resolver_note),
#     ) as stream:
#         for event in stream:
#             if event.type == "content_block_delta":
#                 if hasattr(event.delta, "text") and event.delta.text:
#                     token = event.delta.text
#                     final_text += token
#                     yield token

#     final_text = add_system_context(final_text, query)
#     memory.add("assistant", final_text)

#     yield "[END]"

#     info = _call_tool_cached.cache_info()

#     yield json.dumps(
#         _json_safe_meta(
#             {
#                 "type": "meta",
#                 "resolver": resolution,
#                 "analytics": analytics,
#                 "show_analytics": not conversational,  # 🔑 UI gate
#                 "cache_stats": {
#                     "hits": info.hits,
#                     "misses": info.misses,
#                     "size": info.currsize,
#                     "maxsize": info.maxsize,
#                 },
#             }
#         )
#     )


async def run_agent_stream(query: str, mcp_client=None):
    """
    Yields:
      - str tokens
      - "[END]" sentinel
      - JSON meta string with show_analytics flag
    """

    # ---------------------------------------------------
    # ✅ ADD USER MESSAGE (ONLY ONCE)
    # ---------------------------------------------------
    memory.add("user", query)

    tool_outputs = {}
    res_type = None
    resolution = None
    date = None

    # ---------------------------------------------------
    # 🔥 STEP 1: HANDLE CLARIFICATION (SHORT-CIRCUIT)
    # ---------------------------------------------------
    history = memory.get()
    last_msg = history[-2] if len(history) >= 2 else None

    if last_msg and last_msg["role"] == "assistant":
        if "Which result are you referring to?" in last_msg["content"]:

            user_input = query.lower().strip()

            TOOL_MAP = {
                "1": "get_energy_forecast_tool",
                "solar": "get_energy_forecast_tool",
                "solar production": "get_energy_forecast_tool",
                "2": "get_weather_forecast_tool",
                "weather": "get_weather_forecast_tool",
                "3": "get_adjusted_forecast_tool",
                "adjusted": "get_adjusted_forecast_tool",
                "adjusted solar": "get_adjusted_forecast_tool",
            }

            selected_tool = next(
                (tool for key, tool in TOOL_MAP.items() if key in user_input), None
            )

            if selected_tool:
                logger.info(f"[AGENT] Clarification resolved → {selected_tool}")

                latest = structured_mem.get_latest()

                if latest:
                    date = latest[1]
                else:
                    date = extract_date(query)

                if not date:
                    date = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

                cached = structured_mem.lookup(selected_tool, date) if date else None

                if cached:
                    tool_outputs = {selected_tool: cached}
                else:
                    before = _call_tool_cached.cache_info()
                    output = await _call_tool_cached(selected_tool, date)
                    _log_cache_event(
                        selected_tool, date, before, _call_tool_cached.cache_info()
                    )

                    tool_outputs = {selected_tool: output}
                    structured_mem.store(selected_tool, date, output)

                res_type = "direct"

                # 🔥 FAKE RESOLUTION OBJECT (for meta consistency)
                resolution = {
                    "resolution": "direct",
                    "date": date,
                    "required_tools": [selected_tool],
                    "cached_outputs": tool_outputs,
                    "missing_tools": [],
                    "source": "clarification",
                }

    # ---------------------------------------------------
    # 🔥 STEP 2: NORMAL FLOW (ONLY IF NOT CLARIFIED)
    # ---------------------------------------------------
    if res_type != "direct":

        resolution = context_resolver.resolve(query)
        res_type = resolution["resolution"]
        date = resolution.get("date")
        required_tools = resolution.get("required_tools", [])

        logger.info(
            f"[RESOLVER] type={res_type} | date={date} | "
            f"required={required_tools} | missing={resolution.get('missing_tools', [])}"
        )

        # ---------------------------------------------------
        # ✅ DIRECT
        # ---------------------------------------------------
        if res_type == "direct":
            logger.info("[AGENT] DIRECT → using memory only")
            tool_outputs = resolution["cached_outputs"]

        # ---------------------------------------------------
        # 🔥 AMBIGUOUS → ASK USER
        # ---------------------------------------------------
        elif res_type == "ambiguous":
            logger.info("[AGENT] AMBIGUOUS → asking clarification")

            question = build_clarification_question(resolution["candidates"])
            memory.add("assistant", question)

            yield question
            yield "[END]"

            info = _call_tool_cached.cache_info()

            yield json.dumps(
                _json_safe_meta(
                    {
                        "type": "meta",
                        "resolver": resolution,
                        "analytics": {},
                        "show_analytics": False,
                        "cache_stats": {
                            "hits": info.hits,
                            "misses": info.misses,
                            "size": info.currsize,
                            "maxsize": info.maxsize,
                        },
                    }
                )
            )

            return

        # ---------------------------------------------------
        # 🔥 MISS → PLANNER
        # ---------------------------------------------------
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
                _log_cache_event(
                    tool_name, date, before, _call_tool_cached.cache_info()
                )

                tool_outputs[tool_name] = output
                structured_mem.store(tool_name, date, output)

    # ---------------------------------------------------
    # 🔒 SAFETY CHECK
    # ---------------------------------------------------
    if not tool_outputs:
        logger.warning("[AGENT] No tool outputs — aborting stream")
        yield "[END]"
        return

    # ---------------------------------------------------
    # 🔑 ANALYTICS CONTROL
    # ---------------------------------------------------
    conversational = is_conversational_query(query)
    analytics = {} if conversational else build_analytics_payload(tool_outputs)

    logger.info(
        f"[ANALYTICS] conversational={conversational} show_analytics={not conversational}"
    )

    resolver_note = (
        "Note: Answer derived fully from memory (no new tool calls)."
        if res_type == "direct"
        else ""
    )

    # ---------------------------------------------------
    # 🔥 LLM STREAM
    # ---------------------------------------------------
    final_text = ""

    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=_build_llm_messages(query, tool_outputs, resolver_note),
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta":
                if hasattr(event.delta, "text") and event.delta.text:
                    token = event.delta.text
                    final_text += token
                    yield token

    final_text = add_system_context(final_text, query)
    memory.add("assistant", final_text)

    yield "[END]"

    info = _call_tool_cached.cache_info()

    yield json.dumps(
        _json_safe_meta(
            {
                "type": "meta",
                "resolver": resolution,
                "analytics": analytics,
                "show_analytics": not conversational,
                "cache_stats": {
                    "hits": info.hits,
                    "misses": info.misses,
                    "size": info.currsize,
                    "maxsize": info.maxsize,
                },
            }
        )
    )
