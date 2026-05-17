# Smoke A.2 — `operation_type` catalog-driven (PR #184)

> **Contexto:** PR #184 mergeado em 2026-05-17. Aposenta 3 listas hardcoded de `operation_type` em favor do catálogo único `vectraclip.operation_types_catalog`. Este doc é o **handoff de validação** — pode ser executado via CLI local OU via outro agente Claude (extensão/Code).
>
> **Owner do smoke:** Marcelo Rosas (ou agente delegado)
> **Origem técnica:** ADR §10 P10 (decidido), [`HANDOFF-FRONTEND-BPMN-MODELER.md`](./HANDOFF-FRONTEND-BPMN-MODELER.md) (padrão de handoff)

---

## 1. Pré-requisitos — checar nesta ordem

### 1.1 Deploy do backend novo (PR #184)

```powershell
# Verificar versão do backend ativo (sha do commit deve incluir c9fd5e1 ou mais recente)
curl -sS https://api-vectraclip.vectracargo.com.br/api/health
# Resposta esperada: {"status":"online","service":"VectraClaw Agent Engine"}

# Se houver endpoint /api/version (não temos hoje), confirmar sha
# Senão: olhar logs do Cloudflare Tunnel / docker compose ps no host
```

### 1.2 Migration aplicada no remoto

⚠️ **CRÍTICO:** CI atual **não aplica** migrations automaticamente (`supabase/CLAUDE.md` linha "Status atual: CI ainda não configurada"). Você precisa rodar manualmente:

```powershell
cd C:\Users\marce\VectraClaw

# Verificar se há drift
supabase migration list

# Esperado: arquivo 20260517120000_a2_drop_operation_type_checks.sql
# aparece como LOCAL mas não REMOTE

# Dry-run primeiro
supabase db push --dry-run

# Se ok, aplicar
supabase db push
```

**Validar via SQL pós-aplicação:**

```sql
-- Constraints devem ter desaparecido
SELECT t.relname, c.conname
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'vectraclip'
  AND c.conname IN ('tasks_operation_type_check', 'routines_operation_type_check');

-- Esperado: 0 rows (constraints dropados)
```

### 1.3 JWT válido (caller autenticado)

```powershell
# Login self-service (POST #177)
$resp = Invoke-RestMethod -Method POST `
  -Uri "https://api-vectraclip.vectracargo.com.br/api/auth/login" `
  -ContentType "application/json" `
  -Body '{"email":"marcelo.rosas@vectracargo.com.br","password":"VectraClaw2026!"}'
$TOKEN = $resp.access_token
$COMPANY_ID = $resp.user.app_metadata.vectraclip.company_id
Write-Host "Token capturado. Company: $COMPANY_ID"
```

---

## 2. Smoke 1 — `operation_type` válido do catálogo (deve passar)

**Caso:** `operationType='orchestration'` — existe no `operation_types_catalog` (verificado: 40 entries ativos incluindo `orchestration`).

### Via PowerShell

```powershell
$body = @{
  title = "Smoke A.2 — orchestration válido"
  description = "Teste de validator catalog-driven aceitando valor existente"
  budgetLimit = 100
  operationType = "orchestration"
} | ConvertTo-Json

$resp = Invoke-RestMethod -Method POST `
  -Uri "https://api-vectraclip.vectracargo.com.br/api/companies/$COMPANY_ID/tasks" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body $body

Write-Host "✅ Task criada: $($resp.id)"
Write-Host "operation_type=$($resp.operationType) status=$($resp.status)"
```

### Via curl (bash/WSL)

```bash
TOKEN="<seu_jwt>"
COMPANY_ID="<seu_company_id>"

curl -sS -X POST \
  "https://api-vectraclip.vectracargo.com.br/api/companies/${COMPANY_ID}/tasks" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Smoke A.2 — orchestration válido",
    "description": "Teste de validator catalog-driven aceitando valor existente",
    "budgetLimit": 100,
    "operationType": "orchestration"
  }' | jq '.id, .operationType, .status'
```

### Resposta esperada

- **HTTP 201 Created**
- Body inclui `"operationType": "orchestration"`
- Body inclui `"status": "backlog"` (default)
- `id` UUID retornado

### Critério de aceite

✅ Task criada sem erro. Nenhum 422 nem 400.

---

## 3. Smoke 2 — `operation_type` inventado (deve retornar 422)

**Caso:** `operationType='inventado_xyz_2026'` — NÃO existe no catálogo. Validator deve rejeitar antes mesmo de chegar no banco.

### Via PowerShell

```powershell
$body = @{
  title = "Smoke A.2 — operation_type inventado"
  description = "Teste de validator catalog-driven rejeitando valor inexistente"
  budgetLimit = 100
  operationType = "inventado_xyz_2026"
} | ConvertTo-Json

try {
  $resp = Invoke-RestMethod -Method POST `
    -Uri "https://api-vectraclip.vectracargo.com.br/api/companies/$COMPANY_ID/tasks" `
    -Headers @{ Authorization = "Bearer $TOKEN" } `
    -ContentType "application/json" `
    -Body $body
  Write-Host "❌ FALHA: deveria ter retornado 422, retornou 201 com id=$($resp.id)"
} catch {
  $status = $_.Exception.Response.StatusCode.value__
  $body = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd()
  if ($status -eq 422) {
    Write-Host "✅ 422 esperado. Body:"
    Write-Host $body
  } else {
    Write-Host "❌ Status inesperado: $status (esperava 422)"
    Write-Host $body
  }
}
```

### Via curl

```bash
curl -sS -i -X POST \
  "https://api-vectraclip.vectracargo.com.br/api/companies/${COMPANY_ID}/tasks" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Smoke A.2 — operation_type inventado",
    "description": "Teste de validator catalog-driven rejeitando valor inexistente",
    "budgetLimit": 100,
    "operationType": "inventado_xyz_2026"
  }'

# Esperado: HTTP/1.1 422 Unprocessable Entity
```

### Resposta esperada

- **HTTP 422 Unprocessable Entity**
- Body inclui detalhe Pydantic com mensagem do validator:
  ```
  "unknown_operation_type: 'inventado_xyz_2026' (válidos: [..., ...])
   — adicione via UI /admin (operation_types_catalog) antes de usar"
  ```

### Critério de aceite

✅ Retorna 422 (não 201, não 500). Mensagem aponta como adicionar via UI.

---

## 4. Smoke 3 — Bypass do CHECK (valida que migration foi aplicada)

**Caso:** adicionar entry NOVA no catálogo + criar task usando essa entry. Antes da migration aplicada, isso falharia no banco (CHECK rejeitaria). Depois da migration, passa.

### Pré-condição

Migration `20260517120000_a2_drop_operation_type_checks.sql` aplicada no remoto.

### Passo 1 — Adicionar entry temporária no catálogo via SQL

```sql
INSERT INTO vectraclip.operation_types_catalog
  (id, name, category, description, is_active, display_order)
VALUES
  ('smoke-a2-temp', 'Smoke A.2 Temp', 'system',
   'Tipo temporário pra validar drop de CHECK. Remover após smoke.',
   true, 9990);
```

### Passo 2 — Aguardar cache do backend invalidar (≤60s)

`_load_operation_type_ids()` tem TTL 60s. Pode forçar refresh fazendo qualquer POST/PATCH primeiro.

### Passo 3 — Criar task com o novo type

```powershell
$body = @{
  title = "Smoke A.2 #3 — type novo recém-adicionado"
  description = "Antes do drop_operation_type_checks isso falharia com 23514 (CHECK)"
  budgetLimit = 100
  operationType = "smoke-a2-temp"
} | ConvertTo-Json

$resp = Invoke-RestMethod -Method POST `
  -Uri "https://api-vectraclip.vectracargo.com.br/api/companies/$COMPANY_ID/tasks" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body $body

Write-Host "✅ Task criada: $($resp.id) com operation_type novo"
```

### Passo 4 — Limpar

```sql
-- Apagar task de teste
DELETE FROM vectraclip.tasks WHERE operation_type = 'smoke-a2-temp';

-- Remover entry temporária do catálogo
DELETE FROM vectraclip.operation_types_catalog WHERE id = 'smoke-a2-temp';
```

### Critério de aceite

✅ POST retorna 201 (não 500 com erro Postgres 23514). Confirma que DROP CHECK foi aplicado.

❌ Se retornar 500 com `"violates check constraint tasks_operation_type_check"` → migration **não foi aplicada** (rodar `supabase db push`).

---

## 5. Handoff pra outro agente Claude (extensão / Code)

**Prompt copy-paste:**

```
Tarefa: Executar smoke do PR #184 (operation_type catalog-driven) do
vectraclaw-backend.

Spec completa: docs/SMOKE-A2-OPERATION-TYPE-CATALOG-DRIVEN.md no repo
vectraclaw-backend (cole o conteúdo se precisar).

Pré-requisitos:
1. Backend deploy ativo (curl /api/health = online)
2. Migration 20260517120000 aplicada (verificar via SQL — CI não aplica auto)
3. JWT válido (login via POST /api/auth/login com email+senha)

Executar nesta ordem:
1. Smoke 1: POST task com operationType='orchestration' → esperado 201
2. Smoke 2: POST task com operationType='inventado_xyz_2026' → esperado 422
3. Smoke 3 (opcional, requer migration aplicada): inserir entry temporária
   no catálogo + POST task usando ela + DELETE entry

Reportar:
- Status HTTP de cada smoke
- Body da resposta 422 (validar mensagem do validator)
- Se smoke 3 falhar 500 com "tasks_operation_type_check", reportar que
  migration não foi aplicada

NÃO fazer:
- Não rodar supabase db push (ação manual do Marcelo)
- Não criar tasks com operation_type fora dos 3 smokes
- Não deletar nada do catálogo real (apenas a entry 'smoke-a2-temp')
```

---

## 6. Checklist de aceitação consolidado

- [ ] §1.1 `/api/health` retorna `online`
- [ ] §1.2 `supabase migration list` confirma 20260517120000 aplicada
- [ ] §1.3 JWT capturado via login
- [ ] §2 Smoke 1: POST com `operationType='orchestration'` → 201 ✅
- [ ] §3 Smoke 2: POST com `operationType='inventado_xyz_2026'` → 422 ✅
- [ ] §4 Smoke 3 (opcional): bypass do CHECK funciona após migration

---

## 7. Pós-smoke — o que destrava

Se todos passam:

- ✅ A.2 entregue end-to-end
- ✅ Adicionar novo `operation_type` agora é INSERT no catálogo via UI `/admin` (zero PR Python, zero migration)
- ✅ Task #54 do tracking pode avançar pro próximo PR (A.3 — `_GEMINI_PRO_COST_PER_TOKEN` → `llm_models`)
- ✅ Memory `operation-type-three-lists` deixa de descrever débito ativo (vira histórico)

Se falham:

- Reportar HTTP exato + body + qual smoke
- Mais comum: backend cacheou catalog (aguardar 60s + retry) ou migration não aplicada (`supabase db push`)

---

## 8. Referências

- PR #184: https://github.com/Marcelo-Rosas/vectraclaw-backend/pull/184
- ADR §10 P10 + P13 (decisões cravadas 2026-05-17)
- `docs/CODE-PATTERNS.md` P1 — Regra de Ouro #2 (NO HARDCODE)
- `src/api.py:_load_operation_type_ids` + `_validate_operation_type` (helpers novos)
- `supabase/migrations/20260517120000_a2_drop_operation_type_checks.sql`
- `supabase/CLAUDE.md` — disciplina de migrations (NÃO usar `mcp apply_migration`)
