import streamlit as st
import requests
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import uuid
import json

# ---------------------------------------------------
# 🔥 LOGGING SETUP
# ---------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------
# 🔥 FIX: propagate=False so Streamlit's internal root
#    logger doesn't also emit our records, which was
#    causing every line to appear twice in the console.
# ---------------------------------------------------
logger.propagate = False

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

API_URL = "http://backend:8000/chat/stream"

# ---------------------------------------------------
# 🔥 SESSION STATE
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
        st.markdown(msg["content"])

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
        st.markdown(user_input)

    # ---------------------------------------------------
    # 🔥 STREAMING RESPONSE
    # ---------------------------------------------------
    with st.chat_message("assistant"):

        status_placeholder = st.empty()
        response_placeholder = st.empty()

        full_text = ""
        structured_data = []

        try:
            logger.info(f"[STREAM_REQUEST][{user_msg['id']}] Sending query")
            start_time = time.time()

            response = requests.post(
                API_URL,
                json={"query": user_input, "message_id": user_msg["id"]},
                stream=True,
                timeout=120
            )

            response.raise_for_status()

            # -------------------------------------------------------
            # 🔥 TOKEN ACCUMULATION STRATEGY
            #
            # The LLM emits markdown headings split across tokens:
            #   token 1 → "###"
            #   token 2 → " Summary\nSolar production..."
            #
            # We must NOT flush "###" to full_text until we have the
            # rest of that line. Strategy:
            #   - Maintain a `pending` buffer for the current line.
            #   - Only move a line from pending → full_text when we
            #     receive the \n that terminates it.
            #   - Re-render every N completed lines to avoid flicker.
            # -------------------------------------------------------
            pending = ""        # current incomplete line
            render_counter = 0

            for raw_line in response.iter_lines():

                if not raw_line:
                    # Blank SSE separator — flush pending as a blank
                    # line so paragraph breaks are preserved.
                    if pending:
                        full_text += pending + "\n"
                        pending = ""
                        render_counter += 1
                        if render_counter % 4 == 0:
                            response_placeholder.markdown(full_text + "▌")
                    continue

                decoded = raw_line.decode("utf-8")

                if not decoded.startswith("data: "):
                    continue

                content = decoded[6:]   # strip "data: " prefix

                # — Control tokens —
                if content == "[START]":
                    status_placeholder.markdown("⏳ Processing your request...")
                    continue

                if content == "[END]":
                    status_placeholder.empty()
                    continue

                if content.startswith("{"):
                    try:
                        meta = json.loads(content)
                        if meta.get("type") == "meta":
                            structured_data = meta.get("structured", [])
                    except json.JSONDecodeError:
                        pass
                    continue

                # -------------------------------------------------------
                # 🔥 FIX 1 — Line-aware accumulation.
                #
                # Split the incoming token on \n. Each \n signals that
                # a line is complete and safe to commit to full_text.
                # The final segment (after the last \n, possibly empty)
                # stays in `pending` because its line isn't done yet.
                #
                # Example flow:
                #   token "###"           → pending="###"         (no flush)
                #   token " Summary\n..." → flushes "### Summary" then continues
                # -------------------------------------------------------
                if "\n" in content:
                    parts = content.split("\n")

                    # First part closes the current pending line
                    completed_line = pending + parts[0]
                    full_text += completed_line + "\n"
                    pending = ""
                    render_counter += 1

                    # Middle parts are complete lines on their own
                    for part in parts[1:-1]:
                        full_text += part + "\n"
                        render_counter += 1

                    # Last part starts a new incomplete line
                    pending = parts[-1]

                    if render_counter % 4 == 0:
                        response_placeholder.markdown(full_text + "▌")

                else:
                    # No newline yet — just accumulate into pending
                    pending += content

            # Flush any remaining pending content
            if pending:
                full_text += pending

            # Final render without cursor
            response_placeholder.markdown(full_text)

            latency = time.time() - start_time
            logger.info(f"[STREAM_LATENCY][{user_msg['id']}] {latency:.2f}s")

            st.session_state.answer = full_text
            st.session_state.structured = structured_data

        except requests.Timeout:
            logger.error(f"[TIMEOUT][{user_msg['id']}]")
            st.session_state.answer = "Request timed out."

        except requests.RequestException as e:
            logger.error(f"[REQUEST_ERROR][{user_msg['id']}] {str(e)}")
            st.session_state.answer = f"Error: {str(e)}"

    # ---------------------------------------------------
    # 🔥 SAVE MESSAGE
    # ---------------------------------------------------
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": st.session_state.answer
    }

    st.session_state.messages.append(assistant_msg)

    logger.info(f"[ASSISTANT][{assistant_msg['id']}] Saved response")

# ---------------------------------------------------
# 🔥 ANALYTICS UI
# ---------------------------------------------------
structured = st.session_state.get("structured", [])

if structured:
    df = pd.DataFrame(structured).sort_values("hour")

    st.divider()

    st.subheader("📊 Solar Production Curve")
    st.line_chart(df.set_index("hour"))

    st.subheader("📋 Hourly Data in MW")
    st.dataframe(df, width="stretch")

    csv = df.to_csv(index=False)

    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name="solar_forecast.csv",
        mime="text/csv"
    )

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