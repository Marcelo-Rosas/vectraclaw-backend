"""
VEC-187 Smoke Test – Master System Prompt + Workflow Aduaneiro.

Testa:
  T1 – build_system_prompt() → string não vazia com seções obrigatórias
  T2 – system_prompt_meta()  → versão, hash, char_count presentes
  T3 – workflow_to_dict()    → 7 etapas W1–W7, campos obrigatórios
  T4 – Consistência interna  → todas as etapas 'proximo' apontam para IDs válidos
  T5 – Tools no workflow     → ferramentas referenciadas existem no TOOLS_REGISTRY
  T6 – GET /api/agent/system-prompt → 200, prompt e meta presentes
  T7 – GET /api/agent/system-prompt?format=text → 200, Content-Type text/plain
  T8 – GET /api/agent/workflow → 200, 7+ etapas, tolerancias e canais_siscomex
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import requests as _requests

BASE_URL = "http://localhost:3100"


def ok(label: str):
    print(f"  PASS  {label}")

def fail(label: str, info: str = ""):
    print(f"  FAIL  {label}" + (f": {info}" if info else ""))
    sys.exit(1)

def check(condition: bool, label: str, info: str = ""):
    if condition:
        ok(label)
    else:
        fail(label, info)


# ---------------------------------------------------------------------------
# T1 – build_system_prompt
# ---------------------------------------------------------------------------
print("\n[T1] build_system_prompt() — seções obrigatórias")
from src.services.brain.system_prompt import build_system_prompt, system_prompt_meta

prompt = build_system_prompt()
check(len(prompt) > 2000, "prompt não vazio (> 2000 chars)", str(len(prompt)))

required_sections = [
    "Identidade",
    "Ferramentas Disponíveis",
    "Workflow Aduaneiro",
    "Regras de Negócio",
    "Regras de Escalonamento",
    "Formatação de Respostas",
]
for section in required_sections:
    check(section in prompt, f"seção '{section}' presente")

tools_mentioned = ["extract_bl_pl", "calculate_cbm", "send_whatsapp_webhook"]
for tool in tools_mentioned:
    check(tool in prompt, f"tool '{tool}' mencionada no prompt")


# ---------------------------------------------------------------------------
# T2 – system_prompt_meta
# ---------------------------------------------------------------------------
print("\n[T2] system_prompt_meta()")
meta = system_prompt_meta()
check("version" in meta, "version presente")
check("sha256_prefix" in meta, "sha256_prefix presente")
check(meta.get("char_count", 0) > 2000, "char_count > 2000", str(meta.get("char_count")))


# ---------------------------------------------------------------------------
# T3 – workflow_to_dict
# ---------------------------------------------------------------------------
print("\n[T3] workflow_to_dict() — estrutura e etapas W1–W7")
from src.services.brain.workflow_aduaneiro import workflow_to_dict, STEPS_BY_ID

wf = workflow_to_dict()
check("etapas" in wf, "campo etapas presente")
check(len(wf["etapas"]) >= 7, "pelo menos 7 etapas", str(len(wf["etapas"])))

expected_ids = {"W1", "W2", "W3", "W4", "W4_ALERTA", "W5", "W6", "W7"}
found_ids = {s["id"] for s in wf["etapas"]}
check(expected_ids == found_ids, "IDs W1–W7 + W4_ALERTA presentes", str(found_ids))

check("tolerancias" in wf, "tolerancias presentes")
check("canais_siscomex" in wf, "canais_siscomex presentes")
check("container_specs" in wf, "container_specs presentes")

for etapa in wf["etapas"]:
    for field in ("id", "nome", "responsavel", "ferramentas", "entrada", "saida", "decisoes"):
        check(field in etapa, f"campo '{field}' em {etapa.get('id', '?')}")


# ---------------------------------------------------------------------------
# T4 – Consistência: proximo aponta para IDs válidos
# ---------------------------------------------------------------------------
print("\n[T4] Consistência: proximo → IDs válidos")
for step in wf["etapas"]:
    for next_id in step["proximo"]:
        check(next_id in found_ids, f"{step['id']}.proximo → {next_id} existe")


# ---------------------------------------------------------------------------
# T5 – Ferramentas no workflow existem no TOOLS_REGISTRY
# ---------------------------------------------------------------------------
print("\n[T5] Ferramentas no workflow existem no TOOLS_REGISTRY")
from src.m3_tools import TOOLS_REGISTRY

workflow_tools: set[str] = set()
for step in wf["etapas"]:
    workflow_tools.update(step["ferramentas"])

for tool in workflow_tools:
    check(tool in TOOLS_REGISTRY, f"'{tool}' presente no TOOLS_REGISTRY")


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def _login() -> str:
    r = _requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "marcelo.rosas@vectracargo.com.br", "password": "VectraClaw2026!"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["accessToken"]

tok = _login()
auth = {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# T6 – GET /api/agent/system-prompt (JSON)
# ---------------------------------------------------------------------------
print("\n[T6] GET /api/agent/system-prompt")
r = _requests.get(f"{BASE_URL}/api/agent/system-prompt", headers=auth, timeout=10)
check(r.status_code == 200, "HTTP 200", str(r.status_code))
body = r.json()
check("meta" in body, "campo meta presente")
check("prompt" in body, "campo prompt presente")
check(len(body.get("prompt", "")) > 2000, "prompt não vazio")


# ---------------------------------------------------------------------------
# T7 – GET /api/agent/system-prompt?format=text
# ---------------------------------------------------------------------------
print("\n[T7] GET /api/agent/system-prompt?format=text")
r = _requests.get(f"{BASE_URL}/api/agent/system-prompt?format=text", headers=auth, timeout=10)
check(r.status_code == 200, "HTTP 200", str(r.status_code))
check("text/plain" in r.headers.get("content-type", ""), "Content-Type text/plain", r.headers.get("content-type"))
check(len(r.text) > 2000, "body não vazio")


# ---------------------------------------------------------------------------
# T8 – GET /api/agent/workflow
# ---------------------------------------------------------------------------
print("\n[T8] GET /api/agent/workflow")
r = _requests.get(f"{BASE_URL}/api/agent/workflow", headers=auth, timeout=10)
check(r.status_code == 200, "HTTP 200", str(r.status_code))
wf_http = r.json()
check(len(wf_http.get("etapas", [])) >= 7, "7+ etapas via HTTP")
check("tolerancias" in wf_http, "tolerancias via HTTP")
check("canais_siscomex" in wf_http, "canais_siscomex via HTTP")

print("\n✓ Todos os testes passaram (VEC-187)\n")
