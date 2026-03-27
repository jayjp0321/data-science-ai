import anthropic
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