from mcp_core.server.server import handle_request

def call_tool(tool_name: str, arguments: dict):
    response = handle_request(tool_name, arguments)
    return response