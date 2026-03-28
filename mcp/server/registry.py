TOOLS = {}

def register_tool(tool):
    TOOLS[tool.name] = tool

def get_tool(name):
<<<<<<< HEAD
    return TOOLS.get(name)
=======
    return TOOLS.get(name)

def list_tools():
    tool_list = []

    for tool in TOOLS.values():
        tool_list.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema
        })

    return tool_list
>>>>>>> eaf119e (Implemented MCP-based energy forecasting agent with:)
