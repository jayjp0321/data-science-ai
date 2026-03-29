from mcp_core.server.registry import get_tool

def handle_request(tool_name, args):
    tool = get_tool(tool_name)
    
    if not tool:
        return {"error": "Tool not found"}
    
    return tool.func(**args)