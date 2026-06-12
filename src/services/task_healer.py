"""
src.services.task_healer — Agente de Auto-Recuperação baseado em 5 Porquês (Self-Healing).

Intervém em tasks que falharam ('errored' ou 'blocked'), usa IA generativa para 
realizar a análise de causa raiz (5 Whys), e caso seja um erro operacional recuperável, 
corrige o input_json e devolve a task para 'queued'. Caso contrário, escala a task.
"""
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from uuid import UUID

from src.api import supabase, ws_manager
from src.services.gemini_client import generate
from src.models import Task

logger = logging.getLogger("TaskHealer")

# Usando o Gemini 2.5 Flash devido à alta cota gratuita (contornando rate limit do Pro)
HEALER_MODEL = "gemini-2.5-flash"

HEALER_SYSTEM_PROMPT = """Você é um Engenheiro de Confiabilidade (SRE) Autônomo de Nível 3.
Sua missão é diagnosticar e curar tarefas (Tasks) que falharam na execução, usando a metodologia dos 5 Porquês.

Regras de Diagnóstico (5 Whys):
Você deve analisar o `input_json` (o que foi pedido) e o `output_json` (o log de erro gerado) e perguntar "Por que?" 5 vezes para chegar à causa raiz.

Após a análise, você deve classificar o erro:
- "RESOLVABLE": O erro é operacional e você pode corrigi-lo alterando os parâmetros do `input_json` (ex: URL mal formatada, campo obrigatório vazio, JSON quebrado no input).
- "UNRESOLVABLE": O erro depende de ação externa, permissão humana ou falha sistêmica intransponível (ex: API de terceiros bloqueou IP, falta de saldo, senha revogada).

SE FOR RESOLVABLE: Forneça o `patched_input_json` com a correção aplicada.
SE FOR UNRESOLVABLE: `patched_input_json` deve ser null.

VOCÊ DEVE RESPONDER APENAS EM JSON VÁLIDO NO SEGUINTE FORMATO:
{
    "five_whys_analysis": [
        "1. Por que falhou? [Motivo]",
        "2. Por que [Motivo 1]? [Motivo 2]",
        ...
        "5. Por que [Motivo 4]? [Causa Raiz]"
    ],
    "root_cause_classification": "RESOLVABLE" | "UNRESOLVABLE",
    "rationale": "Breve explicação da sua decisão",
    "patched_input_json": { ... } // ou null se UNRESOLVABLE
}
"""

async def auto_heal_task(company_id: str, task_id: str) -> Dict[str, Any]:
    """Tenta curar uma task falha. Lança exceção em caso de erro no processo."""
    if not supabase:
        raise RuntimeError("Supabase client not initialized")

    # 1. Fetch Task
    res = supabase.table("tasks").select("*").eq("id", task_id).eq("company_id", company_id).execute()
    if not res.data:
        raise ValueError(f"Task {task_id} not found or access denied")
    
    task_row = res.data[0]
    status = task_row.get("status")
    
    if status not in ("errored", "blocked"):
        raise ValueError(f"Task está em status '{status}'. Apenas tasks errored/blocked podem ser curadas.")

    input_json = task_row.get("input_json") or {}
    output_json = task_row.get("output_json") or {}
    op_type = task_row.get("operation_type", "")

    # 2. Prepare Prompt
    prompt = f"""Analise a seguinte tarefa que falhou:

### INPUT_JSON ORIGINAL
{json.dumps(input_json, indent=2, ensure_ascii=False)}

### OUTPUT_JSON (ERRO)
{json.dumps(output_json, indent=2, ensure_ascii=False)}

Gere o JSON com a análise dos 5 Porquês e a correção (se aplicável).
"""

    # 3. Call Generative AI
    logger.info(f"Iniciando Auto-Healing para task {task_id} via {HEALER_MODEL}...")
    try:
        response_text, _ = await generate(
            model=HEALER_MODEL,
            prompt=prompt,
            system_instruction=HEALER_SYSTEM_PROMPT,
            response_mime_type="application/json"
        )
        diagnosis = json.loads(response_text)
    except Exception as e:
        logger.error(f"Falha ao rodar agente de healing para task {task_id}: {e}")
        raise RuntimeError(f"Erro na IA de diagnóstico: {str(e)}")

    classification = diagnosis.get("root_cause_classification")
    five_whys = "\\n".join(diagnosis.get("five_whys_analysis", []))
    rationale = diagnosis.get("rationale", "")
    
    evaluation_notes_append = f"--- AUTO-HEAL DIAGNOSIS ---\\n{five_whys}\\n\\nConclusão: {classification} - {rationale}"

    update_payload: Dict[str, Any] = {
        "evaluation_notes": evaluation_notes_append,
        "evaluated_by": "agent",
        "evaluated_at": datetime.now(timezone.utc).isoformat()
    }

    if classification == "RESOLVABLE" and diagnosis.get("patched_input_json"):
        # Auto-Healed! Volta para a fila.
        update_payload["status"] = "queued"
        update_payload["input_json"] = diagnosis.get("patched_input_json")
        update_payload["output_json"] = None # Limpa o erro para a próxima run
        logger.info(f"Task {task_id} CURADA. Voltando para queued.")
    else:
        # Irresolvível. Mantém/move para blocked para conselho/humano
        update_payload["status"] = "blocked"
        logger.info(f"Task {task_id} IRRESOLVÍVEL. Escalada para blocked.")

    # 4. Update Database
    update_res = supabase.table("tasks").update(update_payload).eq("id", task_id).execute()
    if not update_res.data:
        raise RuntimeError("Falha ao salvar diagnóstico da cura no banco de dados.")

    updated_task_dict = Task(**update_res.data[0]).to_zod_dict()
    
    # 5. Emit WS
    await ws_manager.emit_task_updated(company_id, updated_task_dict)
    
    return {
        "task": updated_task_dict,
        "diagnosis": diagnosis
    }
