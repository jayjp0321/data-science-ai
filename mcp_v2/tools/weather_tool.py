from pydantic import BaseModel
from services.weather_service import WeatherService
from configs.settings import DEFAULT_LOCATION
from datetime import datetime, timedelta
import traceback

weather_service = WeatherService()


class WeatherInput(BaseModel):
    date: str | None = None
    location: str | None = None

def get_weather_forecast(date: str = None, location: str = None):

    # ✅ Default date = tomorrow
    if date is None:
        date = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

    # ✅ Default location
    if location is None:
        location = DEFAULT_LOCATION

    return weather_service.get_weather_forecast(date, location)