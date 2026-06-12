import os
import sys
from supabase import create_client

def main():
    supabase_url = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54321")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "your-service-role-key")
    company_id = "00000000-0000-0000-0000-000000000000" # Vectra Cargo mock company ID
    
    # We should get the company_id dynamically if possible, or leave it for the user to set.
    # We'll fetch the first company as default for seeding.
    
    client = create_client(supabase_url, supabase_key)
    res = client.table("companies").select("id").limit(1).execute()
    if not res.data:
        print("No companies found to attach PMO templates to.")
        sys.exit(1)
        
    company_id = res.data[0]["id"]
    print(f"Using company_id: {company_id}")

    templates = [
        {
            "name": "Termo de Abertura do Projeto",
            "domain": "Governança",
            "process": "Autorização do Projeto",
            "format": "Word",
            "type": "Estratégico",
            "context_vectraclaw": "No início oficial do desenvolvimento do VectraClaw."
        },
        {
            "name": "Business Case",
            "domain": "Governança",
            "process": "Documentos de Negócio",
            "format": "Word",
            "type": "Estratégico",
            "context_vectraclaw": "Justificativa de negócio para o VectraClaw."
        },
        {
            "name": "Ata de Reunião",
            "domain": "Governança",
            "process": "Gerenciar a Execução do Projeto",
            "format": "Word",
            "type": "Operacional",
            "context_vectraclaw": "Registro das reuniões de projeto."
        },
        {
            "name": "Avaliação de Desempenho da Equipe",
            "domain": "Recursos",
            "process": "Planejar o Gerenciamento dos Recursos",
            "format": "Word",
            "type": "Plano",
            "context_vectraclaw": "Avaliar os agentes (daemons) e a equipe humana."
        },
        {
            "name": "Base das Estimativas",
            "domain": "Finanças",
            "process": "Estimar os Custos",
            "format": "Word",
            "type": "Técnico",
            "context_vectraclaw": "Custo de API (OpenAI/Anthropic) e Infra."
        },
        {
            "name": "Declaração de Trabalho",
            "domain": "Governança",
            "process": "Planejar a Estratégia de Aquisições",
            "format": "Word",
            "type": "Contratual",
            "context_vectraclaw": "Termos de compromisso de entregáveis."
        },
        {
            "name": "Declaração do Escopo",
            "domain": "Escopo",
            "process": "Definir o Escopo",
            "format": "Word",
            "type": "Técnico",
            "context_vectraclaw": "Escopo arquitetural e funcional do sistema."
        }
    ]

    for t in templates:
        t["company_id"] = company_id
        
        # Upsert based on name
        exist = client.table("pmo_templates").select("id").eq("name", t["name"]).eq("company_id", company_id).execute()
        if exist.data:
            print(f"Updating {t['name']}")
            client.table("pmo_templates").update(t).eq("id", exist.data[0]["id"]).execute()
        else:
            print(f"Inserting {t['name']}")
            client.table("pmo_templates").insert(t).execute()

if __name__ == "__main__":
    main()
