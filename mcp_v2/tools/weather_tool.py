from services.weather_service import WeatherService

weather_service = WeatherService()

def get_weather_forecast(date: str, location: str = None):
    """
    Get weather forecast for a given date.
    """
    return weather_service.get_weather_forecast(date, location)