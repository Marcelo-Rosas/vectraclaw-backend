import os
import sys
import asyncio
from typing import Dict, Any

from supabase import create_client, Client

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.daedalus import _handle_bpmn_generate
from src.services.bpmn_materialize import materialize_bpmn_to_workflow

from dotenv import load_dotenv

def get_supabase() -> Client:
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    load_dotenv(dotenv_path=env_path)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    schema = os.environ.get("SUPABASE_SCHEMA", "vectraclip")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
        sys.exit(1)
    
    from supabase import ClientOptions
    return create_client(url, key, options=ClientOptions(schema=schema))

def main():
    supabase = get_supabase()
    
    # 1. Encontrar o processo SIPOC criado no teste frontend
    res = supabase.table("sipoc_processes").select("id, name, sipoc_sectors(company_id)").ilike("name", "Fulfillment do Pedido%").order("created_at", desc=True).limit(1).execute()
    if not res.data:
        print("Nenhum processo 'Fulfillment do Pedido' encontrado.")
        sys.exit(1)
        
    process = res.data[0]
    process_id = process["id"]
    company_id = process["sipoc_sectors"]["company_id"]
    print(f"Encontrado Processo: {process['name']} ({process_id})")
    
    # 2. Encontrar a atividade e garantir agent e specialty configs
    comp_res = supabase.table("sipoc_components").select("id, content").eq("process_id", process_id).eq("type", "activity").execute()
    if not comp_res.data:
        print("Nenhuma atividade encontrada no processo.")
        sys.exit(1)
        
    activity = comp_res.data[0]
    activity_id = activity["id"]
    
    print("Garantindo Agente...")
    agent_res = supabase.table("agents").select("id").eq("company_id", company_id).limit(1).execute()
    if not agent_res.data:
        ins_res = supabase.table("agents").insert({"company_id": company_id, "name": "Logistics Agent"}).execute()
        agent_id = ins_res.data[0]["id"]
    else:
        agent_id = agent_res.data[0]["id"]
        
    print("Garantindo Posição (Service Account)...")
    pos_res = supabase.table("sipoc_positions").select("id").eq("company_id", company_id).execute()
    position_id = None
    for p in pos_res.data:
        # Check metadata
        pm = supabase.table("sipoc_positions").select("metadata").eq("id", p["id"]).execute()
        meta = pm.data[0].get("metadata") or {}
        if meta.get("is_bot") and meta.get("linked_agent_id") == agent_id:
            position_id = p["id"]
            break

    if not position_id:
        pos_ins = supabase.table("sipoc_positions").insert({
            "company_id": company_id,
            "title": "Robô Picking",
            "metadata": {
                "is_bot": True,
                "linked_agent_id": agent_id
            }
        }).execute()
        position_id = pos_ins.data[0]["id"]
        
    # Ensure logistics-picking is in catalog
    cat_res = supabase.table("operation_types_catalog").select("id").eq("id", "logistics-picking").execute()
    if not cat_res.data:
        supabase.table("operation_types_catalog").insert({"id": "logistics-picking", "name": "Logistics Picking", "category": "action"}).execute()

    print(f"Vinculando Atividade {activity_id} à Posição {position_id} (RACI)")
    supabase.table("sipoc_components").update({
        "responsible_position_id": position_id,
        "automation_status": None,  # Limpando lixo antigo
        "suggested_operation_type": None # Limpando lixo antigo
    }).eq("id", activity_id).execute()
    
    # Disable logic_pattern for test to avoid FK issue
    supabase.table("bpmn_gateway_bindings").update({"is_active": False}).eq("logic_pattern_id", "split-if").execute()

    
    # 3. Criar agent_specialty_config para 'logistics-picking'
    print("Criando Agent Specialty Config para logistics-picking")
    cfg_res = supabase.table("agent_specialty_configs").select("id").eq("company_id", company_id).eq("agent_id", agent_id).execute()
    if cfg_res.data:
        spec_cfg_id = cfg_res.data[0]["id"]
        # Garante operation_types
        supabase.table("agent_specialty_configs").update({
            "values": {"operation_types": ["logistics-picking"]}
        }).eq("id", spec_cfg_id).execute()
    else:
        spec_res = supabase.table("agent_specialties").select("id").limit(1).execute()
        if not spec_res.data:
            supabase.table("agent_specialties").insert({"id": "picking", "name": "Picking"}).execute()
            specialty_id = "picking"
        else:
            specialty_id = spec_res.data[0]["id"]
            
        ins_cfg = supabase.table("agent_specialty_configs").insert({
            "company_id": company_id,
            "agent_id": agent_id,
            "specialty_id": specialty_id,
            "values": {"operation_types": ["logistics-picking"]}
        }).execute()
        spec_cfg_id = ins_cfg.data[0]["id"]
        
    print(f"Agent Specialty Config ID: {spec_cfg_id}")
    
    verify = supabase.table("agent_specialty_configs").select("id, company_id").eq("id", spec_cfg_id).execute()
    print(f"Verify config in DB: {verify.data}")
    
    # 4. Chamar Daedalus para gerar BPMN
    print("Invocando Daedalus bpmn-generate...")
    import uuid
    task_id = str(uuid.uuid4())
    task_mock = {
        "id": task_id,
        "company_id": company_id,
        "input_json": {
            "source_type": "sipoc_process",
            "source_id": process_id,
            "name": f"BPMN E2E Fulfillment {str(uuid.uuid4())[:8]}"
        },
        "operation_type": "bpmn-generate",
        "status": "in_progress",
        "title": "Teste E2E BPMN"
    }
    
    supabase.table("tasks").insert(task_mock).execute()
    
    
    daedalus_res = _handle_bpmn_generate(task_mock, supabase)
    outputs = daedalus_res.get("output_json", {}).get("outputs", {})
    diagram_id = outputs.get("diagram_id")
    
    if not diagram_id:
        print("Falha ao gerar diagrama:", daedalus_res)
        sys.exit(1)
        
    print(f"Diagrama gerado: {diagram_id}")
    
    # 5. Chamar bpmn_materialize
    print("Materializando BPMN -> Workflow...")
    result = materialize_bpmn_to_workflow(supabase, diagram_id=diagram_id, user_company_id=company_id)
    workflow_id = result.get("workflow_id")
    print(f"Workflow criado: {workflow_id}")
    print("Warnings da materialização:", result.get("warnings"))
    
    # 6. Validar
    steps_res = supabase.table("workflow_steps").select("id, slug, agent_specialty_config_id").eq("workflow_id", workflow_id).execute()
    steps = steps_res.data
    
    print("\n=== VALIDAÇÃO DO CABEAMENTO ===")
    success = False
    for step in steps:
        print(f"Step {step['slug']}: cfg={step['agent_specialty_config_id']}")
        if step['agent_specialty_config_id'] == spec_cfg_id:
            success = True
            
    if success:
        print("[SUCESSO] O fluxo Sipoc -> BPMN -> Workflow manteve o agent_specialty_config_id automaticamente!")
    else:
        print("[FALHA] Nenhum step recebeu o agent_specialty_config_id correto.")

if __name__ == "__main__":
    main()
