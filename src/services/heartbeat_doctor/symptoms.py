from enum import Enum # Pydantic v1 prefere Enum ou StrEnum
from datetime import datetime, timedelta, timezone
from typing import Optional

class Symptom(str, Enum):
    HEARTBEAT_GAP       = "heartbeat_gap"        # S1
    TASK_CLAIM_STALE    = "task_claim_stale"     # S2
    JWT_EXPIRED         = "jwt_expired"          # S3
    ADAPTER_UNRESPONSIVE = "adapter_unresponsive" # S4
    BURN_RATE_ANOMALY   = "burn_rate_anomaly"    # S5
    UNKNOWN_SENTINEL    = "unknown_sentinel"     # S6

# Thresholds V1
HB_GAP_THRESHOLD       = timedelta(seconds=60)
TASK_STALE_THRESHOLD   = timedelta(minutes=5)
SENTINEL_THRESHOLD     = timedelta(minutes=15)
BURN_RATE_HARD_CAP_MULT = 2.0
