"""prospect_leaves — folhas executáveis da prospecção (effect-only, sem LLM).

Fecham a execução real da árvore Goal→SIPOC→workflow→tasks:

- enrich-phone: reconcilia o mobile do decisor a partir dos `contacts` do NAVI
  (populados pelo pipeline GymSite/Instagram) e grava no prospect do Claw.
  Safe/in-repo: leitura NAVI + escrita no prospect. Se não achar, sinaliza
  needs_enrichment (rodar o pipeline GymSite).

- outbound-wa: enfileira o template aprovado no `send_queue` do NAVI (que envia
  com o número GREEN, com pacing). OUTWARD-FACING → GATED: dry-run por padrão;
  só enfileira (status 'pending') quando input.confirm_send == true. Executar o
  workflow NÃO dispara WhatsApp sozinho.

Registradas como effect-only no executor genérico (src/agents/specialty_generic.py).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.specialty_generic import register_effect
from src.services.navi_client import get_navi_client

logger = logging.getLogger("ProspectLeaves")

ENRICH_SLUG = "enrich-phone"
OUTBOUND_SLUG = "outbound-wa"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ---------------------------------------------------------------------------
# enrich-phone
# ---------------------------------------------------------------------------
def enrich_phone(task: Dict[str, Any], supabase: Any, parsed: Dict[str, Any],
                 values: Dict[str, Any]) -> Dict[str, Any]:
    """Reconcilia mobile do decisor via contacts do NAVI; grava no prospect."""
    inp = parsed if isinstance(parsed, dict) else {}
    prospect_id = inp.get("prospect_id")
    name = inp.get("name") or inp.get("decisor")
    phone_hint = _digits(inp.get("phone"))

    navi = get_navi_client()
    if navi is None:
        raise RuntimeError("NAVI não configurado (NAVI_SUPABASE_URL/NAVI_SERVICE_ROLE_KEY)")

    contact = None
    try:
        if phone_hint:
            r = navi.table("contacts").select("id, phone_number, name, tags").execute()
            for c in (r.data or []):
                if _digits(c.get("phone_number")).endswith(phone_hint[-8:]):
                    contact = c
                    break
        if contact is None and name:
            r = (navi.table("contacts").select("id, phone_number, name, tags")
                 .ilike("name", f"%{name}%").limit(1).execute())
            if r.data:
                contact = r.data[0]
    except Exception as exc:
        logger.warning("enrich_phone lookup NAVI falhou: %s", exc)

    if contact is None:
        return {"summary": "mobile não encontrado nos contacts NAVI — rodar pipeline GymSite/Instagram",
                "needs_enrichment": True, "mobile": None, "tier": None}

    mobile = contact.get("phone_number")
    # tier: A=tinha hint e bateu, B=achado por nome, C=sem validação
    tier = "A" if phone_hint else ("B" if name else "C")

    if prospect_id and supabase is not None:
        try:
            supabase.table("prospects").update({
                "phone": mobile, "enriched_at": _now_iso(),
            }).eq("id", prospect_id).execute()
        except Exception as exc:
            logger.warning("enrich_phone update prospect %s falhou: %s", prospect_id, exc)

    return {"summary": f"mobile {mobile} (tier {tier}) reconciliado do NAVI",
            "needs_enrichment": False, "mobile": mobile, "tier": tier,
            "navi_contact_id": contact.get("id")}


# ---------------------------------------------------------------------------
# outbound-wa
# ---------------------------------------------------------------------------
def _build_template_data(inp: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    name = inp.get("template_name") or values.get("default_template") or "vectra_prospeccao_academia"
    lang = inp.get("template_lang") or values.get("default_lang") or "pt_BR"
    params: List[str] = inp.get("template_params") or []
    return {"name": name, "language": lang, "params": params}


def outbound_wa(task: Dict[str, Any], supabase: Any, parsed: Dict[str, Any],
                values: Dict[str, Any]) -> Dict[str, Any]:
    """Enfileira template no send_queue do NAVI. GATED por confirm_send (dry-run default)."""
    inp = parsed if isinstance(parsed, dict) else {}
    to = _digits(inp.get("to") or inp.get("phone"))
    contact_id = inp.get("contact_id")
    confirm = bool(inp.get("confirm_send") is True)
    template = _build_template_data(inp, values)

    if not to and not contact_id:
        raise ValueError("outbound-wa exige input.to (E.164) ou input.contact_id")

    navi = get_navi_client()
    if navi is None:
        raise RuntimeError("NAVI não configurado (NAVI_SUPABASE_URL/NAVI_SERVICE_ROLE_KEY)")

    # resolve contact_id (não cria contato em dry-run)
    resolved_contact = contact_id
    if not resolved_contact and to:
        try:
            r = navi.table("contacts").select("id, phone_number").execute()
            for c in (r.data or []):
                if _digits(c.get("phone_number")).endswith(to[-8:]):
                    resolved_contact = c.get("id")
                    break
        except Exception as exc:
            logger.warning("outbound_wa contact lookup falhou: %s", exc)

    preview = {"to": to, "contact_id": resolved_contact, "template": template,
               "message_type": "template", "status_alvo": "pending"}

    # GATE outward-facing: sem confirm_send → dry-run, NÃO enfileira.
    if not confirm:
        return {"summary": f"DRY-RUN — template '{template['name']}' pronto pra {to or resolved_contact}. "
                           f"Defina input.confirm_send=true pra enfileirar no NAVI.",
                "sent": False, "dry_run": True, "preview": preview}

    # cria contato mínimo se faltar (só com confirm)
    if not resolved_contact:
        if not to:
            raise ValueError("sem contact_id e sem 'to' — não dá pra criar contato")
        try:
            now = _now_iso()
            cr = navi.table("contacts").insert({
                "phone_number": to, "name": inp.get("name"), "is_admin": False,
                "tags": ["vectra-outbound", "gymsite-prospeccao"],
                "created_at": now, "first_contact_date": now, "last_activity": now,
                "updated_at": now,
            }).execute()
            resolved_contact = cr.data[0]["id"] if cr.data else None
        except Exception as exc:
            raise RuntimeError(f"criação de contato NAVI falhou: {exc}")

    row = {
        "contact_id": resolved_contact, "message_type": "template",
        "from_type": "agent", "priority": 5, "retry_count": 0,
        "status": "pending", "template_data": template,
        "content": None, "metadata": {"source": "vectraclaw-outbound-wa", "task_id": task.get("id")},
    }
    ins = navi.table("send_queue").insert(row).execute()
    queue_id = ins.data[0]["id"] if ins.data else None
    return {"summary": f"template '{template['name']}' enfileirado no NAVI send_queue (status=pending)",
            "sent": False, "queued": True, "send_queue_id": queue_id, "contact_id": resolved_contact}


# registra as folhas como effect-only (sem LLM)
register_effect(ENRICH_SLUG, enrich_phone, llm=False)
register_effect(OUTBOUND_SLUG, outbound_wa, llm=False)
