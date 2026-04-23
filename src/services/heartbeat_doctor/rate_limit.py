import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

class AutoHealRateLimiter:
    WINDOW = timedelta(minutes=int(os.getenv("DOCTOR_RATE_LIMIT_WINDOW_MINUTES", "10")))
    MAX_HEALS = int(os.getenv("DOCTOR_RATE_LIMIT_MAX_HEALS", "3"))

    def __init__(self):
        self._history: dict[str, list[datetime]] = defaultdict(list)

    async def exceeded(self, agent_id: str) -> bool:
        now = datetime.now(timezone.utc)
        # Limpar histórico antigo
        self._history[agent_id] = [
            t for t in self._history[agent_id] if now - t < self.WINDOW
        ]
        return len(self._history[agent_id]) >= self.MAX_HEALS

    async def record(self, agent_id: str) -> None:
        self._history[agent_id].append(datetime.now(timezone.utc))

rate_limiter = AutoHealRateLimiter()
