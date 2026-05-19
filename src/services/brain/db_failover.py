"""
DEPRECATED — shim de compatibilidade.

Este módulo foi movido pra `src/services/db_failover.py` em M2 do roadmap
de migração Brain → Daedalus (autopilot 2026-05-19, Caminho 3 W14).

Imports antigos continuam funcionando:
    from src.services.brain.db_failover import build_failover_result   # OK
    from src.services.brain.db_failover import with_db_failover        # OK (alias)
    from src.services.brain.db_failover import _CATEGORIES              # OK

Mas migração recomendada pra novos call-sites:
    from src.services.db_failover import build_failover_result, with_db_recovery

Este shim pode ser deletado no PR M5 (cleanup do Brain) quando todos os
4 imports atuais em src/api.py forem atualizados.
"""
from __future__ import annotations

import warnings

from src.services.db_failover import (  # noqa: F401 — re-export
    ErrorCategory,
    FailoverResult,
    _BY_PG_CODE,
    _BY_PGRST_CODE,
    _CATEGORIES,
    _NETWORK_KEYWORDS,
    _classify,
    build_failover_result,
    logger,
    with_db_recovery,
)

# Alias legacy nome antigo (`with_db_failover`) → novo (`with_db_recovery`)
with_db_failover = with_db_recovery

warnings.warn(
    "src.services.brain.db_failover é deprecado. "
    "Use src.services.db_failover em novos call-sites. "
    "Decorator `@with_db_failover` foi renomeado pra `@with_db_recovery` "
    "(alias legacy mantido).",
    DeprecationWarning,
    stacklevel=2,
)
