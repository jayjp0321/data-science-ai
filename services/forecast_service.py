import joblib
import pandas as pd
import numpy as np


class EnergyForecastService:

    def __init__(self, model_path: str, weights_path: str):
        self.model = joblib.load(model_path)
        self.hourly_weights = joblib.load(weights_path)

    # -------------------------------
    # Step 1: Daily Forecast
    # -------------------------------
    def get_daily_forecast(self, date: str):

        target_date = pd.to_datetime(date)
        last_train_date = pd.to_datetime("2023-12-31")

        steps = (target_date - last_train_date).days

        if steps <= 0:
            raise ValueError("Date must be in future")

        forecast = self.model.get_forecast(steps=steps)
        log_forecast = forecast.predicted_mean

        forecast_vals = np.exp(log_forecast)

        return forecast_vals

    # -------------------------------
    # Step 2: Hourly Mapping
    # -------------------------------
    def hourly_mapping(self, df: pd.DataFrame, daily_forecast: pd.Series):

        out = df.copy()

        out["_month"] = out.index.month
        out["_hour"] = out.index.hour
        out["_date"] = out.index.normalize()

        out["_daily_forecast"] = out["_date"].map(daily_forecast)

        out["_hourly_key"] = list(zip(out["_month"], out["_hour"]))
        out["_hourly_weight_raw"] = out["_hourly_key"].map(self.hourly_weights)

        # daylight mask
        daylight_mask = out["_hourly_weight_raw"].notna()

        weight_sum_per_day = (
            out.loc[daylight_mask]
            .groupby(out.loc[daylight_mask, "_date"])["_hourly_weight_raw"]
            .transform("sum")
        )

        out["_hourly_weight"] = 0.0
        out.loc[daylight_mask, "_hourly_weight"] = (
            out.loc[daylight_mask, "_hourly_weight_raw"] / weight_sum_per_day
        )

        out["forecast_hourly"] = 0.0

        valid = out["_daily_forecast"].notna() & daylight_mask

        out.loc[valid, "forecast_hourly"] = (
            out.loc[valid, "_daily_forecast"]
            * out.loc[valid, "_hourly_weight"]
        )

        out.loc[~daylight_mask, "forecast_hourly"] = 0.0

        return out

    # -------------------------------
    # Step 3: Public API
    # -------------------------------
    def get_hourly_forecast(self, date: str):

        # 1. Daily forecast
        daily_forecast = self.get_daily_forecast(date)

        # 2. Create hourly index for that date
        start = pd.to_datetime(date)
        end = start + pd.Timedelta(days=1) - pd.Timedelta(hours=1)

        hourly_index = pd.date_range(start=start, end=end, freq="H")

        df = pd.DataFrame(index=hourly_index)

        # Convert daily forecast into mapping format
        daily_series = pd.Series(
            [daily_forecast.iloc[-1]],
            index=[start.normalize()]
        )

        # 3. Hourly mapping
        result = self.hourly_mapping(df, daily_series)

        return result[["forecast_hourly"]]