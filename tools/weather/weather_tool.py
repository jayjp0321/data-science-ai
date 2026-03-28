from mcp.schemas.tool_schema import Tool
from services.weather_api import fetch_weather

def get_weather(location: str = "Bangalore"):
    result = fetch_weather(location)

    return {
        "location": result["location"],
        "temperature_C": result["temperature_C"],
        "condition": result["weather"],
        "humidity": result["humidity"]
    }

weather_tool = Tool(
    name="get_weather_data",
    description="Get real-time weather data for a location",
    input_schema={
        "type": "object",
        "properties": {
            "location": {"type": "string"}
        },
        "required": ["location"]
    },
    func=get_weather
)