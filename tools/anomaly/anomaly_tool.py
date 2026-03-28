from mcp.schemas.tool_schema import Tool

def detect_anomaly(days: int):
    return {
        "days_checked": days,
        "anomaly_detected": True,
        "reason": "sudden irradiance drop"
    }

anomaly_tool = Tool(
    name="detect_anomaly",
    description="Detect anomalies in energy production",
    input_schema={"days": "int"},
    func=detect_anomaly
)