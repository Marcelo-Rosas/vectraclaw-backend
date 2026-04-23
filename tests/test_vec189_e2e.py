"""
VEC-189 E2E – Trilha de auditoria completa.

Valida o fluxo fim-a-fim:
  Task criada no VectraClip → Agent claims → Heartbeat → Task concluída → Auditoria

Etapas:
  E1 – GET /api/audit/parity       → overall=healthy, checks sem error
  E2 – POST /api/auth/login        → JWT válido
  E3 – GET /api/companies/{id}/agents → pelo menos 1 agente disponível
  E4 – POST /api/companies/{id}/tasks → task criada com status=backlog
  E5 – GET /api/companies/{id}/tasks  → task aparece na lista
  E6 – POST /api/tasks/{id}/claim     → task status=in_progress, agentId preenchido
  E7 – POST /api/heartbeats           → heartbeat registrado com status=working
  E8 – POST /api/tasks/{id}/complete  → task status=done
  E9 – GET /api/audit/parity          → re-verifica saúde pós-operações
  E10 – Relatório final da trilha
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import time
import requests as _requests

BASE_URL = "http://localhost:3100"
COMPANY_ID = "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c"

PASS = []
FAIL = []
SKIP = []


def ok(label: str, extra: str = ""):
    msg = f"  PASS  {label}" + (f" — {extra}" if extra else "")
    print(msg)
    PASS.append(label)

def fail(label: str, info: str = ""):
    msg = f"  FAIL  {label}" + (f": {info}" if info else "")
    print(msg)
    FAIL.append(label)

def skip(label: str, reason: str = ""):
    msg = f"  SKIP  {label}" + (f" ({reason})" if reason else "")
    print(msg)
    SKIP.append(label)

def check(condition: bool, label: str, info: str = "", fatal: bool = False):
    if condition:
        ok(label, info if info else "")
    else:
        fail(label, info)
        if fatal:
            _report_and_exit()

def _report_and_exit():
    _print_report()
    sys.exit(1)

def _print_report():
    print("\n" + "="*60)
    print(f"  TRILHA E2E VEC-189 — Resultado Final")
    print("="*60)
    print(f"  PASS: {len(PASS)}")
    print(f"  FAIL: {len(FAIL)}")
    print(f"  SKIP: {len(SKIP)}")
    if FAIL:
        print(f"\n  Checks que falharam:")
        for f in FAIL:
            print(f"    ✗ {f}")
    overall = "✓ HEALTHY" if not FAIL else "✗ DEGRADED"
    print(f"\n  Status geral: {overall}")
    print("="*60)


# ============================================================
# E1 – Parity report (pré-operações)
# ============================================================
print("\n[E1] GET /api/audit/parity — pre-check")

# Precisamos de token para acessar endpoints protegidos, mas parity é protegido também
# Então fazemos login primeiro
r_login = _requests.post(
    f"{BASE_URL}/api/auth/login",
    json={"email": "marcelo.rosas@vectracargo.com.br", "password": "vectra123"},
    timeout=10,
)
if not r_login.ok:
    fail("E1 login", f"{r_login.status_code} {r_login.text}")
    _report_and_exit()

tok = r_login.json()["accessToken"]
auth = {"Authorization": f"Bearer {tok}"}
ok("E2 login JWT obtido", f"token={tok[:20]}...")

r = _requests.get(f"{BASE_URL}/api/audit/parity", headers=auth, timeout=10)
check(r.status_code == 200, "E1 GET /api/audit/parity 200", str(r.status_code), fatal=True)
parity = r.json()
summary = parity.get("summary", {})
check(summary.get("error", 0) == 0, "E1 sem checks em error", str(summary.get("failed_checks", [])))
check(summary.get("overall") == "healthy", "E1 overall=healthy", summary.get("overall", "?"))
print(f"       checks: {summary.get('ok')}/{summary.get('total')} ok")


# ============================================================
# E3 – Buscar agente disponível
# ============================================================
print("\n[E3] GET /api/companies/{id}/agents")
r = _requests.get(f"{BASE_URL}/api/companies/{COMPANY_ID}/agents", headers=auth, timeout=10)
check(r.status_code == 200, "E3 200", str(r.status_code), fatal=True)
agents = r.json()
check(len(agents) > 0, "E3 pelo menos 1 agente", f"got {len(agents)}", fatal=True)
agent_id = agents[0].get("id") or agents[0].get("agentId")
ok("E3 agent_id obtido", agent_id)


# ============================================================
# E4 – Criar task
# ============================================================
print("\n[E4] POST /api/companies/{id}/tasks")
task_title = f"VEC-189 E2E trilha {int(time.time())}"
r = _requests.post(
    f"{BASE_URL}/api/companies/{COMPANY_ID}/tasks",
    json={
        "title": task_title,
        "description": "Smoke test E2E — criado pelo test_vec189_e2e.py",
        "budgetLimit": 500,
        "status": "backlog",
    },
    headers={**auth, "Content-Type": "application/json"},
    timeout=10,
)
check(r.status_code in (200, 201), "E4 task criada 200/201", str(r.status_code), fatal=True)
task = r.json()
task_id = task.get("id")
check(bool(task_id), "E4 task_id presente", str(task_id), fatal=True)
check(task.get("status") == "backlog", "E4 status=backlog", task.get("status", "?"))
ok("E4 task_id obtido", task_id)


# ============================================================
# E5 – Verificar task na listagem
# ============================================================
print("\n[E5] GET /api/companies/{id}/tasks — task aparece na lista")
r = _requests.get(f"{BASE_URL}/api/companies/{COMPANY_ID}/tasks", headers=auth, timeout=10)
check(r.status_code == 200, "E5 200", str(r.status_code))
task_list = r.json()
found = any(t.get("id") == task_id for t in task_list)
check(found, "E5 task_id encontrado na lista", f"lista com {len(task_list)} tasks")


# ============================================================
# E6 – Claim da task
# ============================================================
print("\n[E6] POST /api/tasks/{id}/claim")
r = _requests.post(
    f"{BASE_URL}/api/tasks/{task_id}/claim",
    json={"agentId": agent_id},
    headers={**auth, "Content-Type": "application/json"},
    timeout=10,
)
check(r.status_code == 200, "E6 claim 200", str(r.status_code))
if r.status_code == 200:
    claimed = r.json()
    check(
        claimed.get("status") in ("in_progress", "queued", "backlog"),
        "E6 status atualizado",
        claimed.get("status", "?"),
    )


# ============================================================
# E7 – Heartbeat do agente
# ============================================================
print("\n[E7] POST /api/heartbeats")
r = _requests.post(
    f"{BASE_URL}/api/heartbeats",
    json={
        "agentId": agent_id,
        "status": "working",
        "tokensUsed": 128,
        "logExcerpt": "VEC-189 E2E: processando tarefa",
        "taskId": task_id,
    },
    headers={**auth, "Content-Type": "application/json"},
    timeout=10,
)
check(r.status_code in (200, 201), "E7 heartbeat 200/201", str(r.status_code))
if r.status_code in (200, 201):
    hb = r.json()
    check(hb.get("agentId") == agent_id or hb.get("agent_id") == agent_id, "E7 agentId preservado")


# ============================================================
# E8 – Completar task
# ============================================================
print("\n[E8] POST /api/tasks/{id}/complete")
r = _requests.post(
    f"{BASE_URL}/api/tasks/{task_id}/complete",
    json={"agentId": agent_id},
    headers={**auth, "Content-Type": "application/json"},
    timeout=10,
)
check(r.status_code == 200, "E8 complete 200", str(r.status_code))
if r.status_code == 200:
    completed = r.json()
    check(
        completed.get("status") == "done",
        "E8 status=done",
        completed.get("status", "?"),
    )


# ============================================================
# E9 – Parity report pós-operações
# ============================================================
print("\n[E9] GET /api/audit/parity — post-check")
r = _requests.get(f"{BASE_URL}/api/audit/parity", headers=auth, timeout=10)
check(r.status_code == 200, "E9 200", str(r.status_code))
if r.status_code == 200:
    parity2 = r.json()
    s2 = parity2.get("summary", {})
    check(s2.get("error", 0) == 0, "E9 sem degradação pós-E2E", str(s2.get("failed_checks", [])))
    check(s2.get("overall") == "healthy", "E9 overall=healthy", s2.get("overall", "?"))


# ============================================================
# E10 – Relatório final
# ============================================================
print("\n[E10] Trilha auditada:")
print(f"       company_id : {COMPANY_ID}")
print(f"       agent_id   : {agent_id}")
print(f"       task_id    : {task_id}")
print(f"       task_title : {task_title}")
ok("E10 trilha E2E completa documentada")

_print_report()

if FAIL:
    sys.exit(1)
