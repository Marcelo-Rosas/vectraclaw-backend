import asyncio
import json as _json
import logging
import re
import unicodedata
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field

from src.services.oracle_session import (
    get_or_create_session,
    register_stream_queue,
    unregister_stream_queue,
)
from src.services.oracle_llm_stream import stream_oracle_response
from src.services.gemini_client import generate, DEFAULT_MODEL

logger = logging.getLogger("OracleRunner")

class SipocComponentContentSchema(BaseModel):
    name: str = Field(description="Nome ou descrição principal do componente.")
    what: Optional[str] = Field(default=None, description="O que é feito na atividade?")
    who: Optional[str] = Field(default=None, description="Quem executa?")
    when: Optional[str] = Field(default=None, description="Quando ocorre?")
    where: Optional[str] = Field(default=None, description="Onde ocorre?")
    why: Optional[str] = Field(default=None, description="Por que é feito?")
    how: Optional[str] = Field(default=None, description="Como é feito?")
    howMuch: Optional[str] = Field(default=None, description="Quanto custa ou qual o volume?")
    technologies: Optional[list[str]] = Field(default=None, description="Tecnologias utilizadas")
    kpis: Optional[list[str]] = Field(default=None, description="Indicadores")

class SipocComponentSchema(BaseModel):
    id: str = Field(..., description="ID gerado (UUID) para este componente, ou o mesmo ID se já existia na conversa.")
    type: str = Field(..., description="Tipo do componente: 'supplier', 'input', 'activity', 'output' ou 'customer'")
    content: SipocComponentContentSchema = Field(..., description="Conteúdo do componente.")

class SipocStateSchema(BaseModel):
    components: list[SipocComponentSchema] = Field(description="Lista completa e atualizada dos componentes SIPOC extraídos da conversa.")

# ── Deduplicação fuzzy de componentes SIPOC ─────────────────────────────────

_NORMALIZE_RE = re.compile(r"[^\w\s]")


def _normalize_name(name: str) -> str:
    """Normaliza nome pra comparação fuzzy: lowercase, sem acentos, sem pontuação."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("ASCII")
    s = _NORMALIZE_RE.sub(" ", s)
    return " ".join(s.lower().split())


def _is_duplicate(existing_names: set, new_name: str) -> bool:
    """Verifica se new_name é duplicata de algum existing (substring ou igual)."""
    norm_new = _normalize_name(new_name)
    if not norm_new:
        return False
    for ex in existing_names:
        # Igualdade exata ou uma é substring da outra (ex: "Proposta Formal em PDF" vs "Proposta Formal em PDF via Email")
        if norm_new == ex or norm_new in ex or ex in norm_new:
            return True
    return False


def _deduplicate_components(components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove componentes duplicados por tipo+nome similar. Mantém o primeiro."""
    seen_by_type: Dict[str, set] = {}
    out: List[Dict[str, Any]] = []
    for comp in components:
        ctype = (comp.get("type") or "").strip().lower()
        name = ""
        content = comp.get("content") or {}
        if isinstance(content, dict):
            name = content.get("name") or content.get("title") or ""
        if not name:
            name = comp.get("name") or ""
        seen = seen_by_type.setdefault(ctype, set())
        if _is_duplicate(seen, name):
            continue
        seen.add(_normalize_name(name))
        out.append(comp)
    return out


async def _extract_sipoc_state(history_text: str) -> list[Dict[str, Any]]:
    prompt = f"""
Extraia o estado atual do diagrama SIPOC baseado nesta conversa.
Preencha a estrutura JSON com as etapas identificadas: Suppliers, Inputs, Activities, Outputs, Customers.
REGRAS CRÍTICAS:
- NUNCA duplique itens. Se um componente com o mesmo nome/conceito já apareceu, mantenha APENAS uma entrada.
- "Embarcador" e "Embarcador ou Cliente Final" são conceitos diferentes apenas se o usuário EXPLICITAMENTE distinguiu.
- Normalmente, agrupe variações do mesmo conceito em um único item (ex: "Proposta Formal em PDF" cobre também "Proposta Formal em PDF via Email").
- Mantenha consistência: se o usuário corrigiu algo, reflita a correção. Se uma atividade ganhou respostas de 5W2H (quem, quando, como, etc), adicione no 'content' do componente 'activity'.
Para cada item detectado, defina um ID no formato uuid (se não tiver) e o tipo exato.
Para 'activity', as chaves permitidas em 'content' são: name, what, who, when, where, why, how, howMuch, technologies, kpis. Para os demais, apenas 'name'.
O formato do JSON esperado deve seguir estritamente o Schema.

{history_text}
"""
    try:
        from google.genai import types
        text, _ = await generate(
            model=DEFAULT_MODEL,
            prompt=prompt,
            response_mime_type="application/json",
            response_schema=SipocStateSchema,
        )
        data = _json.loads(text)
        return data.get("components", [])
    except Exception as exc:
        logger.error("Failed to extract SIPOC state: %s", exc)
        return []

def _build_pending_activity(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ctx = payload.get("context") or {}
    activity_name = ctx.get("activity_name")
    if not activity_name:
        return None
    return {
        "id": ctx.get("activity_id"),
        "name": activity_name,
        "w2h_data": ctx.get("w2h_data") or {},
    }

async def stream_oracle_chat_v2(payload: Dict[str, Any], session_id: str) -> AsyncIterator[str]:
    """Streams Oracle SIPOC chat using the specialty system prompt, without state machines."""
    session = get_or_create_session(session_id)
    q: asyncio.Queue = asyncio.Queue()
    register_stream_queue(session_id, q)

    ctx = payload.get("context") or {}
    user_message = payload.get("user_message") or ctx.get("value") or ""

    # Fetch specialty config
    try:
        from src.api import supabase
        res = supabase.table("agent_specialties").select("system_prompt_template").eq("slug", "oracle_sipoc_mapper").execute()
        if getattr(res, "data", None):
            system_instruction = res.data[0].get("system_prompt_template", "")
        else:
            system_instruction = "Você é o Oracle, especialista em mapeamento SIPOC."
    except Exception as e:
        logger.warning(f"Failed to load oracle_sipoc_mapper specialty: {e}")
        system_instruction = "Você é o Oracle, especialista em mapeamento SIPOC."

    # Build conversation history
    history_text = ""
    if session.messages:
        history_text = "Histórico da conversa:\n"
        for msg in session.messages:
            role = "Usuário" if msg.get("role") == "user" else "Oracle"
            history_text += f"{role}: {msg.get('content')}\n"
        history_text += "\n"

    # Context injection (RAG, process details)
    context_text = ""
    if payload.get("goal"):
        goal = payload["goal"]
        if isinstance(goal, dict):
            context_text += f"Objetivo do Processo: {goal.get('title')} - {goal.get('description', '')}\n"
        else:
            context_text += f"Objetivo do Processo: {goal}\n"
    if ctx.get("rag_examples"):
        context_text += "Exemplos de Referência (RAG):\n" + "\n".join(ctx["rag_examples"]) + "\n"

    # ── Compile the SIPOC state known so far ─────────────────────────────────
    # Use last saved extraction (from previous turn) so we don't add latency
    # to the current turn. The new extraction will be saved after the response.
    compiled_state = getattr(session, "compiled_state", None)
    compiled_block = ""
    if compiled_state:
        try:
            lines = ["ESTADO_SIPOC_JA_CONFIRMADO (NÃO repita perguntas sobre estes itens):"]
            for comp in compiled_state:
                c = comp.get("content", {})
                name = c.get("name", "?")
                ctype = comp.get("type", "")
                fields = {k: v for k, v in c.items() if k != "name" and v}
                field_str = ", ".join(f"{k}={v!r}" for k, v in fields.items()) if fields else "(sem detalhes ainda)"
                lines.append(f"  [{ctype.upper()}] {name} — {field_str}")
            compiled_block = "\n".join(lines) + "\n\n"
        except Exception:
            compiled_block = ""

    # Append NO-REDUNDANCY rule to system instruction
    no_redundancy_rule = (
        "\n\nREGRA DE NÃO-REDUNDÂNCIA (CRÍTICO):\n"
        "Antes de fazer qualquer pergunta, verifique o bloco ESTADO_SIPOC_JA_CONFIRMADO no prompt.\n"
        "Se a informação já está lá, NÃO pergunte de novo. Pule diretamente para o próximo campo em branco.\n"
        "Compile silenciosamente tudo que o usuário já informou antes de formular a próxima pergunta.\n"
        "Nunca pergunte 'Quem é o responsável?' se já está registrado. Nunca pergunte sobre canal já confirmado."
    )
    system_instruction = system_instruction + no_redundancy_rule

    full_prompt = f"{compiled_block}{context_text}{history_text}Usuário: {user_message}"

    try:
        # We start the stream asynchronously
        assistant_response = ""
        async for chunk in stream_oracle_response(full_prompt, system_instruction=system_instruction):
            assistant_response += chunk
            yield f"data: {_json.dumps({'type': 'delta', 'content': chunk})}\n\n"

        yield f"data: {_json.dumps({'type': 'delta', 'content': '\n\n*Processando SIPOC em background...*'})}\n\n"

        if assistant_response:
            session.messages.append({"role": "user", "content": user_message})
            session.messages.append({"role": "assistant", "content": assistant_response})
            session.current_stage = payload.get("stage", session.current_stage)

        # Re-build full history to send to extraction
        history_for_extraction = "Histórico completo:\n"
        for msg in session.messages:
            role = "Usuário" if msg.get("role") == "user" else "Oracle"
            history_for_extraction += f"{role}: {msg.get('content')}\n"

        extracted_components = await _extract_sipoc_state(history_for_extraction)

        # Cache compiled state for use in NEXT turn's prompt
        if extracted_components:
            session.compiled_state = extracted_components  # type: ignore[attr-defined]
        
        # Deduplica antes de enviar ao frontend — evita duplicatas no canvas
        deduped = _deduplicate_components(extracted_components)
        if deduped:
            yield f"data: {_json.dumps({'type': 'sipoc_state', 'components': deduped})}\n\n"

        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    except Exception as exc:
        logger.error("oracle_runner failed session=%s: %s", session_id, exc)
        yield f"data: {_json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield f"data: {_json.dumps({'type': 'done'})}\n\n"
    finally:
        unregister_stream_queue(session_id)
