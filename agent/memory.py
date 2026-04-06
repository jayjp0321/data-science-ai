from datetime import datetime
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------
# 🔹 Conversation Memory (chat history)
# ---------------------------------------------------
class ConversationMemory:
    def __init__(self, max_messages: int):
        self.messages = []
        self.max_messages = max_messages

    def add(self, role: str, content: str):
        self.messages.append(
            {"role": role, "content": content, "timestamp": datetime.now()}
        )
        self._trim()

    def _trim(self):
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def get(self):
        return self.messages

    def get_recent(self, n=5):
        return self.messages[-n:]

    def get_recent(self, n=5):
        return self.messages[-n:]

    def get_user_messages(self):
        return [m for m in self.messages if m["role"] == "user"]


# ---------------------------------------------------
# 🔹 Structured Memory (tool outputs)
# ---------------------------------------------------
class StructuredMemory:
    def __init__(self):
        self._store: dict = {}

    # ---------------------------------------------------
    # Store
    # ---------------------------------------------------
    def store(self, tool_name: str, date: str, output: dict) -> None:
        key = (tool_name, date)

        self._store[key] = {
            "text": output.get("text") or "",
            "structured": output.get("structured") or [],
            "stored_at": datetime.now(),
        }

        logger.info(f"[MEMORY][STORE] {tool_name} | date={date}")

    # ---------------------------------------------------
    # Direct Lookup (exact match)
    # ---------------------------------------------------
    def lookup(self, tool_name: str, date: str) -> dict | None:
        return self._store.get((tool_name, date))

    def has(self, tool_name: str, date: str) -> bool:
        return (tool_name, date) in self._store

    # ---------------------------------------------------
    # Query Helpers
    # ---------------------------------------------------
    def get_all_for_date(self, date: str) -> dict:
        return {tool: data for (tool, d), data in self._store.items() if d == date}

    def get_latest(self):
        """
        Returns:
        (tool, date, data)
        """
        if not self._store:
            return None

        (tool, date), data = max(
            self._store.items(),
            key=lambda x: x[1]["stored_at"],
        )

        return (tool, date, data)

    def get_latest_for_tool(self, tool_name: str):
        candidates = [
            (tool, date, data)
            for (tool, date), data in self._store.items()
            if tool == tool_name
        ]

        if not candidates:
            return None

        return max(candidates, key=lambda x: x[2]["stored_at"])

    # ---------------------------------------------------
    # 🔥 SEARCH (Memory-first resolution)
    # ---------------------------------------------------
    def search(self, query: str) -> list:
        """
        Returns list of:
        [(tool, date, data)]
        """
        q = query.lower()
        results = []

        for (tool, date), data in self._store.items():

            tool_clean = tool.replace("_tool", "")

            # Strong match: tool explicitly mentioned
            if tool_clean in q:
                results.append((tool, date, data))
                continue

            # Weak match: short query → use recency
            if len(q.split()) <= 6:
                results.append((tool, date, data))

        # 🔥 Sort by recency (important)
        results.sort(key=lambda x: x[2]["stored_at"], reverse=True)

        return results

    # ---------------------------------------------------
    # Utility
    # ---------------------------------------------------
    def keys(self) -> list:
        return list(self._store.keys())

    def clear(self) -> None:
        self._store.clear()
        logger.info("[MEMORY][CLEARED]")

    def summary(self) -> list:
        return [
            f"{tool}::{date} (stored {data['stored_at'].strftime('%H:%M:%S')})"
            for (tool, date), data in self._store.items()
        ]
