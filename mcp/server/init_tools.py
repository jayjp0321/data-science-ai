from mcp.server.registry import register_tool
from tools.forecasting.forecast_tool import forecast_tool

def init_tools():
    register_tool(forecast_tool)