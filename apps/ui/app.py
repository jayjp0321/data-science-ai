import streamlit as st
import requests
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import uuid

# ---------------------------------------------------
# 🔥 LOGGING SETUP
# ---------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ---------------------------------------------------
# 🔥 APP CONFIG
# ---------------------------------------------------
st.title("⚡ Energy AI Chatbot")

#API_URL = "http://localhost:8000/chat"
API_URL = "http://backend:8000/chat"

# ---------------------------------------------------
# 🔥 SESSION STATE INIT
# ---------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "structured" not in st.session_state:
    st.session_state.structured = []

if "answer" not in st.session_state:
    st.session_state.answer = ""


# ---------------------------------------------------
# 🔥 DISPLAY CHAT HISTORY
# ---------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


# ---------------------------------------------------
# 🔥 USER INPUT
# ---------------------------------------------------
user_input = st.chat_input("Ask your energy question...")

if user_input:
    user_msg = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": user_input
    }

    logger.info(f"[USER][{user_msg['id']}] {user_input}")
    st.session_state.messages.append(user_msg)

    with st.chat_message("user"):
        st.write(user_input)

    # ---------------------------------------------------
    # 🔥 API CALL (ONLY ON USER INPUT)
    # ---------------------------------------------------
    with st.spinner("Thinking..."):
        try:
            logger.info(f"[API_REQUEST][{user_msg['id']}] Sending query to backend")

            start_time = time.time()

            response = requests.post(
                API_URL,
                json={"query": user_input, "message_id": user_msg["id"]},
                timeout=120
            )

            latency = time.time() - start_time
            logger.info(f"[LATENCY][{user_msg['id']}] {latency:.2f}s")
            logger.info(f"[API_STATUS][{user_msg['id']}] {response.status_code}")

            response.raise_for_status()

            response_json = response.json()

            logger.info(f"[RAW STRUCTURE][{user_msg['id']}] {response.text[:500]}...")

            safe_log = dict(response_json)
            if "data" in safe_log:
                safe_log["data"] = "REDACTED"

            logger.info(f"[API_RESPONSE_FULL][{user_msg['id']}] {safe_log}")

            # ✅ STORE ONLY (NO UI HERE)
            st.session_state.answer = response_json.get("response", "No response")

            data = response_json.get("data", {})
            tool_data = data.get("get_energy_forecast_tool", {})
            st.session_state.structured = tool_data.get("structured", [])

        except requests.Timeout:
            logger.error(f"[TIMEOUT][{user_msg['id']}] Request timed out")
            st.session_state.answer = "Request timed out. Please try again."

        except requests.RequestException as e:
            logger.error(f"[REQUEST_ERROR][{user_msg['id']}] {str(e)}")
            st.session_state.answer = f"Error: {str(e)}"

    # ---------------------------------------------------
    # 🔥 SAVE ASSISTANT MESSAGE
    # ---------------------------------------------------
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": st.session_state.answer
    }

    st.session_state.messages.append(assistant_msg)

    logger.info(f"[ASSISTANT][{assistant_msg['id']}] {st.session_state.answer}")

    with st.chat_message("assistant"):
        st.write(st.session_state.answer)


# ---------------------------------------------------
# 🔥 UI RENDER (ALWAYS FROM SESSION STATE)
# ---------------------------------------------------
structured = st.session_state.get("structured", [])
answer = st.session_state.get("answer", "")

if structured:
    df = pd.DataFrame(structured)
    df = df.sort_values("hour")

    st.divider()

    # 📊 Chart
    st.subheader("📊 Solar Production Curve")
    st.line_chart(df.set_index("hour"))

    # 📋 Table
    st.subheader("📋 Hourly Data in MW")
    st.dataframe(df, use_container_width=True)

    # 📥 Download
    csv = df.to_csv(index=False)

    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name="solar_forecast.csv",
        mime="text/csv"
    )

    # 📈 Analytics
    st.subheader("📈 Quick Analytics")

    peak_value = df["production_mw"].max()
    peak_hour = df.loc[df["production_mw"].idxmax(), "hour"]
    total_energy = df["production_mw"].sum()
    active_hours = (df["production_mw"] > 0).sum()

    col1, col2, col3 = st.columns(3)

    col1.metric("Peak Output", f"{peak_value:.2f} MW")
    col2.metric("Peak Hour", f"{peak_hour}:00")
    col3.metric("Active Hours", active_hours)

    st.write(f"Total Daily Generation: **{total_energy:,.0f} MWh (approx)**")