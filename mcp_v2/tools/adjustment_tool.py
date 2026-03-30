# mcp_v2/tools/adjustment_tool.py
from mcp_v2.tools.weather_tool import get_weather_forecast
from mcp_v2.tools.forecast_tool import run_energy_forecast
from configs.settings import DEFAULT_LOCATION

def run_solar_adjustment(date: str) -> dict:
    """Fetch weather + energy forecast and return adjusted solar output for a date."""
    
    weather = get_weather_forecast(date=date, location=DEFAULT_LOCATION)
    energy = run_energy_forecast(date)

    cloud_cover = weather.get("avg_cloud_cover", 0)
    adjustment_factor = 1 - (cloud_cover / 100) * 0.7

    adjusted_hourly = {
        hour: round(kwh * adjustment_factor, 2)
        for hour, kwh in energy.items()
    }

    total_base = sum(energy.values())
    total_adjusted = sum(adjusted_hourly.values())

    return {
        "date": date,
        "cloud_cover": cloud_cover,
        "adjustment_factor": round(adjustment_factor, 4),
        "base_total_kwh": round(total_base, 2),
        "adjusted_total_kwh": round(total_adjusted, 2),
        "adjusted_hourly_kwh": adjusted_hourly,
        "status": "success"
    }