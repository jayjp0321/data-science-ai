import os

from dotenv import load_dotenv

load_dotenv()

# -----------------------
# LLM Configuration
# -----------------------
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 500))

# -----------------------
# Memory Configuration
# -----------------------
MEMORY_WINDOW = int(os.getenv("MEMORY_WINDOW", 10))

# -----------------------
# API Keys
# -----------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# -----------------------
# Weather tool default location
# -----------------------
DEFAULT_LOCATION = "Spain"

# -----------------------
# Forecast tool paths
# -----------------------
MODEL_PATH = "models/energy/solar_forecast/ucm_model_2020_2023.pkl"
WEIGHTS_PATH = "models/energy/solar_forecast/hourly_weights.pkl"

MAX_ANALYTICS_MESSAGES = 3  # keep analytics only for last N assistant messages
RENDER_INTERVAL = 0.1  # Render Tokens to UI every 0.1 seconds during streaming
