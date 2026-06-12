"""W13 MVP — Handler Mercator pra operation_type `freight-quotation`.

Resolve Bug #1 (handoff CONNECTOR-SESSIONS-AGENT-DISPATCH 2026-05-18):
- 5 tasks freight-quotation recentes ficaram status=blocked
- Memory `project_session_2026-05-16_fase_a_5prs` afirmou W7 P0-10 criou
  src/agents/mercator.py, mas o arquivo NUNCA EXISTIU em prod

Pattern MVP humano-in-loop (escolha Marcelo 2026-05-18 após auditoria NAVI):
- NÃO calcula valor de frete (depende de price_tables/ANTT/pedágio que VectraClaw
  ainda não tem — ver ADR/PR4-5 futuro pra absorção do buscarCotacao NAVI completo)
- Gera resposta humanizada pt-BR escalando pro time comercial
- Pede os 4 dados estruturados (origem, destino, peso, valor) pra agilizar
- Retorna status=done — hook _reply_to_connector_session em agent_daemon.py:439
  envia o output_text como WhatsApp via connector_bus.reply

NÃO É ESCOPO (vai pra PRs futuros):
- LLM-driven response personalizada (W6)
- Cálculo automático de valor (W13.2+ se Marcelo decidir importar CFN tables)
- Multiselect templates WABA pra abrir conversa fora da janela 24h (W11+)
- Notificação interna pro operador via canal admin (W3 connector_channels admin)
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("Mercator")


def _greet(name: str) -> str:
    """Saudação amigável. Se nome vazio/anônimo, usa fallback genérico."""
    clean = (name or "").strip()
    if not clean or clean.lower() in ("anônimo", "anonimo", "anonymous"):
        return "Olá!"
    # Pega só primeiro nome se vier completo
    first = clean.split()[0]
    return f"Olá {first}!"


def _build_quotation_intake_message(client_name: str) -> str:
    """Resposta padrão escalação humana. Pede os 5 dados que o time comercial
    precisa pra fechar cotação (Marcelo 2026-05-18 adicionou CNPJ/CPF —
    necessário pra emissão de CT-e + análise de crédito + segmentação cliente)."""
    return (
        f"{_greet(client_name)} Recebi sua solicitação de cotação. 📦\n\n"
        "Pra meu time comercial agilizar, me confirma:\n"
        "• CNPJ ou CPF\n"
        "• Origem (cidade + UF)\n"
        "• Destino (cidade + UF)\n"
        "• Peso aproximado da carga (kg)\n"
        "• Valor da mercadoria (R$)\n\n"
        "Já estou encaminhando. Te retorno em até 1 hora útil com o valor. 🚚"
    )


def handle_freight_quotation(task: Dict[str, Any], supabase_client) -> Dict[str, Any]:
    """Entry point dispatchado por agent_daemon._execute_task quando
    op_type=='freight-quotation'.

    Args:
        task: row de vectraclip.tasks. Espera input_json com (no mínimo):
              - message: str (texto do cliente que disparou)
              - external_name: Optional[str] (nome do contato WhatsApp)
              - session_id: Optional[str] (FK pra connector_sessions — hook reply usa)
        supabase_client: client autenticado (pode ser None em testes).

    Returns:
        dict serializable: {status, output_text, output_json, ...}.
        agent_daemon faz json.dumps e marca task status=done.

        `output_text` é consumido pelo hook _reply_to_connector_session
        (agent_daemon.py:474) — vira o conteúdo enviado ao WhatsApp.
    """
    task_id = task.get("id", "?")
    input_json = task.get("input_json") or {}

    if not isinstance(input_json, dict):
        logger.warning("freight-quotation task=%s input_json malformado: %r", task_id, input_json)
        input_json = {}

    client_message = str(input_json.get("message") or "").strip()
    external_name = str(input_json.get("external_name") or "").strip()
    session_id = input_json.get("session_id")
    channel = input_json.get("channel") or "unknown"

    if not client_message:
        logger.warning("freight-quotation task=%s sem message no input_json", task_id)

    response = _build_quotation_intake_message(external_name)

    logger.info(
        "Mercator freight-quotation task=%s channel=%s name=%r session=%s len_response=%d",
        task_id, channel, external_name, session_id, len(response),
    )

    return {
        "status": "done",
        "output_text": response,
        "output_json": {
            "handler": "mercator.freight_quotation",
            "mode": "human_in_loop_mvp",
            "escalation": "comercial_team",
            "client_message_excerpt": client_message[:200],
            "external_name": external_name or None,
            "session_id": session_id,
            "channel": channel,
            "next_steps": [
                "Cliente recebe a mensagem de intake via WhatsApp (hook auto)",
                "Time comercial responde manualmente via /api/connector-sessions/{id}/reply",
                "TODO W13.2+: importar price_tables CFN pra cotação automática",
            ],
        },
        "log_excerpt": f"Mercator (freight-quotation) gerou escalação para {external_name or 'cliente'}"
    }
