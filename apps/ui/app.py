import streamlit as st
import requests
import time
import logging
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------
# 🔥 LOGGING SETUP
# ---------------------------------------------------
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
#     handlers=[
#         logging.FileHandler("app.log"),   # ← file logging
#         logging.StreamHandler()           # ← console logging
#     ]
# )

# logger = logging.getLogger(__name__)


# ---------------------------------------------------
# 🔥 LOGGING SETUP- Rotating logs- Managing only last 3 files each upto 5MB
# ---------------------------------------------------

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = RotatingFileHandler(
        "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# def stream_text(text):
#     for word in text.split():
#         yield word + " "
#         time.sleep(0.05)

st.title("⚡ Energy AI Chatbot")

API_URL = "http://localhost:8000/chat"

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Input
user_input = st.chat_input("Ask your energy question...")

import uuid

if user_input:
    # Create user message
    user_msg = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": user_input
    }
    logger.info(f"[USER][{user_msg['id']}] {user_input}")
    st.session_state.messages.append(user_msg)

    with st.chat_message("user"):
        st.write(user_input)

    # API call
    with st.spinner("Thinking..."):
        try:
            logger.info(f"[API_REQUEST][{user_msg['id']}] Sending query to backend")
            start_time = time.time()
            response = requests.post(
                API_URL,
                json={"query": user_input, "message_id": user_msg["id"]},
                timeout=10
            )
            
            latency = time.time() - start_time
            logger.info(f"[LATENCY][{user_msg['id']}] {latency:.2f}s")
            logger.info(f"[API_STATUS][{user_msg['id']}] {response.status_code}")
            response.raise_for_status()
            answer = response.json().get("response", "No response")
            logger.info(f"[API_RESPONSE][{user_msg['id']}] {answer[:200]}...")
        except requests.Timeout:
            logger.error(f"[TIMEOUT][{user_msg['id']}] Request timed out")
            answer = "Request timed out. Please try again."

        except requests.RequestException as e:
            logger.error(f"[REQUEST_ERROR][{user_msg['id']}] {str(e)}")
            answer = f"Error: {str(e)}"

    # Create assistant message
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": answer
    }
    st.session_state.messages.append(assistant_msg)
    logger.info(f"[ASSISTANT][{assistant_msg['id']}] {answer}")
    with st.chat_message("assistant"):
        st.write(answer)   # ← NOT write_stream