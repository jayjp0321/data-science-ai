# agent/context_resolver.py

import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

import re

# ---------------------------------------------------
# 🔥 DOMAIN CONFIG
# ---------------------------------------------------
DOMAIN_MAP = {
    "weather": {
        "keywords": ["weather", "temperature", "rain", "wind"],
        "tools": ["get_weather_forecast_tool"],
    },
    "solar": {
        "keywords": ["solar", "irradiance", "sunlight"],
        "tools": ["get_energy_forecast_tool"],
    },
    "adjusted": {
        "keywords": ["adjusted", "optimized"],
        "tools": ["get_adjusted_forecast_tool"],
    },
    "combined": {
        "keywords": [],
        "tools": [
            "get_weather_forecast_tool",
            "get_energy_forecast_tool",
        ],
    },
}

# ---------------------------------------------------
# 🔥 COMBINED PATTERNS
# ---------------------------------------------------
COMBINED_PATTERNS = [
    r"weather.*solar",
    r"solar.*weather",
    r"weather.*energy",
    r"energy.*weather",
]


# ---------------------------------------------------
# 🔥 DOMAIN CLASSIFIER (UPDATED: no hard fallback)
# ---------------------------------------------------
def classify_domain(query: str) -> list[str] | None:
    q = query.lower()

    scores = {}
    for domain, cfg in DOMAIN_MAP.items():
        hits = sum(1 for kw in cfg["keywords"] if kw in q)
        if hits > 0:
            scores[domain] = hits

    if not scores:
        logger.info("[DOMAIN] no match")
        return None  # 🔥 IMPORTANT CHANGE

    best = max(scores, key=scores.get)
    tools = DOMAIN_MAP[best]["tools"]

    if best == "adjusted":
        tools = ["get_energy_forecast_tool", "get_adjusted_forecast_tool"]

    logger.info(f"[DOMAIN] {best} → {tools}")
    return tools


# ---------------------------------------------------
# 🔥 DATE EXTRACTOR (UPDATED: no forced fallback)
# ---------------------------------------------------
def extract_date(query: str) -> str | None:
    q = query.lower()
    today = datetime.today()

    if "today" in q:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in q:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    match = re.search(r"\d{4}-\d{2}-\d{2}", query)
    if match:
        return match.group()

    logger.info("[DATE] no explicit date")
    return None  # 🔥 IMPORTANT CHANGE


# ---------------------------------------------------
# 🔥 CONTEXT RESOLVER (FULLY FIXED)
# ---------------------------------------------------
class ContextResolver:

    def __init__(self, memory):
        self.memory = memory

    def resolve(self, query: str) -> dict:

        # ---------------------------------------------------
        # 🔥 STEP 1: MEMORY-FIRST SEARCH
        # ---------------------------------------------------
        candidates = self.memory.search(query)

        if candidates:
            logger.info(f"[RESOLVER] MEMORY MATCH → {len(candidates)} candidates")

            # pick most recent
            tool, date, data = candidates[0]

            return {
                "resolution": "direct",
                "date": date,
                "required_tools": [tool],
                "cached_outputs": {tool: data},
                "missing_tools": [],
                "source": "memory",
            }

        # ---------------------------------------------------
        # 🔻 STEP 2: NORMAL RESOLUTION
        # ---------------------------------------------------
        tools = classify_domain(query)
        date = extract_date(query)

        # ---------------------------------------------------
        # 🔥 STEP 3: CONTEXT FILL FROM MEMORY
        # ---------------------------------------------------
        latest = self.memory.get_latest()

        if latest:
            last_tool, last_date, _ = latest

            if not tools:
                logger.info("[RESOLVER] filling tool from memory")
                tools = [last_tool]

            if not date:
                logger.info("[RESOLVER] filling date from memory")
                date = last_date

        # safety fallback (only if nothing exists at all)
        if not tools:
            logger.info("[RESOLVER] fallback → solar (last resort)")
            tools = ["get_energy_forecast_tool"]

        if not date:
            date = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

        # ---------------------------------------------------
        # 🔍 STEP 4: MEMORY LOOKUP (PRECISE)
        # ---------------------------------------------------
        cached_outputs = {}
        missing_tools = []

        for tool in tools:
            cached = self.memory.lookup(tool, date)
            if cached:
                cached_outputs[tool] = cached
            else:
                missing_tools.append(tool)

        # ---------------------------------------------------
        # 🔥 STEP 5: RESOLUTION DECISION
        # ---------------------------------------------------
        if not missing_tools:
            resolution = "direct"
            logger.info(f"[RESOLVER] DIRECT HIT | {tools} | {date}")

        elif cached_outputs:
            resolution = "ambiguous"
            logger.info(
                f"[RESOLVER] PARTIAL HIT | cached={list(cached_outputs.keys())} "
                f"| missing={missing_tools}"
            )

        else:
            resolution = "miss"
            logger.info(f"[RESOLVER] MISS | tools={tools} | date={date}")

        return {
            "resolution": resolution,
            "date": date,
            "required_tools": tools,
            "cached_outputs": cached_outputs,
            "missing_tools": missing_tools,
        }
