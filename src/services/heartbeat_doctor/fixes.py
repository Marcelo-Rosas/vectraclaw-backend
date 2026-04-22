from enum import Enum
from .symptoms import Symptom

class Fix(str, Enum):
    RESET_HB_LOOP       = "reset_hb_loop"        # F1
    CLEAR_CONTEXT_CACHE = "clear_context_cache"  # F2
    REGEN_JWT           = "regen_jwt"            # F3
    SKIP_TASK           = "skip_task"            # F4
    RESTART_ADAPTER     = "restart_adapter"      # F5
    DETECT_ONLY         = "detect_only"          # F6

SYMPTOM_TO_FIX: dict[Symptom, list[Fix]] = {
    Symptom.HEARTBEAT_GAP:        [Fix.RESET_HB_LOOP, Fix.RESTART_ADAPTER],
    Symptom.TASK_CLAIM_STALE:     [Fix.SKIP_TASK],
    Symptom.JWT_EXPIRED:          [Fix.REGEN_JWT],
    Symptom.ADAPTER_UNRESPONSIVE: [Fix.CLEAR_CONTEXT_CACHE, Fix.RESTART_ADAPTER],
    Symptom.BURN_RATE_ANOMALY:    [Fix.DETECT_ONLY],
    Symptom.UNKNOWN_SENTINEL:     [Fix.DETECT_ONLY],
}
