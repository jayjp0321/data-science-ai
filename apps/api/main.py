import time
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI
from pydantic import BaseModel
import asyncio
from agent.agent import run_agent_async, start_mcp_client


# ---------------------------------------------------
# 🔥 LOGGING SETUP (PRODUCTION SAFE)
# ---------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        "api.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ---------------------------------------------------
# 🔥 FASTAPI LIFECYCLE (MODERN REPLACEMENT)
# ---------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[STARTUP] Initializing MCP client")

    app.state.mcp_client = await start_mcp_client()

    logger.info("[STARTUP] MCP client ready")

    yield  # 🚀 app runs here

    # (Optional future cleanup)
    logger.info("[SHUTDOWN] Cleaning up resources")


# ---------------------------------------------------
# 🔥 APP INIT
# ---------------------------------------------------
app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------
# 🔥 REQUEST / RESPONSE MODELS
# ---------------------------------------------------
class ChatRequest(BaseModel):
    query: str
    message_id: str




class ChatResponse(BaseModel):
    response: str
    data: Dict[str, Any]      # Optional structured data from tools to return hourly forecast in table format


# ---------------------------------------------------
# 🔥 API ENDPOINT
# ---------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):

    message_id = request.message_id
    query = request.query

    logger.info(f"[API_RECEIVED][{message_id}] {query}")

    start_time = time.time()

    try:
        logger.info(f"[AGENT_START][{message_id}] Running async agent")

        result = await asyncio.wait_for(
            run_agent_async(query, app.state.mcp_client),
            timeout=90
        )

        latency = time.time() - start_time

        logger.info(f"[AGENT_END][{message_id}] Completed")
        logger.info(f"[API_LATENCY][{message_id}] {latency:.2f}s")
        logger.info(f"[DATA_KEYS][{message_id}] {list(result['data'].keys())}")
        return {
                    "response": result["text"],
                    "data": result["data"]
                }
        #return {"response": result}

    except Exception as e:
        latency = time.time() - start_time

        logger.error(
            f"[API_ERROR][{message_id}] {str(e)} | latency={latency:.2f}s"
        )

        return {"response": f"Error: {str(e)}",
                "data": {}
                }