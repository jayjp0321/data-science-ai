from mcp.server.registry import register_tool

#from tools.forecasting.forecast_tool import forecast_tool
from tools.energy.forecast_tool import energy_forecast_tool
from tools.weather.weather_tool import weather_tool
from tools.anomaly.anomaly_tool import anomaly_tool

def init_tools():
    register_tool(energy_forecast_tool)
    register_tool(weather_tool)
    register_tool(anomaly_tool)

    print("[MCP] Tools Registered:",
          energy_forecast_tool.name,
          weather_tool.name,
          anomaly_tool.name)
