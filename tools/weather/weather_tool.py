from mcp.schemas.tool_schema import Tool
from services.weather_service import WeatherService
from configs.settings import DEFAULT_LOCATION
import requests
from mcp.schemas.tool_schema import Tool
from services.weather_service import WeatherService
from configs.settings import DEFAULT_LOCATION

service = WeatherService()


def get_weather_data(date: str, location: str = None):

    if not location:
        location = DEFAULT_LOCATION

    result = service.get_weather_forecast(date, location)

    return result


weather_tool = Tool(
    name="get_weather_data",
    description="Get weather forecast (temperature, cloud cover) for a given date and location",
    input_schema={
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "location": {"type": "string"}
        },
        "required": ["date"]
    },
    func=get_weather_data
)