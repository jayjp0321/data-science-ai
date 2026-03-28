import anthropic
import json
from configs.settings import MODEL_NAME, MAX_TOKENS, ANTHROPIC_API_KEY
from mcp.server.registry import list_tools

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def create_plan(query):

    tools = list_tools()

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,

        # ✅ SYSTEM PROMPT (behavior control)
        system="""
You are an AI planner for an intelligent agent.

Your responsibilities:
- Understand the user query
- Decide whether tools are needed
- Select appropriate tools if required
- If tools are not needed, respond with empty list []

Rules:
- Do NOT force tool usage
- Use tools ONLY when external data is required
- Prefer reasoning if answer can be derived without tools
- Always return valid JSON
- Do NOT include explanation outside JSON
""",

        messages=[
            {
                "role": "user",
                "content": f"""
User query:
{query}

Available tools:
{json.dumps(tools, indent=2)}

Task:
Return a JSON list of steps.

Format:
[
  {{"tool": "tool_name", "args": {{...}}}},
  ...
]

If no tools needed:
[]
"""
            }
        ]
    )

    text = response.content[0].text

    print("\n[Planner Output]:", text)  # Debug visibility

    return text


def parse_plan(plan_text):
    try:
        return json.loads(plan_text)
    except Exception:
        return []