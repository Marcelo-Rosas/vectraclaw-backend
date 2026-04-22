"""
VEC-182 smoke — CRUD completo de Tasks.

Testa:
1. POST /api/companies/{id}/tasks  — insert real no Supabase
2. GET  /api/companies/{id}/tasks  — lista inclui a task criada
3. PATCH /api/tasks/{id}           — atualiza status + budgetLimit

Roda: python tests/test_vec182_smoke.py
"""
import sys, requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:3100"
COMPANY = "c0000000-0000-4000-8000-000000000001"


def login() -> str:
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": "marcelo.rosas@vectracargo.com.br", "password": "vectra123"},
    )
    r.raise_for_status()
    tok = r.json()["accessToken"]
    print(f"[OK] login token={tok[:24]}...")
    return tok


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def test_create_task(tok: str) -> dict:
    body = {
        "title": "VEC-182 smoke task",
        "description": "Criada pelo smoke test automatico",
        "budgetLimit": 12000,
        "status": "backlog",
        "parentTaskId": None,
        "assignedToAgentId": None,
        "goalId": None,
    }
    r = requests.post(
        f"{BASE}/api/companies/{COMPANY}/tasks", json=body, headers=_headers(tok)
    )
    if r.status_code not in (200, 201):
        print(f"[FAIL] create_task status={r.status_code} body={r.text}")
        sys.exit(1)

    task = r.json()
    print(f"[OK] create_task id={task.get('id')} title={task.get('title')} status={task.get('status')}")

    # validar shape Zod (taskSchema)
    for field in ["id", "companyId", "title", "description", "status", "budgetLimit", "spent", "createdAt"]:
        assert field in task, f"campo ausente no response: {field}"
    assert "updatedAt" not in task, "updatedAt deve ser omitido (VEC-192 §3)"
    print("[OK] shape Zod ok (sem updatedAt)")

    return task


def test_list_includes(tok: str, task_id: str):
    r = requests.get(f"{BASE}/api/companies/{COMPANY}/tasks", headers=_headers(tok))
    r.raise_for_status()
    ids = [t["id"] for t in r.json()]
    assert task_id in ids, f"task {task_id} ausente na lista (total {len(ids)})"
    print(f"[OK] GET list inclui task criada ({len(ids)} tasks no total)")


def test_patch_task(tok: str, task_id: str):
    r = requests.patch(
        f"{BASE}/api/tasks/{task_id}",
        json={"status": "queued", "budgetLimit": 15000},
        headers=_headers(tok),
    )
    if r.status_code != 200:
        print(f"[FAIL] patch_task status={r.status_code} body={r.text}")
        sys.exit(1)
    patched = r.json()
    assert patched["status"] == "queued", f"status esperado 'queued', got {patched['status']}"
    assert patched["budgetLimit"] == 15000, f"budgetLimit esperado 15000, got {patched['budgetLimit']}"
    print(f"[OK] PATCH status={patched['status']} budgetLimit={patched['budgetLimit']}")


def test_empty_patch(tok: str, task_id: str):
    r = requests.patch(
        f"{BASE}/api/tasks/{task_id}", json={}, headers=_headers(tok)
    )
    assert r.status_code == 400, f"empty patch deveria ser 400, got {r.status_code}"
    assert r.json().get("detail") == "empty_patch"
    print("[OK] PATCH vazio => 400 empty_patch")


if __name__ == "__main__":
    tok = login()
    task = test_create_task(tok)
    test_list_includes(tok, task["id"])
    test_patch_task(tok, task["id"])
    test_empty_patch(tok, task["id"])
    print("\nALL OK — VEC-182 CRUD completo (POST real + GET + PATCH)")
