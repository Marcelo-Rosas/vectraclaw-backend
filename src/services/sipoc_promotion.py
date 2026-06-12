from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any
from src.services.roi_calculator import calculate_automation_potential
from src.models import Agent, Routine, RoutineSchedule

async def promote_activity_to_automation(supabase_client, component_id: str) -> Dict[str, Any]:
    """
    Transforma uma atividade SIPOC em um Agente e uma Rotina funcional.
    """
    # 1. Buscar o componente
    comp_res = supabase_client.table("sipoc_components").select("*, sipoc_processes(*)").eq("id", component_id).single().execute()
    if not comp_res.data:
        return {"error": "Component not found"}
    
    component = comp_res.data
    process = component.get("sipoc_processes")
    content = component.get("content", {})
    
    # 2. Calcular Score Final (Rubrica v1)
    score = calculate_automation_potential(content)
    
    # 3. Definir Adaptador e Lógica
    logic_pattern = content.get("logicPattern", "SIMPLE")
    adapter_type = "claude_code"
    if logic_pattern == "WAIT-EVENT":
        adapter_type = "webhook" # Exemplo de mapeamento
    
    # 4. Criar o Agente
    agent_id = str(uuid4())
    agent_data = {
        "id": agent_id,
        "company_id": process.get("company_id"),
        "name": content.get("name", "Novo Agente"),
        "role": f"Automatizador de {process.get('name')}",
        "status": "idle",
        "token_budget": 50000,
        "current_burn_rate": 0.0,
        "adapter_type": adapter_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    supabase_client.table("agents").insert(agent_data).execute()
    
    # 5. Criar a Rotina (Schedule)
    when = content.get("when", "").lower()
    cron = "0 9 * * *" # Default: todo dia às 9h
    if "semanal" in when:
        cron = "0 9 * * 1" # Toda segunda às 9h
    
    routine_id = str(uuid4())
    routine_data = {
        "id": routine_id,
        "company_id": process.get("company_id"),
        "name": f"Rotina: {content.get('name')}",
        "status": "active",
        "schedule": {
            "cron": cron,
            "timezone": "America/Sao_Paulo",
            "human": f"Execução baseada em: {when}"
        },
        "agent_id": agent_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    supabase_client.table("routines").insert(routine_data).execute()
    
    # 6. Atualizar o componente SIPOC com o score e status
    supabase_client.table("sipoc_components").update({
        "validation_status": "verde" if score > 60 else "amarelo",
        "metadata": {
            **component.get("metadata", {}),
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "routine_id": routine_id,
            "automation_score": score
        }
    }).eq("id", component_id).execute()
    
    return {
        "success": True,
        "agent_id": agent_id,
        "routine_id": routine_id,
        "score": score
    }


async def promote_process_to_workflow(
    supabase_client,
    *,
    sipoc_process_id: str,
    goal_id: str,
    company_id: str,
    kind: str = "project",
) -> Dict[str, Any]:
    """Promove um processo SIPOC para um workflow executável.

    Cria um workflow baseado no processo SIPOC, com steps derivados das
    atividades mapeadas.
    """
    from src.services.workflow_graph import WorkflowGraphService

    try:
        wf_service = WorkflowGraphService(supabase_client)
        result = await wf_service.create_from_sipoc(
            sipoc_process_id=sipoc_process_id,
            goal_id=goal_id,
            company_id=company_id,
            kind=kind,
        )
        return {"success": True, "workflow_id": result.get("id"), **result}
    except Exception as exc:
        return {"error": str(exc)}
