from pydantic import BaseModel
from datetime import datetime, timedelta

from services.forecast_service import EnergyForecastService
from configs.settings import MODEL_PATH, WEIGHTS_PATH


# ✅ Initialize ONCE (critical for performance)
forecast_service = EnergyForecastService(
    model_path=MODEL_PATH,
    weights_path=WEIGHTS_PATH
)


class ForecastInput(BaseModel):
    date: str | None = None


def run_energy_forecast(date: str):

    df = forecast_service.get_hourly_forecast(date)

    # ✅ Convert DataFrame → JSON-safe dict
    return {
        k.strftime("%Y-%m-%d %H:%M:%S"): float(v)
        for k, v in df["forecast_hourly"].to_dict().items()
    }