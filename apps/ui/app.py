import streamlit as st
import requests
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import uuid
import json

st.set_option("client.showErrorDetails", False)


# ---------------------------------------------------
# 🔥 LOGGING SETUP
# ---------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

logger.propagate = False

if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler = RotatingFileHandler(
        "app.log", maxBytes=5 * 1024 * 1024, backupCount=3
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

# Re-render at most every 100ms — imperceptible to users,
# cuts browser re-renders from ~200 to ~10-15 per response.
RENDER_INTERVAL = 0.1


# ---------------------------------------------------
# 🔥 SESSION STATE INITIALIZATION
# ---------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# Structured data keyed by assistant message_id.
# Never wiped — each query's analytics persist independently.
if "structured_per_message" not in st.session_state:
    st.session_state.structured_per_message = {}

if "answer" not in st.session_state:
    st.session_state.answer = ""


# ---------------------------------------------------
# 🔥 ANALYTICS HELPERS
# ---------------------------------------------------
def render_chart(df, cols: list, title: str):
    """Render st.line_chart for only the columns that exist in df."""
    valid = [c for c in cols if c in df.columns]
    if not valid:
        return
    st.subheader(f"📊 {title}")
    st.line_chart(df[["hour"] + valid].set_index("hour"))


def render_quick_analytics(df, value_col, value_label):
    """Generic metric block for any numeric column."""
    if value_col not in df.columns or df[value_col].isna().all():
        return
    peak_value = df[value_col].max()
    peak_hour = int(df.loc[df[value_col].idxmax(), "hour"])
    avg_value = df[value_col].mean()
    active_hours = int((df[value_col] > 0).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Peak {value_label}", f"{peak_value:.2f}")
    c2.metric("Peak Hour", f"{peak_hour:02d}:00")
    c3.metric(
        (
            "Active Hours"
            if ("mw" in value_col.lower() or "kwh" in value_col.lower())
            else "Hours Recorded"
        ),
        active_hours,
    )
    st.write(f"Daily Average **{value_label}**: **{avg_value:.2f}**")


def render_analytics(structured: dict, msg_id: str):
    """
    Render table + charts + quick analytics for one query response.
    msg_id is used to generate unique Streamlit widget keys so
    multiple analytics blocks can coexist on the same page.
    """
    if isinstance(structured, list):
        return

    energy_data = structured.get("energy", [])
    weather_data = structured.get("weather", [])
    adjusted_data = structured.get("adjusted", [])

    has_energy = bool(energy_data)
    has_weather = bool(weather_data)
    has_adjusted = bool(adjusted_data)

    if not (has_energy or has_weather or has_adjusted):
        return  # conversational query — show nothing

    # Detect scenario
    if has_energy and has_weather and has_adjusted:
        scenario = "combined"
    elif has_energy or has_adjusted:
        scenario = "solar"
    else:
        scenario = "weather"

    # Short key safe for Streamlit widget keys (buttons only)
    k = msg_id.replace("-", "")[:12]

    # ---------------------------------------------------
    # 🔥 HELPER: Normalize energy column names to MWh
    # Handles all variants the backend might return:
    #   production_mw  → energy_mwh
    #   energy_mw      → energy_mwh
    #   adjusted_kwh   → adjusted_mwh
    #   adjusted_mw    → adjusted_mwh
    # If both adjusted variants exist after a merge, drop the duplicate.
    # ---------------------------------------------------
    def normalize_units(df):
        # Energy column
        for old in ["production_mw", "energy_mw"]:
            if old in df.columns:
                df = df.rename(columns={old: "energy_mwh"})
                break

        # Adjusted column — rename whichever exists first
        for old in ["adjusted_kwh", "adjusted_mw"]:
            if old in df.columns:
                if "adjusted_mwh" not in df.columns:
                    df = df.rename(columns={old: "adjusted_mwh"})
                else:
                    df = df.drop(columns=[old])  # drop duplicate
                break

        return df

    # -------------------------------------------------------
    # SCENARIO 1: WEATHER ONLY
    # -------------------------------------------------------
    if scenario == "weather":
        try:
            df = pd.DataFrame(weather_data).sort_values("hour").reset_index(drop=True)

            st.subheader("📋 Hourly Weather Forecast")
            st.dataframe(df)
            st.download_button(
                label="📥 Download CSV",
                data=df.to_csv(index=False),
                file_name="weather_forecast.csv",
                mime="text/csv",
                key=f"dl_weather_{k}",
            )

            render_chart(
                df,
                cols=["temperature", "avg_temperature", "avg_cloud_cover"],
                title="Hourly Temperature & Cloud Cover",
            )

            st.subheader("📈 Quick Analytics")
            render_quick_analytics(df, "temperature", "Temperature (°C)")
            if "avg_cloud_cover" in df.columns:
                st.write(
                    f"Average Cloud Cover: **{df['avg_cloud_cover'].iloc[0]:.1f}%**"
                )
            if "avg_temperature" in df.columns:
                st.write(
                    f"Average Temperature: **{df['avg_temperature'].iloc[0]:.1f}°C**"
                )

        except Exception as e:
            logger.error(f"[UI_ERROR][weather][{k}] {str(e)}")

    # -------------------------------------------------------
    # SCENARIO 2: SOLAR / ENERGY ONLY
    # -------------------------------------------------------
    elif scenario == "solar":
        try:
            df_e = (
                pd.DataFrame(energy_data).sort_values("hour").reset_index(drop=True)
                if has_energy
                else pd.DataFrame()
            )
            df_a = (
                pd.DataFrame(adjusted_data).sort_values("hour").reset_index(drop=True)
                if has_adjusted
                else pd.DataFrame()
            )

            if not df_e.empty and not df_a.empty:
                adj_cols = ["hour"] + [c for c in df_a.columns if c != "hour"]
                df = df_e.merge(df_a[adj_cols], on="hour", how="outer").sort_values(
                    "hour"
                )
            elif not df_e.empty:
                df = df_e.copy()
            else:
                df = df_a.copy()

            # 🔥 Normalize all energy columns to MWh
            df = normalize_units(df)
            df = df.sort_values("hour").reset_index(drop=True)

            st.subheader("📋 Hourly Solar Forecast")
            st.dataframe(df)
            st.download_button(
                label="📥 Download CSV",
                data=df.to_csv(index=False),
                file_name="solar_forecast.csv",
                mime="text/csv",
                key=f"dl_solar_{k}",
            )

            render_chart(
                df,
                cols=["energy_mwh", "adjusted_mwh"],
                title="Solar Production Curve (MWh)",
            )

            st.subheader("📈 Quick Analytics")
            primary_col = next(
                (c for c in ["energy_mwh", "adjusted_mwh"] if c in df.columns),
                None,
            )
            if primary_col:
                render_quick_analytics(df, primary_col, "Solar Output (MWh)")
                st.write(
                    f"Total Daily Generation: **{df[primary_col].sum():,.0f} MWh (approx)**"
                )

            for stat_col, label, unit in [
                ("adjusted_total_kwh", "Adjusted Total Energy", "kWh"),
                ("base_total_kwh", "Base Total Energy", "kWh"),
                ("adjustment_factor", "Weather Adjustment Factor", ""),
                ("cloud_cover", "Cloud Cover", "%"),
            ]:
                if stat_col in df.columns:
                    val = df[stat_col].iloc[0]
                    unit_str = f" {unit}" if unit else ""
                    st.write(f"**{label}**: {val:,.2f}{unit_str}")

        except Exception as e:
            logger.error(f"[UI_ERROR][solar][{k}] {str(e)}")

    # -------------------------------------------------------
    # SCENARIO 3: COMBINED (weather + solar + adjusted)
    # Two charts: energy scale (MWh) and weather scale (°C/%)
    # are completely different — render separately.
    # -------------------------------------------------------
    elif scenario == "combined":
        try:
            df_e = pd.DataFrame(energy_data).sort_values("hour").reset_index(drop=True)
            df_w = pd.DataFrame(weather_data).sort_values("hour").reset_index(drop=True)
            df_a = (
                pd.DataFrame(adjusted_data).sort_values("hour").reset_index(drop=True)
            )

            weather_keep = [
                c
                for c in ["hour", "temperature", "avg_cloud_cover", "avg_temperature"]
                if c in df_w.columns
            ]
            adj_keep = list(df_a.columns)

            df = df_e.merge(df_w[weather_keep], on="hour", how="outer")
            df = df.merge(df_a[adj_keep], on="hour", how="outer")

            # 🔥 Normalize all energy columns to MWh
            df = normalize_units(df)
            df = df.sort_values("hour").reset_index(drop=True)

            st.subheader("📋 Combined Hourly Forecast")
            st.dataframe(df)
            st.download_button(
                label="📥 Download CSV",
                data=df.to_csv(index=False),
                file_name="combined_forecast.csv",
                mime="text/csv",
                key=f"dl_combined_{k}",
            )

            # Chart 1: Solar vs Adjusted — same MWh scale, valid comparison
            render_chart(
                df,
                cols=["energy_mwh", "adjusted_mwh"],
                title="☀️ Solar Forecast vs Weather-Adjusted Forecast (MWh)",
            )

            # Chart 2: Weather — separate scale (°C / %)
            render_chart(
                df,
                cols=["temperature", "avg_temperature", "avg_cloud_cover"],
                title="🌡️ Weather Conditions (Temperature & Cloud Cover)",
            )

            st.subheader("📈 Quick Analytics")
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**☀️ Solar**")
                primary_col = next(
                    (c for c in ["energy_mwh", "adjusted_mwh"] if c in df.columns),
                    None,
                )
                if primary_col:
                    render_quick_analytics(df, primary_col, "Solar Output (MWh)")
                    st.write(f"Total: **{df[primary_col].sum():,.0f} MWh (approx)**")

            with col2:
                st.markdown("**🌡️ Weather**")
                render_quick_analytics(df, "temperature", "Temperature (°C)")
                if "avg_cloud_cover" in df.columns:
                    st.write(
                        f"Avg Cloud Cover: **{df['avg_cloud_cover'].iloc[0]:.1f}%**"
                    )

            # Weather impact delta — energy lost/gained due to weather
            if "energy_mwh" in df.columns and "adjusted_mwh" in df.columns:
                diff = df["energy_mwh"].sum() - df["adjusted_mwh"].sum()
                st.write(
                    f"Weather Impact: **{abs(diff):,.0f} MWh {'lost' if diff > 0 else 'gained'}** "
                    f"due to cloud cover / temperature effects."
                )

            for stat_col, label, unit in [
                ("adjusted_total_kwh", "Adjusted Total Energy", "kWh"),
                ("base_total_kwh", "Base Total Energy", "kWh"),
                ("adjustment_factor", "Weather Adjustment Factor", ""),
            ]:
                if stat_col in df.columns:
                    val = df[stat_col].iloc[0]
                    unit_str = f" {unit}" if unit else ""
                    st.write(f"**{label}**: {val:,.2f}{unit_str}")

        except Exception as e:
            logger.error(f"[UI_ERROR][combined][{k}] {str(e)}")


# ---------------------------------------------------
# 🔥 DISPLAY CHAT HISTORY + ANCHORED ANALYTICS
# Analytics are rendered here ONLY — never inline after
# streaming — so each chart renders exactly once per rerun
# with no duplicate widget conflicts.
# ---------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

    if msg["role"] == "assistant":
        msg_structured = st.session_state.structured_per_message.get(msg["id"])
        if msg_structured:
            render_analytics(msg_structured, msg["id"])


# ---------------------------------------------------
# 🔥 USER INPUT
# ---------------------------------------------------
user_input = st.chat_input("Ask your energy question...")

if user_input:
    user_msg = {"id": str(uuid.uuid4()), "role": "user", "content": user_input}

    logger.info(f"[USER][{user_msg['id']}] {user_input}")
    st.session_state.messages.append(user_msg)

    with st.chat_message("user"):
        st.markdown(user_input)

    # Allocate assistant ID upfront so we can anchor
    # structured data to it after streaming ends.
    assistant_id = str(uuid.uuid4())

    # ---------------------------------------------------
    # 🔥 STREAMING RESPONSE
    # ---------------------------------------------------
    with st.chat_message("assistant"):

        status_placeholder = st.empty()
        response_placeholder = st.empty()

        full_text = ""
        structured_data = {}

        try:
            logger.info(f"[STREAM_REQUEST][{user_msg['id']}] Sending query")
            start_time = time.time()

            response = requests.post(
                API_URL,
                json={"query": user_input, "message_id": user_msg["id"]},
                stream=True,
                timeout=120,
            )

            response.raise_for_status()

            pending = ""
            last_render = time.time()

            for raw_line in response.iter_lines():

                if not raw_line:
                    if pending:
                        full_text += pending + "\n"
                        pending = ""
                        now = time.time()
                        if now - last_render >= RENDER_INTERVAL:
                            response_placeholder.markdown(full_text + "▌")
                            last_render = now
                    continue

                decoded = raw_line.decode("utf-8")

                if not decoded.startswith("data: "):
                    continue

                content = decoded[6:]

                if content == "[START]":
                    status_placeholder.markdown("⏳ Processing your request...")
                    continue

                if content == "[END]":
                    status_placeholder.empty()
                    continue

                # Meta / structured data frame
                if content.startswith("{"):
                    try:
                        meta = json.loads(content)
                        if meta.get("type") == "meta":
                            structured_data = meta.get("structured", {})
                            logger.info(
                                f"[META] keys={list(structured_data.keys())} "
                                f"energy={len(structured_data.get('energy', []))} "
                                f"weather={len(structured_data.get('weather', []))} "
                                f"adjusted={len(structured_data.get('adjusted', []))}"
                            )
                    except json.JSONDecodeError:
                        pass
                    continue

                # Line-aware token accumulation
                if "\n" in content:
                    parts = content.split("\n")
                    full_text += pending + parts[0] + "\n"
                    pending = ""
                    for part in parts[1:-1]:
                        full_text += part + "\n"
                    pending = parts[-1]
                else:
                    pending += content

                # Time-based render gate — at most once per RENDER_INTERVAL
                now = time.time()
                if now - last_render >= RENDER_INTERVAL:
                    response_placeholder.markdown(full_text + "▌")
                    last_render = now

            if pending:
                full_text += pending

            # Final render — no cursor
            response_placeholder.markdown(full_text)

            latency = time.time() - start_time
            logger.info(f"[STREAM_LATENCY][{user_msg['id']}] {latency:.2f}s")

            st.session_state.answer = full_text

        except requests.Timeout:
            logger.error(f"[TIMEOUT][{user_msg['id']}]")
            st.session_state.answer = "Request timed out."
            response_placeholder.markdown("⚠️ Request timed out. Please try again.")

        except requests.RequestException as e:
            logger.error(f"[REQUEST_ERROR][{user_msg['id']}] {str(e)}")
            st.session_state.answer = f"Error: {str(e)}"
            response_placeholder.markdown(f"⚠️ {str(e)}")

    # ---------------------------------------------------
    # 🔥 SAVE ASSISTANT MESSAGE + STRUCTURED DATA
    # Then trigger a rerun so the history loop above
    # renders the analytics cleanly in one pass.
    # ---------------------------------------------------
    assistant_msg = {
        "id": assistant_id,
        "role": "assistant",
        "content": st.session_state.answer,
    }
    st.session_state.messages.append(assistant_msg)

    if structured_data:
        st.session_state.structured_per_message[assistant_id] = structured_data

    logger.info(f"[ASSISTANT][{assistant_id}] Saved response")

    # 🔥 Rerun so the history loop renders analytics cleanly.
    # This is the key fix — analytics render exactly once via
    # the history loop, never duplicated inline during streaming.
    st.rerun()
