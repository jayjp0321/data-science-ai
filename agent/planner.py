import anthropic
import json
from configs.settings import MODEL_NAME, MAX_TOKENS, ANTHROPIC_API_KEY  
from mcp.server.registry import list_tools
from datetime import datetime

today = datetime.today().strftime("%Y-%m-%d")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def create_plan(query):

    tools = list_tools()

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,

        # ✅ SYSTEM PROMPT (behavior control)
        system="""
                You are an intelligent AI planner for an MCP-based agent.

                Your responsibilities:
                - Understand the user query deeply
                - Extract structured parameters like date, location
                - Decide whether tools are needed
                - Select one or more tools if required
                - Combine tools when reasoning is needed

                Guidelines:

                1. ALWAYS extract DATE if present in query
                - Convert to format: YYYY-MM-DD
                - Example: "13th Jan 2024" → "2024-01-13"

                2. Tool usage:
                - Factual queries → single tool
                - Analytical queries (why, explain) → multiple tools

                3. Tool selection:
                - get_energy_forecast → for solar production
                - get_weather_data → for environmental factors

                4. IMPORTANT:
                - If using weather tool → ALWAYS pass "date"
                - Do NOT use placeholders like "default"

                5. If no tools required:
                return []

                6. Always return STRICT JSON list:
                [
                {"tool": "tool_name", "args": {...}}
                ]

                NO explanation outside JSON.
                """,

        messages=[
            {
                "role": "user",
                "content":f"""
                        User query:
                        {query}

                        Today's date:
                        {today}

                        Available tools:
                        {json.dumps(tools, indent=2)}

                        Important:
                        - Convert relative dates:
                        "today" → {today}
                        "tomorrow" → next day from today
                        - Use realistic dates ONLY
                        - Weather API supports near-term forecast only

                        Return ONLY JSON list.
                        """
            }
        ]
    )

    text = response.content[0].text

    print("\n[Planner Output]:", text)  # Debug visibility

    return text


def parse_plan(plan_text):
    try:
        # 🔥 Remove markdown formatting
        cleaned = plan_text.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "")
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

        return json.loads(cleaned)

    except Exception as e:
        print("Parsing Error:", e)
        return []