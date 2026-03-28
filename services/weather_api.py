import requests

def fetch_weather(location: str):
    url = f"https://wttr.in/{location}?format=j1"

    response = requests.get(url)
    data = response.json()

    current = data["current_condition"][0]

    return {
        "location": location,
        "temperature_C": current["temp_C"],
        "weather": current["weatherDesc"][0]["value"],
        "humidity": current["humidity"]
    }