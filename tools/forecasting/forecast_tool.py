from mcp.schemas.tool_schema import Tool

def forecast(date: str):
    return {
        "date": date,
        "forecast": 1250,
        "unit": "kWh"
    }

forecast_tool = Tool(
    name="get_energy_forecast",
    description="Get energy production forecast",
    input_schema={"date": "string"},
    func=forecast
)