from mcp_core.schemas.tool_schema import Tool
from services.forecast_service import EnergyForecastService


# -------------------------------
# Initialize Service (LOAD ONCE)
# -------------------------------
service = EnergyForecastService(
    model_path="models/energy/solar_forecast/ucm_model_2020_2023.pkl",
    weights_path="models/energy/solar_forecast/hourly_weights.pkl"
)


# -------------------------------
# Tool Function
# -------------------------------
def get_energy_forecast(date: str):

    try:
        df = service.get_hourly_forecast(date)

        hourly_forecast = {
            k.strftime("%Y-%m-%d %H:%M:%S"): float(v)
            for k, v in df["forecast_hourly"].to_dict().items()
        }

        return {
            "date": date,
            "hourly_forecast": hourly_forecast,
            "total": float(df["forecast_hourly"].sum()),
            "status": "success"
        }

    except Exception as e:
        return {
            "date": date,
            "error": str(e),
            "status": "failed"
        }


# -------------------------------
# MCP Tool Registration
# -------------------------------
energy_forecast_tool = Tool(
    name="get_energy_forecast",
    description = """
Get solar energy production forecast (MW).
Useful for predicting expected generation.
""",
    input_schema={
        "date": "string"
    },
    func=get_energy_forecast
)