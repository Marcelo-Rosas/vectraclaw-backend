"""Single Source of Truth (SSOT) para AGENT_IDs do VectraClaw.

Os AGENT_IDs são UUIDs imutáveis — FK em `vectraclip.tasks.assigned_to_agent_id`
e identificam o processo daemon antes mesmo de tocar Supabase.

## Decisão arquitetural

IDs ficam em Python (não em tabela catalog) porque:
1. **Imutabilidade absoluta:** mudar um AGENT_ID quebra histórico de tasks (RLS/FK).
2. **Bootstrap independente de DB:** o daemon precisa de `AGENT_ID` para adquirir lock
   antes mesmo de o cliente Supabase estar pronto.
3. **Casos canônicos do P6 do CODE-PATTERNS.md** (decisões registradas, não omissões):
   identidade do processo, não config de negócio.

Mas DEVEM ter SSOT: declarações duplicadas em múltiplos arquivos foi a violação
que o `hardcode-orphan-auditor` flagou (achados N7+N8+N9 da auditoria 2026-05-17).
Antes desta consolidação havia 13 declarações espalhadas + 2 naming conflicts
(`HERMES_REPORTER_AGENT_ID` vs `HERMES_REPORTER_UUID`) + Oracle ID literal
inline em `task_factory.py:191`.

## Como usar

```python
from src.agent_ids import ORACLE_AGENT_ID, KRONOS_AGENT_ID

if task.get("assigned_to_agent_id") == ORACLE_AGENT_ID:
    ...
```

Nunca declare AGENT_ID localmente. Se faltar um aqui, adicione neste arquivo.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# Daemons "fixos" (UUIDs determinísticos 00000000-xxx)
# Convenção historica: agents que existem desde o bootstrap do sistema.
# ─────────────────────────────────────────────────────────────────────────────

MORPHEUS_AGENT_ID = "00000000-0000-0000-0000-000000000001"
"""Orquestrador. EXCLUDED_TYPES inclui route-cost-calculation."""

ORACLE_AGENT_ID = "00000000-0000-0000-0000-000000000002"
"""Oracle: oracle-research, SIPOC chat, fallback Deep Research."""

MNEMOS_AGENT_ID = "00000000-0000-0000-0000-000000000003"
"""Curador do corpus RAG global (rag-ingest)."""


# ─────────────────────────────────────────────────────────────────────────────
# Daemons com UUIDs aleatórios (gerados ad-hoc em momentos diferentes)
# ─────────────────────────────────────────────────────────────────────────────

HERMES_AGENT_ID = "59b7a69e-cc53-4063-85f9-5dcc5619ac96"
"""Hermes: polling IMAP + email_lead."""

MERCATOR_AGENT_ID = "c7de1b0f-7c74-42f1-9de4-7210349e668e"
"""Mercator: comercial / cotações."""

PLUTUS_AGENT_ID = "80fd6d0e-53ab-4638-b6e9-05cbbd121092"
"""Plutus: financeiro / CRM."""

HODOS_AGENT_ID = "0d6e56cc-28b6-4382-96cd-1952b890d412"
"""Hodos: QUALP / rotas."""

HERMES_REPORTER_AGENT_ID = "360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1"
"""HermesReporter: oracle-report (envio SMTP)."""

KRONOS_AGENT_ID = "9c8d7e6f-5a4b-4321-9876-543210fedcba"
"""Kronos: scrape-backlog, financial-audit, planner-*."""

ATHENA_AGENT_ID = "ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d"
"""Athena: PMBOK handlers (classify, charter, recommend, etc.)."""

DAEDALUS_AGENT_ID = "d4ed4145-0000-4000-8000-000000000005"
"""Daedalus: bpmn-modeling. Em retrofit (memory `agent-hiring-ritual`)."""

GYMSITE_AGENT_ID = "917e51b3-9413-4000-8000-000000000006"
"""GymSite: prospecção de academias (CNAE 9313-1/00). Nome técnico do produto,
sem persona mitológica. UUID v4 temático (gym) grepável. Registrado em
vectraclip.agents pelo seed 20260517250000_gymsite_seed.sql. operation_types:
gymsite-prospect-scan, gymsite-enrich-lead, gymsite-location-roi."""


# ─────────────────────────────────────────────────────────────────────────────
# Convenience map para iteração (ex: start_all_daemons, dashboards)
# ─────────────────────────────────────────────────────────────────────────────

ALL_AGENT_IDS = {
    "Morpheus": MORPHEUS_AGENT_ID,
    "Oracle": ORACLE_AGENT_ID,
    "Mnemos": MNEMOS_AGENT_ID,
    "Hermes": HERMES_AGENT_ID,
    "Mercator": MERCATOR_AGENT_ID,
    "Plutus": PLUTUS_AGENT_ID,
    "Hodos": HODOS_AGENT_ID,
    "HermesReporter": HERMES_REPORTER_AGENT_ID,
    "Kronos": KRONOS_AGENT_ID,
    "Athena": ATHENA_AGENT_ID,
    "Daedalus": DAEDALUS_AGENT_ID,
    "GymSite": GYMSITE_AGENT_ID,
}
