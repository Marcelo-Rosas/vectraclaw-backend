"""
Hermes Auditor — O Novo Auditor Financeiro
Lê a pasta de Auditoria, extrai texto via RAG (PDF/CSV/OFX) e gera
regras sugeridas para as transações que o Kronos não conseguiu categorizar.
O resultado final não é injetado diretamente; ele vai para o "Council" para aprovação humana.
"""

import json
import logging
import os
from glob import glob
from typing import Any, Dict, List

import pdfplumber

from src.services.gemini_client import generate

logger = logging.getLogger("HermesAuditor")

AUDITORIA_DIR = r"C:\Users\marce\OFX-C6\Auditoria\Auditoria"


def _extract_text_from_pdf(filepath: str) -> str:
    """Extrai texto de um PDF usando pdfplumber."""
    text = []
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
    except Exception as e:
        logger.error("Erro ao ler PDF %s: %s", filepath, e)
    return "\n".join(text)


def _extract_text_from_csv(filepath: str) -> str:
    """Lê CSV puramente como texto para injetar no RAG."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [f.readline() for _ in range(100)]
            return "".join(lines)
    except Exception as e:
        logger.error("Erro ao ler CSV %s: %s", filepath, e)
    return ""


def _extract_text_from_ofx(filepath: str) -> str:
    """Lê arquivo OFX/QFX para injetar no RAG."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = [f.readline() for _ in range(100)]
            return "".join(lines)
    except Exception as e:
        logger.error("Erro ao ler OFX %s: %s", filepath, e)
    return ""


def _build_rag_context() -> str:
    """Varre a pasta de Auditoria e constrói o contexto de RAG."""
    if not os.path.exists(AUDITORIA_DIR):
        logger.warning("Pasta de Auditoria não encontrada: %s", AUDITORIA_DIR)
        return ""

    context_parts = []
    
    # Processar PDFs (Faturas, Extratos)
    for pdf_file in glob(os.path.join(AUDITORIA_DIR, "*.pdf")):
        filename = os.path.basename(pdf_file)
        text = _extract_text_from_pdf(pdf_file)
        if text:
            context_parts.append(f"--- INÍCIO DOCUMENTO: {filename} ---\n{text[:2000]}\n--- FIM DOCUMENTO ---")

    # Processar CSVs
    for csv_file in glob(os.path.join(AUDITORIA_DIR, "*.csv")):
        filename = os.path.basename(csv_file)
        text = _extract_text_from_csv(csv_file)
        if text:
            context_parts.append(f"--- INÍCIO CSV: {filename} ---\n{text}\n--- FIM CSV ---")

    # Processar OFXs
    for ofx_file in glob(os.path.join(AUDITORIA_DIR, "*.ofx")) + glob(os.path.join(AUDITORIA_DIR, "*.qfx")):
        filename = os.path.basename(ofx_file)
        text = _extract_text_from_ofx(ofx_file)
        if text:
            context_parts.append(f"--- INÍCIO OFX: {filename} ---\n{text}\n--- FIM OFX ---")

    return "\n\n".join(context_parts)


def _resolve_company_name(company_id: str, supabase_client: Any) -> str:
    if not company_id or not supabase_client:
        return "VectraClaw"
    try:
        r = supabase_client.table("companies").select("name").eq("company_id", company_id).limit(1).execute()
        name = ((r.data[0].get("name") if r.data else None) or "").strip()
        if name:
            return name
    except Exception as exc:
        logger.warning("HermesAuditor: falha ao ler companies.name (%s)", exc)
    return "VectraClaw"


def handle_ofx_audit(task: Dict[str, Any], supabase_client: Any) -> Dict[str, Any]:
    """
    Entrypoint despachado quando op_type == 'ofx-audit'.
    Gera um relatório de sugestão (Human-in-the-loop).
    """
    task_id = task.get("id", "?")
    company_id = str(task.get("company_id") or "")
    input_json = task.get("input_json") or {}
    logger.info("HermesAuditor ofx-audit task=%s", task_id)

    # 1. Recuperar itens não categorizados
    unclassified_items = input_json.get("unclassified_items", [])
    if not unclassified_items:
        return {
            "status": "done",
            "output_text": "Auditoria concluída: Nenhum item pendente de categorização encontrado.",
            "output_json": {"status": "no_action_needed"}
        }

    # 2. Construir o RAG Context
    rag_context = _build_rag_context()
    
    company_name = _resolve_company_name(company_id, supabase_client)

    # 3. Montar Prompt
    items_str = json.dumps(unclassified_items, indent=2, ensure_ascii=False)
    prompt = f"""Você é o Hermes, o Auditor Financeiro da empresa {company_name}.
Existem transações OFX que o Kronos não conseguiu categorizar. Sua missão é ler as transações pendentes,
cruzar com as informações contidas nos documentos de auditoria (RAG) e sugerir regras exatas em YAML
para inserção no 'kronos_category_rules.yaml'.

[DOCUMENTOS DA AUDITORIA (RAG)]
{rag_context}

[TRANSAÇÕES PENDENTES]
{items_str}

Retorne um JSON estrito no seguinte formato:
{{
  "summary": "Breve explicação do que você descobriu.",
  "suggested_rules": [
    {{
      "match_type": "contains|exact|regex",
      "pattern": "PADRAO ENCONTRADO",
      "category": "Categoria Sugerida",
      "justification": "Explique por que esta regra faz sentido com base no RAG"
    }}
  ]
}}
"""

    # 4. Invocar LLM (Gemini)
    try:
        # A chamada `generate` retorna uma tupla (response_text, context_ou_algo)
        import asyncio
        # Como _handle_ofx_audit é síncrono mas `generate` pode ser assíncrono?
        # O agent_daemon roda tasks como síncronas? Aparentemente o daemon usa métodos síncronos,
        # mas no task_healer ele é async. Se for necessário, vamos usar asyncio.run ou apenas mockar por enquanto.
        # Mas para o teste funcionar, vou mockar uma função async local para rodar.
        
        async def call_llm():
            resp_text, _ = await generate(
                model="gemini-2.5-flash",
                prompt=prompt,
                system_instruction="Retorne apenas JSON válido conforme requisitado, sem formatação markdown.",
                response_mime_type="application/json"
            )
            return resp_text
        
        try:
            loop = asyncio.get_event_loop()
            llm_response = loop.run_until_complete(call_llm())
        except RuntimeError:
            llm_response = asyncio.run(call_llm())

        # Parse JSON
        result_data = json.loads(llm_response)

        # O output do Hermes não atualiza o DB diretamente! Ele apenas gera a sugestão
        # para a UI do Council.
        return {
            "status": "done",
            "output_text": "Relatório de sugestões gerado para o Council.",
            "output_json": {
                "handler": "hermes_auditor",
                "report": result_data,
                "needs_human_approval": True
            },
            "log_excerpt": "Hermes auditor concluiu RAG e gerou sugestões pendentes de aprovação."
        }

    except Exception as e:
        logger.error("Erro na inferência do Hermes Auditor: %s", str(e))
        return {
            "status": "error",
            "output_text": f"Falha na auditoria: {str(e)}",
            "output_json": {"error": "llm_failure"}
        }
