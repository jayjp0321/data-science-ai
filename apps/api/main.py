import time
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI
from pydantic import BaseModel
import asyncio
from agent.agent import run_agent_async, run_agent_stream, start_mcp_client
from fastapi.responses import StreamingResponse

# ---------------------------------------------------
# 🔥 GLOBAL LOGGING CONFIG (ROOT LOGGER)
# ---------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

root_logger = logging.getLogger()

# Guard: only add the file handler once even if this
# module is imported multiple times by uvicorn workers.
if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
    file_handler = RotatingFileHandler(
        "api.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    ))
    root_logger.addHandler(file_handler)

# ---------------------------------------------------
# 🔥 MODULE LOGGER
# ---------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------
# 🔥 FIX: propagate=False on this module's logger
#    stops uvicorn's root handler from printing every
#    line a second time via the propagation chain.
# ---------------------------------------------------
logger.propagate = False

if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)


# ---------------------------------------------------
# 🔥 FASTAPI LIFECYCLE
# ---------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "mcp_client") or app.state.mcp_client is None:
        logger.info("[STARTUP] Initializing MCP client")
        app.state.mcp_client = await start_mcp_client()
        logger.info("[STARTUP] MCP client ready")
    else:
        logger.info("[STARTUP] MCP client already initialized — skipping")

    yield

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
    data: Dict[str, Any]

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ready")
async def readiness():
    try:
        client = getattr(app.state, "mcp_client", None)
        if client is None:
            return {"status": "not_ready", "reason": "MCP client not initialized"}
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"[READINESS_ERROR] {str(e)}")
        return {"status": "not_ready", "reason": str(e)}


# ---------------------------------------------------
# 🔥 SYNC CHAT ENDPOINT
# ---------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    message_id = request.message_id
    query = request.query
    logger.info(f"[API_RECEIVED][{message_id}] {query}")
    start_time = time.time()
    try:
        result = await asyncio.wait_for(
            run_agent_stream(query, app.state.mcp_client),
            timeout=90
        )
        latency = time.time() - start_time
        logger.info(f"[AGENT_END][{message_id}] Completed in {latency:.2f}s")
        return {"response": result["text"], "data": result["data"]}
    except Exception as e:
        latency = time.time() - start_time
        logger.error(f"[API_ERROR][{message_id}] {str(e)} | latency={latency:.2f}s")
        return {"response": f"Error: {str(e)}", "data": {}}


# ---------------------------------------------------
# 🔥 STREAMING GENERATOR
# ---------------------------------------------------
async def stream_agent_response(query, message_id, mcp_client):
    try:
        yield "data: [START]\n\n"

        async for token in run_agent_stream(query, mcp_client):

            logger.info(f"[API_STREAM] {token}")

            if token == "[END]":
                yield "data: [END]\n\n"
                continue

            if token.startswith('{"type": "meta"'):
                yield f"data: {token}\n\n"
                continue

            if not token or token.strip() == "":
                continue

            # -------------------------------------------------------
            # 🔥 Split tokens containing \n into separate SSE frames.
            #    requests.iter_lines() drops embedded newlines inside
            #    a single "data: ...\n\n" frame, so we must send each
            #    line as its own frame to preserve markdown structure.
            # -------------------------------------------------------
            if "\n" in token:
                parts = token.split("\n")
                for part in parts[:-1]:
                    yield f"data: {part}\n\n"   # complete line
                    yield "data: \n\n"           # the \n itself as blank frame
                if parts[-1]:                    # trailing partial line
                    yield f"data: {parts[-1]}\n\n"
            else:
                yield f"data: {token}\n\n"

    except Exception as e:
        logger.error(f"[STREAM_ERROR] {str(e)}")
        yield f"data: ERROR: {str(e)}\n\n"


# ---------------------------------------------------
# 🔥 STREAMING ENDPOINT
# ---------------------------------------------------
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    message_id = request.message_id
    query = request.query
    logger.info(f"[STREAM_API][{message_id}] {query}")
    return StreamingResponse(
        stream_agent_response(query, message_id, app.state.mcp_client),
        media_type="text/event-stream"
    )