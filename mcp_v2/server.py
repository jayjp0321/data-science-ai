import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import traceback
from fastmcp import FastMCP
from mcp_v2.tools.weather_tool import get_weather_forecast
from configs.settings import DEFAULT_LOCATION  # ✅ import from settings
from mcp_v2.tools.forecast_tool import run_energy_forecast, ForecastInput
from datetime import datetime, timedelta
from mcp_v2.tools.adjustment_tool import run_solar_adjustment

mcp = FastMCP("Energy-AI-MCP")

@mcp.tool
def get_weather_forecast_tool(date: str):  # ✅ location removed from params
    """Get weather forecast for a given date."""
    try:
        return get_weather_forecast(date=date, location=DEFAULT_LOCATION)  # ✅ hardcoded from settings
    except Exception as e:
        print("🔥 TOOL ERROR:", str(e))
        traceback.print_exc()
        return {"status": "failed", "error": str(e)}



@mcp.tool  # ✅ remove input_model=ForecastInput
def get_energy_forecast_tool(date: str = None):  # ✅ direct typed parameter
    """Get solar energy forecast for a given date."""
    try:
        # ✅ Date resolution stays here, same logic
        if date is None or date.lower() == "tomorrow":
            date = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif date.lower() == "today":
            date = datetime.utcnow().strftime("%Y-%m-%d")

        return run_energy_forecast(date)

    except Exception as e:
        print("FORECAST TOOL ERROR:", str(e))
        traceback.print_exc()
        return {"status": "failed", "error": str(e)}
    

@mcp.tool
def get_adjusted_forecast_tool(date: str):
    """Get weather-adjusted solar energy forecast for a given date."""
    try:
        return run_solar_adjustment(date)
    except Exception as e:
        traceback.print_exc()
        return {"status": "failed", "error": str(e)}
    
if __name__ == "__main__":
    mcp.run()