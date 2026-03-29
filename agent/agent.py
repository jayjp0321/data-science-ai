import anthropic
from agent.planner import create_plan, parse_plan
from agent.memory import ConversationMemory
from mcp.client.client import call_tool
from configs.settings import (
    ANTHROPIC_API_KEY,
    MODEL_NAME,
    MAX_TOKENS,
    MEMORY_WINDOW
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
memory = ConversationMemory(MEMORY_WINDOW)


def run_agent(query):

    memory.add("user", query)

    # -------------------------------
    # Step 1: Create plan
    # -------------------------------
    plan_text = create_plan(query)
    plan = parse_plan(plan_text)
    tool_results_blocks = []

    # -------------------------------
    # Step 2: Execute tools
    # -------------------------------
    for idx, step in enumerate(plan):
        tool_name = step.get("tool")
        args = step.get("args", {})

        result = call_tool(tool_name, args)
        # ✅ Safety check
        if result.get("status") == "failed":
            return f"Tool `{tool_name}` failed: {result.get('error')}"
        # 🔥 Create MCP-compliant tool_result block
        tool_results_blocks.append({
        "type": "tool_result",
        "tool_use_id": f"tool_{idx}",
        "content": [
            {
                "type": "text",
                "text": str(result)
            }
        ]
    })

    # -------------------------------
    # Step 3: Final reasoning (MCP style)
    # -------------------------------
    final_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[
            *memory.get(),
            {
                "role": "user",
                "content": f"""
    User query: {query}

    Executed plan:
    {plan}

    Tool results:
    {tool_results_blocks}

    Use this data to provide final answer with reasoning.
    """
            }
        ]
    )
    
    # -------------------------------
    # Step 4: Extract response
    # -------------------------------
    final_text = ""
    for block in final_response.content:
        if hasattr(block, "text"):
            final_text += block.text

    memory.add("assistant", final_text)

    return final_text