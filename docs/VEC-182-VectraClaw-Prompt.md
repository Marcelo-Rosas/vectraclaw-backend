# VEC-182 — VectraClaw Prompt (CRUD JSON de Tasks: POST real + PATCH)

**Issue Linear:** [VEC-182 — Implementar rotas de CRUD JSON para Tasks](https://linear.app/vectra-cargo/issue/VEC-182/implementar-rotas-de-crud-json-para-tasks)
**Repositório alvo:** `VectraClaw` — `src/api.py`, `src/models.py`
**Relaciona-se com:** `VEC-194` (Fix 1 — GET tasks com JWT), `VEC-197b` (grants write `authenticated`)

---

## 🗺️ Território

| Responsabilidade                                          | Dono        | Onde                                                                       |
|-----------------------------------------------------------|-------------|----------------------------------------------------------------------------|
| `GET /api/tasks` / `GET /api/companies/{id}/tasks`        | já entregue | `VectraClaw/src/api.py` — `get_tasks`                                      |
| `POST /api/companies/{id}/tasks` — insert real Supabase   | **VectraClaw** | `src/api.py` — `create_task` (esta VEC)                                 |
| `PATCH /api/tasks/{id}` — `UpdateTaskInput` parcial       | **VectraClaw** | `src/api.py` — `patch_task` (esta VEC)                                  |
| `GET /api/tasks/{id}`                                     | já entregue | `src/api.py` — `get_task_endpoint`                                         |
| `POST /api/tasks/{id}/claim` e `/complete`                | já entregue | `src/api.py`                                                               |
| Schema `vectraclip.tasks` + RLS + grants                  | já aplicado pelo VectraClip | migrations existentes — **não recriar**              |
| Contrato Zod `taskSchema` / `CreateTaskInput` / `UpdateTaskInput` | VectraClip | `src/lib/api/endpoints/tasks.ts`, `src/lib/api/schemas.ts`   |
| Hooks React Query (`useCreateTask`, `useUpdateTask`)      | VectraClip  | `src/lib/queries/tasks.ts`                                                 |
| DELETE `/api/tasks/{id}`                                  | **fora de escopo** | Não existe no contrato `tasks.ts` do VectraClip                    |

---

## Contexto — auditoria pre-VEC (20/Abr/2026)

Varredura de `src/api.py` identificou dois gaps que bloqueavam o "CRUD completo":

| Gap | Evidência |
|---|---|
| `POST /api/companies/{id}/tasks` era mock puro | Retornava cópia de `MOCK_TASKS[0]` sem tocar o Supabase |
| `NewTaskInput` incompleto | Só `title`, `description`, `budgetLimit` — frontend envia também `parentTaskId`, `assignedToAgentId`, `goalId`, `status` |
| Status `blocked` ausente no modelo Python | `Task.status` não tinha `"blocked"` mas `taskStatusSchema` do Clip tem |
| `PATCH /api/tasks/{id}` inexistente | `updateTask` do Clip chamava `PATCH /tasks/{id}` → 405 |

---

## Fix 1 — 🔴 `NewTaskInput` alinhado ao `CreateTaskInput` do VectraClip

**Arquivo:** `src/api.py`

**Antes:** apenas `title: str`, `description: str`, `budgetLimit: int`.

**Depois:**

```python
class NewTaskInput(BaseModel):
    title: str
    description: str
    budgetLimit: int
    status: Optional[Literal["backlog","queued","in_progress","review","done","blocked"]] = "backlog"
    parentTaskId: Optional[str] = None
    assignedToAgentId: Optional[str] = None
    goalId: Optional[str] = None

    @validator("parentTaskId", "assignedToAgentId", "goalId", pre=True)
    def empty_str_to_none(cls, v):
        if v == "": return None
        return v
```

---

## Fix 2 — 🔴 `POST /api/companies/{id}/tasks` — insert real no Supabase

**Arquivo:** `src/api.py` — função `create_task`

**Estratégia:** usa `supabase` (service_role) para garantir write independente de grants `INSERT` do `authenticated`. O `company_id` vem da **rota** (não do body) para evitar cross-company injection.

```python
@app.post("/api/companies/{company_id}/tasks")
@app.post("/companies/{company_id}/tasks")
async def create_task(request: Request, company_id: str, payload: NewTaskInput):
    insert_row = {
        "company_id": company_id,
        "title": payload.title,
        "description": payload.description,
        "budget_limit": payload.budgetLimit,
        "status": payload.status or "backlog",
        "spent": 0,
        "parent_task_id": payload.parentTaskId,
        "assigned_to_agent_id": payload.assignedToAgentId,
        "goal_id": payload.goalId,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if supabase:
        res = supabase.table("tasks").insert(insert_row).execute()
        if not res.data:
            raise HTTPException(500, "insert_returned_empty")
        return Task(**res.data[0]).to_zod_dict()

    # Mock fallback
    ...
```

**Contrato de resposta:** `Task.to_zod_dict()` — sem `updatedAt` (VEC-192 §3).

---

## Fix 3 — 🔴 `PATCH /api/tasks/{id}` — `UpdateTaskInput` parcial

**Arquivo:** `src/api.py` — novo endpoint `patch_task`

```python
class UpdateTaskInput(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[Literal["backlog","queued","in_progress","review","done","blocked"]] = None
    budget_limit: Optional[int] = Field(default=None, alias="budgetLimit")
    spent: Optional[float] = None
    assigned_to_agent_id: Optional[str] = Field(default=None, alias="assignedToAgentId")
    parent_task_id: Optional[str] = Field(default=None, alias="parentTaskId")
    goal_id: Optional[str] = Field(default=None, alias="goalId")

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"

@app.patch("/api/tasks/{task_id}")
async def patch_task(request: Request, task_id: str, patch: UpdateTaskInput):
    payload = patch.dict(exclude_unset=True, by_alias=False)
    if not payload:
        raise HTTPException(400, "empty_patch")
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    client = get_authenticated_client(request.state.token)
    res = client.table("tasks").update(payload).eq("id", task_id).execute()
    if not res.data:
        raise HTTPException(404, "Target Task Not Found")
    return Task(**res.data[0]).to_zod_dict()
```

**Casos de erro:**
- Body vazio ou sem campos mutáveis → `400 empty_patch`
- `task_id` não encontrado → `404 Target Task Not Found`

---

## Fix 4 — 🟡 Status `blocked` em `models.py`

`Task.status` era `Literal["backlog","queued","in_progress","review","done"]`.
Adicionado `"blocked"` para alinhar com `taskStatusSchema` do VectraClip.

---

## Smoke test / Critério de aceite

Script: `tests/test_vec182_smoke.py`

```
[OK] login
[OK] create_task id=0628c99c-… title=VEC-182 smoke task status=backlog
[OK] shape Zod ok (sem updatedAt)
[OK] GET list inclui task criada (4 tasks no total)
[OK] PATCH status=queued budgetLimit=15000
[OK] PATCH vazio => 400 empty_patch

ALL OK — VEC-182 CRUD completo (POST real + GET + PATCH)
```

Critérios:
- [x] `POST /api/companies/{id}/tasks` grava no `vectraclip.tasks` via service_role
- [x] Response shape válido pelo `taskSchema` Zod (sem `updatedAt`)
- [x] `GET /api/companies/{id}/tasks` inclui a task recém-criada
- [x] `PATCH /api/tasks/{id}` atualiza campos parcialmente
- [x] `PATCH` vazio devolve `400 empty_patch`
- [x] Status `blocked` aceito em ambos os endpoints

---

## Fora de escopo

- `DELETE /api/tasks/{id}` — não existe no contrato `tasks.ts` do VectraClip.
- Insert real em `POST /api/companies/{id}/tasks` com `authenticated` role — sem grant de `INSERT` confirmado; service_role é a abordagem segura até migration explícita.
- Rollback / soft-delete de tasks.

---

*Última atualização: 20/Abr/2026 — VEC-182 encerrada como Done.*
