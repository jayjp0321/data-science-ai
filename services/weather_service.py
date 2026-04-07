import requests
import pandas as pd


class WeatherService:

    def __init__(self):
        # Default Spain (Madrid)
        self.default_lat = 40.4168
        self.default_lon = -3.7038

    def get_weather_forecast(self, date: str, location: str = None):

        # 👉 For now: Spain default
        lat = self.default_lat
        lon = self.default_lon

        url = (
            f"https://ensemble-api.open-meteo.com/v1/ensemble"  # ← changed: ensemble endpoint (works in browser)
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,cloud_cover"  # ← changed: cloudcover → cloud_cover
            f"&models=icon_seamless"  # ← required for ensemble API
            f"&timezone=auto"
            f"&forecast_days=2"  # today + tomorrow covers all "tomorrow" queries
        )

        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return {
                "status": "failed",
                "error": f"API request failed with status {response.status_code}: {response.text}",
            }

        data = response.json()

        # Convert to DataFrame
        df = pd.DataFrame(
            {
                "time": data["hourly"]["time"],
                "temperature": data["hourly"]["temperature_2m"],
                "cloudcover": data["hourly"][
                    "cloud_cover"
                ],  # ← key in API response is now cloud_cover
            }
        )

        df["time"] = pd.to_datetime(df["time"])

        # Filter for requested date
        target_date = pd.to_datetime(date).date()
        df = df[df["time"].dt.date == target_date]

        if df.empty:
            return {
                "status": "success",
                "warning": "No weather data available, using fallback",
                "avg_cloud_cover": 50,
                "avg_temperature": 15,
            }

        return {
            "date": date,
            "avg_temperature": float(df["temperature"].mean()),
            "avg_cloud_cover": float(df["cloudcover"].mean()),
            "hourly": {
                k.strftime("%Y-%m-%d %H:%M:%S"): float(v)
                for k, v in df.set_index("time")["temperature"].to_dict().items()
            },
            "status": "success",
        }
