from fastmcp import FastMCP
from mcp_core_v2.tools.weather_tool import get_weather_forecast

mcp = FastMCP("Energy-AI-MCP")

# Register tool
@mcp.tool()
def get_weather_forecast_tool(date: str, location: str = None):
    return get_weather_forecast(date, location)


if __name__ == "__main__":
    mcp.run()