import anthropic
<<<<<<< HEAD
from mcp.client.client import call_tool

client = anthropic.Anthropic()

def run_agent(query):
    response = client.messages.create(
        model="claude-3-sonnet-20240229",
        messages=[{"role": "user", "content": query}],
        tools=[{
            "name": "get_energy_forecast",
            "description": "Get forecast",
            "input_schema": {"type": "object"}
        }]
    )

    tool_call = response.content[0].input

    result = call_tool(
        tool_call["name"],
        tool_call["arguments"]
    )

    return result
=======
from agent.planner import create_plan, parse_plan
from agent.memory import ConversationMemory
from mcp.client.client import call_tool
from configs.settings import (
    ANTHROPIC_API_KEY,
    MODEL_NAME,
    MAX_TOKENS,
    MEMORY_WINDOW
)

# Initialize client
client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY
)

memory = ConversationMemory(MEMORY_WINDOW)


# -------------------------------
# Agent Runner
# -------------------------------
def run_agent(query):

    memory.add("user", query)

    # Step 1: Create plan
    plan_text = create_plan(query)
    plan = parse_plan(plan_text)

    results = []

    # Step 2: Execute plan
    for step in plan:
        tool_name = step.get("tool")
        args = step.get("args", {})

        result = call_tool(tool_name, args)
        results.append({tool_name: result})

    # Step 3: Final reasoning
    final_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[
            *memory.get(),
            {
                "role": "user",
                "content": f"""
User query: {query}

Tool results:
{results}

Provide final answer with reasoning.
"""
            }
        ]
    )

    final_text = final_response.content[0].text

    memory.add("assistant", final_text)

    return final_text
>>>>>>> eaf119e (Implemented MCP-based energy forecasting agent with:)
