import os
<<<<<<< HEAD

=======
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
>>>>>>> eaf119e (Implemented MCP-based energy forecasting agent with:)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")