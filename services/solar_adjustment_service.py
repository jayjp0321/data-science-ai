class SolarAdjustmentService:

    def adjust_forecast(self, energy_data, weather_data):

        if energy_data["status"] != "success":
            return energy_data

        if weather_data["status"] != "success":
            return energy_data  # fallback

        base = energy_data.get("total", 0)

        cloud_cover = weather_data.get("avg_cloud_cover", 0)

        # 🔥 Simple physics-based adjustment
        # More clouds → less production
        adjustment_factor = 1 - (cloud_cover / 100) * 0.7

        adjusted = base * adjustment_factor

        return {
            "date": energy_data["date"],
            "base_forecast": base,
            "cloud_cover": cloud_cover,
            "adjusted_forecast": adjusted,
            "adjustment_factor": adjustment_factor,
            "status": "success"
        }