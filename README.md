# data-science-ai
# ⚡ MCP-Based Energy AI Agent

An intelligent energy analysis agent built using **Model Context Protocol (MCP)** with:
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

- Forecast solar energy production
- Analyze weather impact on solar output
- Combine multiple data sources intelligently
- Dynamically decide which tools to use
- Self-correct wrong decisions

---

# 🧠 Core Architecture

User Query
   ↓
Planner (LLM)
   ↓
Execution Loop
   ↓
Sanitization Layer (critical)
   ↓
MCP Tool Execution
   ↓
Evaluator (LLM + rules)
   ↓
Final Reasoning (LLM)
   ↓
Context Injection Layer (Spain constraint)
   ↓
Final Response


---

# 🧩 System Components

## 1. Planner (`agent/planner.py`)

**Responsibility:**
- Understand user query
- Select optimal tools
- Generate execution plan

## 2. MCP Layer

    . MCP Client
        - Sends tool execution request
        - Receives structured response
    . MCP Server (mcp_v2/server.py)
        - Registers tools
        - Executes business logic

## Argument Sanitization Layer (NEW)
LLM may generate invalid arguments based on the user query- since this system is designed on Spain data
User will get the prompt even if user enquire abotu the other location. That why before calling this layer
sanitize the input to the tools.

## 3. Tools (MCP)
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


## 4.  Final Reasoning (LLM)

After execution completes:

    -Interprets tool outputs
    -Generates human-readable explanation
    -Applies domain reasoning
## 5. 🧠 Key Design Principles
    | Component | Responsibility  |
    | --------- | --------------- |
    | Planner   | What to do      |
    | MCP       | Execute tools   |
    | Evaluator | Control flow    |
    | LLM       | Explain results |

## 6. Self-Correcting System
Wrong plan → evaluator detects → replan → continue

## 7. 🔥 Key Features
✅ MCP-native tool execution
✅ Multi-tool reasoning
✅ Weather-aware solar forecasting
✅ Self-correcting agent loop
✅ JSON-safe serialization
✅ Production-ready architecture

## 8. 🧠 Future Improvements
API layer (FastAPI)
UI integration

## 9. API Architecture Flow
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

    G --> H[Evaluator]

    H -->|continue| C
    H -->|replan| B
    H -->|stop| I[Final LLM Response]

    I --> J[User Output]
```

## Dockerization (NEW)
The agent is fully containerized.

## Note
This project may contain some extra files as it is the outcome of a transition from an MCP implementation in Python to using readily available FastMCP libraries. For better understanding of the files included in the project scope, please refer to the imports used in the code. Some of them are mentioned below:
- mcp_core: This folder is not used in the current project scope.
- tools: This folder has not been used in the project so far, but it has been retained for future scope.
- services: This folder contains an unused file named data_loader.py, which can be utilized for future enhancements.
- models: This folder contains multiple subfolders named after different model algorithms tested for solar energy forecasting (Spain). However, within the project scope, only the UnobservedComponentModel has been used, located inside models/energy/solar_forecast. The objective of this project is to develop an agent prototype that integrates MCP with the energy forecast model.
- test: Completely unused folder as of now.
- data: Reserved for future scope.

