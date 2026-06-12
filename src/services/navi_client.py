import os
import logging
import httpx

logger = logging.getLogger("VectraClawAPI")

NAVI_API_BASE = os.getenv("NAVI_API_BASE", "")
NAVI_API_TOKEN = os.getenv("NAVI_API_TOKEN", "")

async def create_gymsite_deal(nome: str, cnpj: str, email: str, telefone: str, access_code: str) -> dict:
    """Best-effort — nunca raise."""
    if not NAVI_API_BASE or not NAVI_API_TOKEN:
        logger.warning("NAVI vars ausentes — deal não criado")
        return {}
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{NAVI_API_BASE}/api/deals",
                json={
                    "title": f"GymSite Lead — {cnpj}",
                    "contact_name": nome,
                    "contact_email": email,
                    "contact_phone": telefone,
                    "source": "gymsite_lead_form",
                    "tags": ["gymsite", "lead"],
                    "metadata": {"access_code": access_code}
                },
                headers={"Authorization": f"Bearer {NAVI_API_TOKEN}"}
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("Navi deal failed (best-effort): %s", exc)
        return {}
