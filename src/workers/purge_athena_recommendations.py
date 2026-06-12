"""
Worker script para expurgo automático de recomendações antigas da Athena.
Deleta registros da tabela `athena_recommendations` onde o status é 'rejected' ou 'superseded' 
e o `updated_at` é anterior a 90 dias atrás.
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    print("ERRO: python-dotenv não instalado.", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [Worker] - %(levelname)s - %(message)s")
logger = logging.getLogger("PurgeAthenaRecommendations")

def main():
    root_dir = Path(__file__).resolve().parent.parent.parent
    load_dotenv(root_dir / ".env")

    try:
        from supabase import create_client, ClientOptions
    except ImportError:
        logger.error("Pacote `supabase` não instalado.")
        sys.exit(1)

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    schema = os.getenv("SUPABASE_SCHEMA", "vectraclip")

    if not url or not key:
        logger.error("Credenciais SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não encontradas.")
        sys.exit(1)

    try:
        supabase = create_client(url, key, options=ClientOptions(schema=schema, persist_session=False))
        
        # Calcula a data de corte (90 dias atrás)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
        cutoff_iso = cutoff_date.isoformat()
        
        logger.info(f"Iniciando expurgo de recomendações com inatividade anterior a: {cutoff_iso}")
        
        # O supabase-py não suporta a função `IN` combinada nativamente com deletes múltiplos de forma fácil,
        # então faremos duas chamadas distintas. O Postgrest permite o delete com múltiplos filtros.
        
        # 1. Purgar 'rejected'
        res_rejected = supabase.table("athena_recommendations").delete().eq("status", "rejected").lt("updated_at", cutoff_iso).execute()
        count_rejected = len(res_rejected.data) if hasattr(res_rejected, 'data') and res_rejected.data else 0
        logger.info(f"Sucesso: {count_rejected} recomendações 'rejected' foram purgadas.")
        
        # 2. Purgar 'superseded'
        res_superseded = supabase.table("athena_recommendations").delete().eq("status", "superseded").lt("updated_at", cutoff_iso).execute()
        count_superseded = len(res_superseded.data) if hasattr(res_superseded, 'data') and res_superseded.data else 0
        logger.info(f"Sucesso: {count_superseded} recomendações 'superseded' foram purgadas.")
        
        logger.info("Rotina de expurgo concluída.")
        
    except Exception as e:
        logger.error(f"Falha ao executar rotina de expurgo: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
