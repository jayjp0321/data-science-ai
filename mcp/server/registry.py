TOOLS = {}

def register_tool(tool):
    TOOLS[tool.name] = tool

def get_tool(name):
    return TOOLS.get(name)