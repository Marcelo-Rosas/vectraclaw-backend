"""Morpheus Inbound Triage — W9 (2026-05-18).

Handler do op_type `inbound-triage`. Chamado pelo agent_daemon quando uma task
desse tipo é claimed pelo daemon do Morpheus.

Responsabilidade: classificar a mensagem inbound (via vectraclip.inbound_intent_rules
catalog-driven) e criar task filha com op_type+agent corretos. Não responde
mensagens. Não executa cotação. Só roteia.

Fluxo:
  1. Lê task.input_json (message, session_id, button_id_hint, channel)
  2. SELECT inbound_intent_rules WHERE company_id=X AND is_active ORDER BY priority
  3. Loop data-driven (sem if/elif por tipo de sinal — auditor 2026-05-18):
     pra cada rule, tenta button_id (match exato) → origin_pattern (regex) →
     keywords (any lowercase). Primeira que bate vence.
  4. Sem match: lê connector_channels.fallback_operation_type (sem hardcode)
  5. Cria task filha com target_op_type + target_agent_id + parent_task_id
  6. Retorna {status:'done', output_json:{triage_result, child_task_id, ...}}

Convenções:
- Sync (chamado por agent_daemon que é sync). Sem asyncio.
- Best-effort: falhas individuais (rule parsing, child insert) logam e seguem.
  Se nenhuma child for criada (insert falhou), retorna status=blocked com erro.
- Não usa LLM nesta fase MVP. Match é puro regex/keywords. Evoluir pra LLM
  zero-shot quando rules de texto livre falharem com frequência (B2/B3 do ADR).

Memory refs:
- ADR-VEC-INBOUND-INTENT-CLASSIFIER (Opção A — Morpheus router)
- orchestration-pending-decision (decisão fechada nesta entrega)
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Morpheus.InboundTriage")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_active_rules(client, company_id: str) -> List[Dict[str, Any]]:
    """SELECT rules ativas pra company, ORDER BY priority (menor = mais prioritário)."""
    try:
        res = (
            client.table("inbound_intent_rules")
            .select("*")
            .eq("company_id", company_id)
            .eq("is_active", True)
            .order("priority")
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("load rules failed company=%s: %s", company_id, e)
        return []


def _load_fallback_op_type(client, channel: str) -> Optional[str]:
    """Lê connector_channels.fallback_operation_type pra o channel. Auditor:
    NUNCA hardcodar 'human-triage' — vem do catalog."""
    if not channel:
        return None
    try:
        res = (
            client.table("connector_channels")
            .select("fallback_operation_type")
            .eq("slug", channel)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("fallback_operation_type")
    except Exception as e:
        logger.warning("load fallback_operation_type failed channel=%s: %s", channel, e)
    return None


def _rule_matches(rule: Dict[str, Any], message: str, button_id_hint: Optional[str]) -> Optional[str]:
    """Tenta os 3 sinais da rule. Retorna o tipo de match que ganhou
    ('button_id'|'origin_pattern'|'keywords') ou None. Auditor: loop puro
    sobre campos preenchidos, sem if/elif estratificando prioridade —
    prioridade entre rules vem do `priority` column."""
    msg_lower = (message or "").lower()

    # button_id (match exato)
    rule_button_id = rule.get("button_id")
    if rule_button_id and button_id_hint and rule_button_id == button_id_hint:
        return "button_id"

    # origin_pattern (regex)
    pattern = rule.get("origin_pattern")
    if pattern:
        try:
            if re.search(pattern, message or "", re.IGNORECASE):
                return "origin_pattern"
        except re.error as e:
            logger.warning("rule %s origin_pattern inválido: %s", rule.get("intent_slug"), e)

    # keywords (any lowercase match)
    keywords = rule.get("keywords") or []
    if isinstance(keywords, list) and msg_lower:
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            if kw.lower() in msg_lower:
                return "keywords"

    return None


def _create_child_task(
    client,
    parent_task: Dict[str, Any],
    target_op_type: str,
    target_agent_id: Optional[str],
    rule: Optional[Dict[str, Any]],
    match_type: Optional[str],
) -> Optional[str]:
    """Cria task filha com referência ao parent triage. Retorna child_task_id ou None."""
    parent_id = parent_task.get("id")
    company_id = parent_task.get("company_id")
    parent_input = parent_task.get("input_json") or {}

    # Mantém input_json original + adiciona triage metadata
    child_input = dict(parent_input) if isinstance(parent_input, dict) else {"raw_parent_input": str(parent_input)}
    child_input["_triage"] = {
        "parent_triage_task_id": parent_id,
        "rule_id": rule.get("id") if rule else None,
        "rule_intent_slug": rule.get("intent_slug") if rule else None,
        "match_type": match_type,
        "matched_at": _now_iso(),
    }

    title_prefix = f"[Triage:{rule.get('intent_slug')}]" if rule else "[Triage:fallback]"
    message = parent_input.get("message") if isinstance(parent_input, dict) else None
    external_label = (
        (parent_input.get("external_name") if isinstance(parent_input, dict) else None)
        or (parent_input.get("external_id") if isinstance(parent_input, dict) else None)
        or "anônimo"
    )
    title = f"{title_prefix} {external_label[:30]} — {(message or '')[:60]}".strip()

    now_iso = _now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "company_id": company_id,
        "parent_task_id": parent_id,
        "title": title[:200],
        "description": (message or "")[:2000],
        "operation_type": target_op_type,
        "status": "queued",
        "executor_type": "auto",  # W8 — decision_engine roteia
        "assigned_to_agent_id": target_agent_id,
        "input_json": child_input,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    try:
        res = client.table("tasks").insert(row).execute()
        if not res.data:
            logger.error("create child task: insert retornou vazio")
            return None
        cid = str(res.data[0]["id"])
        logger.info(
            "morpheus triage child created parent=%s child=%s op=%s agent=%s match=%s",
            parent_id, cid, target_op_type, target_agent_id, match_type,
        )
        return cid
    except Exception as e:
        logger.exception("create child task falhou parent=%s op=%s: %s", parent_id, target_op_type, e)
        return None


def _build_user_facing_text(
    matched_rule: Optional[Dict[str, Any]],
    fallback_used: bool,
    target_op_type: Optional[str],
) -> str:
    """PR0e autopilot 2026-05-18: gera output_text amigável pra ir pro
    WhatsApp via _reply_to_connector_session (hook agent_daemon:432).

    Sem isso, o fallback do PR #225 envia JSON cru pro cliente.
    Marcelo recebeu JSON cru 3x na sessão 2bb7223b (pos 22, 25, 26)
    durante teste autopilot.

    Mensagem varia por contexto: rule matched (skill conhecida) vs
    fallback humano (escalação).
    """
    if matched_rule:
        intent_label = matched_rule.get("intent_slug") or "sua solicitação"
        intent_human = {
            "web-freight": "cotação de frete",
            "text-freight": "cotação de frete",
            "web-cross-docking": "cross-docking",
            "text-cross-docking": "cross-docking",
            "web-gymsite": "análise de academia",
            "text-gymsite": "análise de academia",
        }.get(intent_label, intent_label.replace("-", " "))
        return (
            f"Recebi sua solicitação de {intent_human}. "
            "Já encaminhei pro especialista responsável e em breve te respondemos. 🚀"
        )

    if fallback_used:
        # human-triage ou outro fallback configurado em connector_channels
        return (
            "Recebi sua mensagem! 👋 Vou direcionar pro time humano analisar "
            "e respondemos em breve. Se for urgente, me confirma o assunto pra agilizar."
        )

    return "Mensagem recebida. Em breve retornamos."


def entrypoint(task: Dict[str, Any], supabase_client) -> Dict[str, Any]:
    """Handler de inbound-triage. Chamado pelo agent_daemon.execute_task.

    Retorna dict serializable com status/output_json — agent_daemon parsea
    e marca task done OU blocked.

    PR0e (2026-05-18): inclui `output_text` amigável em todos os returns
    de SUCESSO (não erros internos). Hook _reply_to_connector_session
    extrai esse texto e envia pro WhatsApp. Sem isso, JSON cru vazaria.
    """
    task_id = task.get("id", "?")
    company_id = task.get("company_id")
    input_json = task.get("input_json") if isinstance(task.get("input_json"), dict) else None

    if not company_id or not input_json:
        return {
            "status": "errored",
            "error": "missing_company_id_or_input_json",
            "output_json": {"error_detail": {"task_id": task_id}},
        }

    message = str(input_json.get("message") or "").strip()
    button_id_hint = input_json.get("button_id_hint") or None
    # channel vem da connector_session original; webhook já passa via session lookup,
    # mas como fallback usa o que vier no input_json
    channel = input_json.get("channel") or "whatsapp"  # connector_bus dispatcha hoje só whatsapp

    if not message and not button_id_hint:
        # Não há sinal nenhum pra classificar (mensagem vazia + sem botão).
        # Cai direto no fallback.
        logger.warning("morpheus triage task=%s sem message+button_id — fallback direto", task_id)

    rules = _load_active_rules(supabase_client, company_id)
    if not rules:
        logger.warning("morpheus triage company=%s sem rules ativas — fallback direto", company_id)

    matched_rule: Optional[Dict[str, Any]] = None
    matched_type: Optional[str] = None
    for rule in rules:
        match_type = _rule_matches(rule, message, button_id_hint)
        if match_type:
            matched_rule = rule
            matched_type = match_type
            break

    if matched_rule:
        target_op_type = matched_rule.get("target_operation_type")
        target_agent_id = matched_rule.get("target_agent_id")
    else:
        # Sem match → fallback do connector_channels (NÃO hardcode 'human-triage')
        target_op_type = _load_fallback_op_type(supabase_client, channel)
        target_agent_id = None  # Fallback geralmente é humano

        if not target_op_type:
            return {
                "status": "errored",
                "error": "no_match_and_no_fallback_configured",
                "output_json": {
                    "error_detail": {
                        "task_id": task_id,
                        "channel": channel,
                        "message_excerpt": message[:200],
                    }
                },
            }

    child_id = _create_child_task(supabase_client, task, target_op_type, target_agent_id, matched_rule, matched_type)
    if not child_id:
        return {
            "status": "errored",
            "error": "child_task_creation_failed",
            "output_json": {
                "error_detail": {
                    "task_id": task_id,
                    "target_op_type": target_op_type,
                    "matched_rule_slug": matched_rule.get("intent_slug") if matched_rule else None,
                }
            },
        }

    fallback_used = matched_rule is None
    return {
        "status": "done",
        "output_text": _build_user_facing_text(matched_rule, fallback_used, target_op_type),
        "output_json": {
            "child_task_id": child_id,
            "target_operation_type": target_op_type,
            "target_agent_id": target_agent_id,
            "matched_rule_slug": matched_rule.get("intent_slug") if matched_rule else None,
            "matched_rule_id": matched_rule.get("id") if matched_rule else None,
            "match_type": matched_type,
            "fallback_used": fallback_used,
        },
    }
