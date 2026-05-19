"""SSOT pras chaves 5W2H usadas em SIPOC components (PR2.2 autopilot).

Antes deste módulo o codebase tinha drift entre `howMuch` (camelCase) e
`how_much` (snake_case) — mesmo campo, dois nomes — confirmado por auditor
hardcode-orphan (a778cf6d57ef076a5, 2026-05-19). Marcelo decidiu canonical
snake_case (alinha DB jsonb + Pydantic field naming + grande maioria do
catalog `sipoc_taxonomy_global.default_5w2h`).

NOTA: este módulo **não migra dados existentes** nem reescreve o normalizer
de `src/api.py:5629-5793` (raio enorme — F-007 do PENDING-FOLLOWUPS). Ele
estabelece a convenção SSOT pra novos endpoints (PR2.3 commit) e fix de
labels/templates que estavam em camelCase sem necessidade.

Uso típico:
    from src.services.sipoc_5w2h_keys import (
        CANONICAL_KEYS, normalize_5w2h_keys, W2H_LABELS,
    )
    coverage = sum(1 for k in CANONICAL_KEYS if content.get(k)) / len(CANONICAL_KEYS)
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

#: Ordem canônica das 7 chaves 5W2H em snake_case (PMI clássico — what/why
#: precedem who/where/when, e how/how_much fecham). Mantenha esta ordem
#: estável: outros módulos podem confiar nela pra layout determinístico.
CANONICAL_KEYS: Tuple[str, ...] = (
    "what",
    "why",
    "who",
    "where",
    "when",
    "how",
    "how_much",
)

#: Aliases conhecidos → chave canônica. Usado por `normalize_5w2h_keys`
#: pra absorver legado camelCase sem precisar refator imediato em todos
#: os call-sites.
LEGACY_TO_CANONICAL: Dict[str, str] = {
    "howMuch": "how_much",
    "HowMuch": "how_much",
}

#: Labels humanos pt-BR pras 7 chaves. Usado em prompts do Oracle (substitui
#: hardcode em src/agents/oracle.py:_W2H_LABELS).
W2H_LABELS: Dict[str, str] = {
    "what":     "O Quê? (What)",
    "why":      "Por Quê? (Why)",
    "who":      "Quem? (Who)",
    "where":    "Onde? (Where)",
    "when":     "Quando? (When)",
    "how":      "Como? (How)",
    "how_much": "Quanto Custa? (How Much)",
}


def normalize_5w2h_keys(content: Mapping[str, Any]) -> Dict[str, Any]:
    """Devolve dict novo com chaves 5W2H canônicas em snake_case.

    Mantém valores não-5W2H intactos (ex: `name`, `title`, `description`).
    Se ambos `howMuch` e `how_much` existirem, snake_case vence (alinha DB).
    """
    if not isinstance(content, Mapping):
        return {}
    out: Dict[str, Any] = {}
    for k, v in content.items():
        canonical = LEGACY_TO_CANONICAL.get(k, k)
        if canonical in out and canonical != k:
            continue
        out[canonical] = v
    return out


def coverage_5w2h(content: Mapping[str, Any]) -> float:
    """Retorna 0.0–1.0 de cobertura das 7 chaves 5W2H em `content`.

    Aceita valores string-like (str não vazia, dict não vazio, list não vazia).
    Normaliza chaves antes — `howMuch` legado conta como `how_much`.
    """
    normalized = normalize_5w2h_keys(content)
    filled = 0
    for k in CANONICAL_KEYS:
        v = normalized.get(k)
        if isinstance(v, str) and v.strip():
            filled += 1
        elif isinstance(v, dict) and v:
            filled += 1
        elif isinstance(v, list) and v:
            filled += 1
    return filled / len(CANONICAL_KEYS)
