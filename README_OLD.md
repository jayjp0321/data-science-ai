# data-science-ai
# ⚡ MCP-Based Energy AI Agent

An intelligent energy analysis agent backed by ML-Model, built using **Model Context Protocol (MCP)** :
This release introduces a production-grade MCP-native hybrid agent architecture with:

✔ Planner-driven execution
✔ MCP-based tool orchestration
✔ Evaluator loop (self-correction)
✔ Argument sanitization layer
✔ Deterministic tool control
✔ Location constraint handling (Spain-only system)
✔ Dockerized deployment

---

# 🚀 Overview

This project implements a **multi-stage AI agent system** that can:

- Understands natural language queries
- Plans execution using an LLM-based planner
- Calls external tools (weather, energy, adjusted forecasts)
- Streams structured + analytical responses
- Visualizes insights in real-time
- Forecast weather (Spain)
- Forecast solar energy production 
- Analyze weather impact on solar output
- Combine multiple data sources intelligently
- Dynamically decide which tools to use
- Self-correct wrong decisions
- This system has been calibarated for spain

---

## Multi Container Dockerization (NEW)
- The agent is fully containerized.
- Two containers used:
   1. UI Container
   2. Backend Container

# 🧠 Docker Container level Architecture

+---------------------------+        +--------------------------------------+
|        UI CONTAINER       |        |        BACKEND CONTAINER             |
|---------------------------|        |--------------------------------------|
| Streamlit (app.py)        |        | FastAPI (main.py)                    |
|                           |        |                                      |
| - Chat UI                 | <----> | - API Endpoints                      |
| - Streaming Renderer      |  HTTP  | - Agent Orchestration                |
| - Charts & Analytics      |        | - MCP Client                         |
|                           |        |                                      |
+---------------------------+        |  ┌──────────────────────────────┐    |
                                     |  │         AGENT LAYER          │    |
                                     |  │ (agent/ - planner, memory)   │    |
                                     |  └──────────────┬───────────────┘    |
                                     |                 │                    |
                                     |  ┌──────────────▼───────────────┐    |
                                     |  │       SERVICE LAYER          │    |
                                     |  │ (services/)                  │    |
                                     |  │ - forecast_service           │    |
                                     |  │ - weather_service            │    |
                                     |  │ - solar_adjustment_service   │    |
                                     |  └──────────────┬───────────────┘    |
                                     |                 │                    |
                                     |  ┌──────────────▼───────────────┐    |
                                     |  │        MODEL LAYER           │    |
                                     |  │ (models/)                    │    |
                                     |  │ - baseline                   │    |
                                     |  │ - energy                     │    |
                                     |  │ - nhits                      │    |
                                     |  │ - tcn                        │    |
                                     |  └──────────────┬───────────────┘    |
                                     |                 │                    |
                                     |  ┌──────────────▼───────────────┐    |
                                     |  │        DATA LAYER            │    |
                                     |  │ (data/, loaders)             │    |
                                     |  └──────────────────────────────┘    |
                                     |                                      |
                                     +------------------+-------------------+
                                                        |
                                                        | STDIO (MCP)
                                                        ▼
                                           +-----------------------------+
                                           |      MCP SERVER             |
                                           |-----------------------------|
                                           | mcp_v2.server               |
                                           |                             |
                                           | Tools:                      |
                                           | - Weather Forecast          |
                                           | - Energy Forecast           |
                                           | - Adjusted Forecast         |
                                           +-----------------------------+


---

# 🧩 System Components

## Agent Layer
   Core Orchestration layer coordinates Planner + Tools + LLM

## 1. Planner (LLM Planning Engine)

**Responsibility:**
- Understand user query
- Select optimal tools
- Generate execution plan

## 2. MCP Flow/Layer with Core Achitectural Flow

                                          User Query
                                             ↓
                                          Agent (Planner + Executor + Evaluator/Self Correction)
                                             ↓
                                          MCP Client (Consumes Tool)
                                             ↓
                                          MCP Server (Exposes Tool)
                                             ↓
                                          Service Layer 
                                             ↓
                                          Model Layer (Pre-built ML Models)
                                             ↓
                                          Data Layer
                                             ↓
                                          Response → Agent → UI(Streamlit UI)

    . MCP Client
        - Sends tool execution request
        - Receives structured response
    . MCP Server (mcp_v2/server.py)
        - Registers tools
        - Executes business logic

## 3. Conversation Memory (Basic)
   - Stores User + Assistant messages (To render UI at session level for every user query)
   - Not used in reasoning
   - Not used in planner
   - Not used in prompts

## 4. Self-Correcting System
Wrong plan → evaluator detects → replan → continue

## 5. Tools (MCP)
🌤️ get_weather_forecast_tool
        -Fetches weather data from Open-Meteo API
⚡ get_energy_forecast_tool
        -Uses ML model (UnobservedComponents)
        -Predicts solar production
🔥 get_adjusted_forecast_tool
        . Combines:
            -weather
            -solar forecast
        . Applies adjustment logic
        . Returns final production


## 6. Final Reasoning (LLM)

After execution completes:

    -Interprets tool outputs
    -Generates human-readable explanation
    -Applies domain reasoning

## 7. ML-Model/s

Machine learning pre-build model(.pkl file) to be used for grid solar production forecast for Spain.

## 8. Streaming communication layer (New)
   - Potocol: SSE( Server-sent events)
   - LLM Level streaming ( Backend --> Streamlit UI)
   - Behavior
      . Token streaming
      . Event framing (data:)
      . Meta payload for analytics

## 9. Logging System
- Backend:
   . Root logger
   . Rotating file handler (api.log)
   . Propagation control
- UI:
   . File + console logging (app.log)

## 10. Dockerized Setup. 

      +------------------------------------------+
      | Container | Contents                     |
      | --------- | ---------------------------- |
      | UI        | Streamlit app                |
      | Backend   | FastAPI + Agent + MCP client |
      +------------------------------------------+
    
##  🧠 Key Design Principles
    +----------------------------------------+
    | Component        | Responsibility      |
    ------------------------------------------
    | Planner          | What to do          |
    | MCP              | Execute tools       |
    | Evaluator        | Control flow        |
    | LLM              | Explain results     |
    | Memory           | UI Memory(Session)  |
    +----------------------------------------+

## 🔑 Engineering Decisions
✅ SSE over WebSockets
   - Simpler infra
   - Reliable streaming
   - Works with HTTP stack
✅ MCP-based Tooling
   - Clean separation of concerns
   - Scalable tool ecosystem
✅ Structured Extraction
   - Deterministic UI rendering
   - No LLM dependency for charts
✅ Logging Design
   - Rotating logs
   - No duplicate logs

## 🔥 Key Features
✅ MCP-native tool execution
✅ Multi-tool reasoning
✅ Weather-aware solar forecasting
✅ Self-correcting agent loop
✅ JSON-safe serialization
✅ SSE Streaming (Agent Engine Level- Unidirectional LLM Streaming Tokenwise LLM-->UI)
✅ MCP client lifecycle management
✅ Multi container (Docker) communication
✅ Strucured data pipeline (Tool Response) used for Charts,Tables,Metrics & CSV Export
✅ Production-ready architecture


##  API Architecture Flow

```mermaid
flowchart TD

    A[User Query] --> B[Planner LLM]

    B --> C[Execution Loop]

    C --> D[MCP Client]
    D --> E[MCP Server]
    E --> F[Tools Layer]

    F --> F1[get_weather_forecast_tool]
    F --> F2[get_energy_forecast_tool]
    F --> F3[get_adjusted_forecast_tool]

    F --> G[Tool Result]

    G --> H[Evaluator LLM]

    H -->|continue| C
    H -->|replan| B
    H -->|stop| I[Final LLM Response]

    I --> J[User Output]
```


## 🧠 Future Roadmap

   🔹 1. Tool Memory Layer:
         - Cache tool outputs
         - Reuse across queries
   🔹 2. Memory-Aware Planning:
         - Planner agent is aware of previous tool call/s output uses for the next queries
           during the session context/browser context
         - Minimize tool call
         - No MCP Call (Faster response)
         - Cost: Fewer LLM + Toll Token
         Current Behaviour:
            User: solar forecast tomorrow
               → tool called ✅

            User: what is peak production?
               → tool called AGAIN ❌ (wasteful)
   🔹 3. Smart Context Injection:
         - Summarized memory
         - Reduced token usage
   🔹 4. Multi-Turn Reasoning
         - Context-aware follow-ups
         - Cross-query intelligence

## 📁 Project Structure

            DATA-SCIENCE-AI/
            │
            ├── agent/
            │   ├── agent.py
            │   ├── memory.py
            │   └── planner.py
            │
            ├── apps/
            │   ├── api/
            │   │   └── main.py
            │   └── ui/
            │       └── app.py
            │
            ├── mcp_core/
            ├── mcp_v2/
            ├── services/
            ├── models/
            │
            ├── docker-compose.yml
            ├── requirements.txt
            └── README.md

## 🔑 Final Summary

Your current system consists of:

   - Frontend layer → Streamlit UI + analytics
   - API layer → FastAPI + SSE streaming
   - Agent layer → planning + execution
   - Tool layer (MCP) → externalized computation
   - Service layer → domain logic
   - Model layer → ML forecasting
   - Data pipeline → structured outputs for UI

📌 Note

   ⚠️ This project is designed as a tool-augmented AI agent system, not a traditional chatbot.

   - The system relies on LLM-based planning + external tool execution (via MCP) rather than static responses.
   - All analytics (charts, tables, metrics) are generated from structured tool outputs, not directly from the LLM.
   - The UI maintains session-level state for visualization, but the backend agent currently operates independently per request.
   - Streaming responses are implemented using Server-Sent Events (SSE) for real-time token delivery.
   - The architecture follows a layered design:
      . Agent (reasoning)
      . MCP (tool execution)
      . Services (business logic)
      . Models (ML inference)


   ⚠️ This project may contain some extra files as it is the outcome of a transition from an MCP implementation in Python to using readily available FastMCP libraries. For better understanding of the files included in the project scope, please refer to the imports used in the code. Some of them are mentioned below:
   - mcp_core: This folder is not used in the current project scope.
   - tools: This folder has not been used in the project so far, but it has been retained for future scope.
   - services: This folder contains an unused file named data_loader.py, which can be utilized for future enhancements.
   - models: This folder contains multiple subfolders named after different model algorithms tested for solar energy forecasting (Spain). However, within the project scope, only the UnobservedComponentModel has been used, located inside models/energy/solar_forecast. The objective of this project is to develop an agent prototype that integrates MCP with the energy forecast model.
   - test: Completely unused folder as of now.
   - data: Reserved for future scope.

