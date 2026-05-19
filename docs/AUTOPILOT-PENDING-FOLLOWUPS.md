# Autopilot Pending Followups

> Lista operacional de itens **encontrados durante autopilot mas pulados** com justificativa. Não duplica `MEMORY.md` (que é conhecimento persistente). Aqui é fila de TODOs descobertos.

**Iniciado**: 2026-05-18 23:08 BRT

---

## Itens descobertos

### F-006 — PR2 expandiu pra 4 sub-PRs (auditor GO COM AJUSTES)

**Descoberto em**: PR2 pre-audit (00:18 BRT 2026-05-19, agente `a778cf6d57ef076a5`)
**Severidade**: P1 (não bloqueia, mas precisa decisão sua antes de codar)
**Detalhe**: Auditor cravou **GO COM AJUSTES** com 1 P0 + 2 P1 + 2 P2 + 1 órfão. Resolvendo via SQL as 3 perguntas humanas do auditor:
- ✅ **RLS multi-tenant**: COBERTO (4 policies em sipoc_processes via JOIN `sipoc_sectors.company_id = sipoc_company_id()`)
- ⚠️ **sipoc_processes.status sem CHECK**: confirmado — só existe CHECK em `sipoc_components.automation_status`
- ⚠️ **sipoc_components.type sem CHECK**: confirmado; `sipoc_taxonomy_global` é catalog de activities (atributos), não de types (activity/supplier/input/output/customer)
- ✅ **sipoc_drafts NÃO EXISTE**: doc `src/services/CLAUDE.md:65` ainda menciona, gap doc

**Sub-PRs propostos** (pra Marcelo decidir):

**PR2.1 — Migration prévia (DDL pure)**
- Migration `supabase/migrations/<ts>_sipoc_constraints.sql`:
  ```sql
  ALTER TABLE vectraclip.sipoc_processes
    ADD CONSTRAINT sipoc_processes_status_check
    CHECK (status IS NULL OR status = ANY (ARRAY['rascunho','em_revisao','aprovado']));
  -- OPÇÃO A: CHECK simples
  ALTER TABLE vectraclip.sipoc_components
    ADD CONSTRAINT sipoc_components_type_check
    CHECK (type = ANY (ARRAY['activity','supplier','input','output','customer']));
  -- OPÇÃO B: catalog cross-tenant sipoc_component_types(slug, name, ordinal) + FK
  -- (mais aderente à Regra de Ouro #2 — UI consegue editar; CHECK não)
  ```
- **Decisão pendente Marcelo**: Opção A (CHECK rígido) vs B (catalog)? Recomendação: **B** se houver chance de adicionar `decision_point` ou `event` futuramente. **A** se SIPOC PMI é fixo pra sempre.

**PR2.2 — SSOT 5W2H keys (refactor)**
- Criar `src/services/sipoc_5w2h_keys.py` com `CANONICAL_KEYS = ("what","why","when","where","who","how","how_much")` snake_case
- Refator `src/agents/oracle.py:64` (atualmente `"howMuch"` camelCase)
- Refator `src/api_routes/sipoc_diagnose.py:32` (já snake_case mas valida via import central)
- **Decisão pendente Marcelo**: snake_case (recomendado, alinha DB) vs camelCase (alinha frontend JS)?

**PR2.3 — Endpoint commit (feature principal)**
- `src/api_routes/sipoc_commit.py` novo arquivo: `POST /api/sipoc/sessions/{session_id}/commit`
- Body: `{sector_id, owner_position_id?, name?}` (company_id resolvido via JOIN sipoc_sectors, NÃO vem do body)
- Service `src/services/sipoc_commit_service.py`:
  1. Resolver `company_id` via `SELECT sipoc_sectors WHERE id=sector_id` + cruzar com `request.state.company_id`
  2. Ler `_OracleSession.sipoc_snapshot` + `collected_5w2h`
  3. INSERT sipoc_processes (status='rascunho', sector_id, name, responsible_id=owner_position_id)
  4. Loop INSERT sipoc_components (process_id, type, content jsonb com 5W2H canonical, order, responsible_position_id, suggested_operation_type só se existir em `operation_types_catalog`)
  5. Loop INSERT sipoc_raci se snapshot tiver responsible_positions válidas em sipoc_positions
  6. Mark session.committed=True (in-memory)
  7. Retornar `{process_id, components_created, raci_created, warnings}`
- Pydantic input/output em `src/models.py`
- UI mínima VectraClip: botão "Materializar SIPOC" no chat Oracle (PR2.4)

**PR2.4 — UI mínima + doc fix**
- VectraClip: botão "Materializar SIPOC" + toast de sucesso + redirect pra `/sipoc/sectors/{sector_id}/processes/{new_process_id}`
- Fix `src/services/CLAUDE.md:65`: remover menção a `sipoc_drafts` (não existe, confunde quem ler)

**Riscos especificados pelo auditor**:
- FK `sipoc_raci.position_id` viola se snapshot tem position UUID que não existe em DB → validar antes em batch
- FK `sipoc_components.suggested_operation_type` viola se op_type não está em `operation_types_catalog` → SET NULL ou validar antes
- `generate_audit_log` órfão em `sipoc_approvals.py:17` — candidato a deletar em sweep separado

**Estado autopilot**: SUSPENSO até Marcelo decidir Opção A/B do PR2.1 + naming PR2.2.

---

### F-005 — Auditor outdated 2x — PR1 goal_classifications JÁ EXISTE

**Descoberto em**: PR1 setup (00:05 BRT 2026-05-19)
**Severidade**: P2 (padrão preocupante — auditor lê snapshot velho)
**Detalhe**: Relatório quíntuplo do `hardcode-orphan-auditor` indicou PR1 = "migration goal_classifications Heldman". Mirror antes de criar (Regra #1) revelou:
- `goal_kinds` table catalog cross-tenant 6 rows EXISTE (W2A AUDIT-007)
- `business_case_strengths` table catalog 5 rows EXISTE (W2A AUDIT-007)
- FK `goals.kind → goal_kinds.slug` EXISTE (`goals_kind_fk`)
- FK `goals.business_case_strength → business_case_strengths.slug` EXISTE (`goals_business_case_strength_fk`)
- `_handle_classify` em `src/agents/athena.py:133-340` é IMPLEMENTAÇÃO REAL (não stub) — escreve em goals.kind/confidence/business_case_strength/pmoia_metadata/classified_at
- Histórico de classificações implícito via `tasks WHERE operation_type='athena-classify' AND input_json->>'goal_id'=X ORDER BY created_at`

**Padrão emergente** (2 ocorrências hoje):
- F-001: auditor disse daedalus sem `execute_specialty` → existia em daedalus.py:317
- F-005: auditor pediu migration `goal_classifications` → já existe há semanas (Wave 2A AUDIT-007)

Hipótese: invocações de `hardcode-orphan-auditor` na sessão anterior usaram dump de schema antigo (talvez de antes do W2A merge). Recomendação **pra Marcelo manhã**: forçar auditor a fazer `mcp__plugin_supabase_supabase__list_tables` ANTES de qualquer roadmap.

**Ação**: PR1 vira no-op (igual PR0a). Autopilot pula pra PR2.

---

### F-001 — Auditor outdated sobre H2/B1 Daedalus ImportError

**Descoberto em**: PR0a setup
**Severidade**: P2 (anotação)
**Detalhe**: Relatório do hardcode-orphan-auditor (5a invocação 2026-05-18) identificou H2/B1 como `ImportError silencioso` porque `agent_daemon.py:631` faz `from src.agents.daedalus import execute_specialty as daedalus_execute` mas `daedalus.py` "só tem `entrypoint`". Verificação pós-leitura mostrou que **`daedalus.py:317` JÁ TEM `async def execute_specialty(task, supabase)`** (alias correto via `asyncio.to_thread`). H2/B1 invalidado.

**Hipótese real do "0 BPMNs em prod"**: ausência de `operation_types` array em `agent_specialty_configs.values` do Daedalus. Lookup de specialty por operation_type retorna NULL → Daedalus nunca é matched. PR0b resolve.

**Ação**: nenhuma — apenas registro pra futura invocação do auditor não repetir o falso positivo.

### F-004 — Docker Desktop filesystem corrompido — RESOLVIDO 23:42 BRT

**Recovery executado** após Marcelo cravar "FAÇA UM FORCE" + agente `docker-hang-troubleshooter` Plano A:
1. taskkill /F /IM docker.exe (ghosts CLI)
2. wsl --shutdown × 2
3. Stop-Process Docker Desktop + relança
4. Aguardar Docker daemon (~10s)
5. Containers auto-start (Up 15s)
6. Aguardar health (~70s pra backend healthy)
7. docker cp morpheus_inbound_triage.py × 2 containers
8. docker compose restart backend daemon
9. Smoke OK: local + tunnel + PR0e import

Volume `nous-hermes-config` preservado. PR0e agora ATIVO em prod (Morpheus retorna output_text amigável).

**Lição registrada em memória**: Plano A do agente `docker-hang-troubleshooter` (taskkill + wsl --shutdown + relança Docker Desktop UI) é safe-recovery quando overlayfs do WSL2 corrompe. NÃO usar Reset to Factory Defaults (destrói volumes).

---

### F-004-ORIG — Docker Desktop filesystem corrompido (overlayfs I/O error) — PROD DOWN

**Descoberto em**: pós-merge PR0e (cp + restart containers)
**Severidade**: P0 (prod red)
**Detalhe**: `docker compose restart` falhou com:
```
chown /var/lib/docker/containers/.../resolv.conf: read-only file system
readdirent /var/lib/desktop-containerd/.../overlayfs/snapshots/5645/fs: input/output error
```

Backend container reporta "Up 3 hours (healthy)" no `docker ps` mas:
- `curl localhost:3100/api/health` → "máquina recusou conexão"
- `curl https://api-vectraclip.vectracargo.com.br/api/health` → timeout 8s
- `docker compose up -d backend` → "exited (137)"

Containers vivos no metadata mas processo dentro morto + Docker FS corrupto impede restart limpo.

**Causa provável**: WSL2 overlayfs corruption (disco cheio? crash forçado? bug Docker Desktop?)

**NÃO causado por PR0e** — PR é apenas Python edit em morpheus_inbound_triage. Coincidência de timing.

**Daemons HOST OK** (11 pythonw + 11 locks, Morpheus com PR0e ativo). Polling de tasks continua. Mas inbound Meta WhatsApp não funciona (chega via tunnel → backend container → 503).

**Ação Marcelo (manhã)**: 
1. Tentar `wsl --shutdown` + restart Docker Desktop
2. Se persistir: Docker Desktop → Troubleshoot → Reset to factory defaults
3. Pior caso: reboot Windows
4. Após Docker voltar: `docker compose up -d` + verificar healthy + reaplicar PR0e cp (apenas src/agents/morpheus_inbound_triage.py)
5. Smoke: WhatsApp inbound deve retornar texto amigável (PR0e ativo) em vez de JSON cru

**AUTOPILOT SUSPENSO** após este incidente. PRs PR1+ NÃO iniciados. PR0a/0b/0c/0d/0e status: 0b+0e mergeados e aplicáveis quando Docker voltar; 0a no-op confirmado; 0c aguardando dono BPMN; 0d aguarda 0e estável em prod.

---

### F-003 — Sprint BPMN VectraClip ~95% pronto MAS dono em sessão ativa

**Descoberto em**: PR0c investigação (Explore agent)
**Severidade**: P1 (não bloqueia MVP CFN)
**Detalhe**: VectraClip tem 16 arquivos untracked + 6 modified que formam o sprint BPMN completo (PR-1 + PR-2 do `docs/PLANO-BPMN-MODELER-CLIP.md`). **mtime de BpmnCanvas.tsx é ~10min atrás** — sugere dono em sessão ativa. Build quebra se commit parcial (App.tsx já referencia páginas untracked).

**Mapeamento**:
- 16 arquivos BPMN: pages/Bpmn.tsx + pages/BpmnEditor.tsx + components/bpmn/* + lib/api/endpoints/bpmnDiagrams.ts + lib/queries/bpmnDiagrams.ts + types/bpmn.ts
- 6 wire files: App.tsx + Sidebar + MainLayout + queries/keys + package.json + mocks/handlers
- 1 arquivo obsoleto: pages/BpmnEditorPlaceholder.tsx
- 0 TODO/FIXME (código production-ready)
- 0 testes unitários

**Ação autopilot**: **NÃO commitar** durante autopilot — memory `multi-session-coordination` cravou que paralelismo exige pausar. Aguardar dono terminar sprint. PR0c (wire `/bpmn/new`) fica resolvido AUTOMATICAMENTE quando dono commitar o sprint inteiro.

**PR0c removido do bloqueio MVP CFN** (auditor já cravou que bloqueantes são PR0+PR1+PR2+PR4+PR5, sem PR0c).

---

### F-002 — Morpheus inbound_triage envia JSON cru pro WhatsApp (PR0e do roadmap)

**Descoberto em**: teste autopilot PDF (Marcelo recebeu JSON serializado após mandar feedback do PDF)
**Severidade**: P1
**Detalhe**: `src/agents/morpheus_inbound_triage.entrypoint` retorna `{status, output_json}` sem `output_text`. Hook `agent_daemon._maybe_reply_to_connector_session` (PR #225) tem fallback que envia JSON serializado quando `output_text` ausente. Resultado: Marcelo recebe `{"status":"done","output_json":{"child_task_id":"...","target_operation_type":"human-triage","fallback_used":true}}` no WhatsApp.

**Evidência**: `connector_sessions` id `2bb7223b-5a76-408c-9168-ded48282a0d7` pos 22, 25, 26 em prod.

**Ação**: incluído como PR0e no roadmap (task #98). Fix: adicionar `output_text` amigável em morpheus_inbound_triage quando rule não casa (ex: "Recebi sua mensagem! Vou direcionar pro time humano e em breve responderão"). Cobertura ampla: revisar TODOS handlers do roadmap PR0-PR8 garantindo `output_text` sempre presente.

---

*Itens vão sendo adicionados conforme autopilot encontra.*
