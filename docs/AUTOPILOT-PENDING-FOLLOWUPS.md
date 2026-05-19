# Autopilot Pending Followups

> Lista operacional de itens **encontrados durante autopilot mas pulados** com justificativa. Não duplica `MEMORY.md` (que é conhecimento persistente). Aqui é fila de TODOs descobertos.

**Iniciado**: 2026-05-18 23:08 BRT

---

## Itens descobertos

### F-001 — Auditor outdated sobre H2/B1 Daedalus ImportError

**Descoberto em**: PR0a setup
**Severidade**: P2 (anotação)
**Detalhe**: Relatório do hardcode-orphan-auditor (5a invocação 2026-05-18) identificou H2/B1 como `ImportError silencioso` porque `agent_daemon.py:631` faz `from src.agents.daedalus import execute_specialty as daedalus_execute` mas `daedalus.py` "só tem `entrypoint`". Verificação pós-leitura mostrou que **`daedalus.py:317` JÁ TEM `async def execute_specialty(task, supabase)`** (alias correto via `asyncio.to_thread`). H2/B1 invalidado.

**Hipótese real do "0 BPMNs em prod"**: ausência de `operation_types` array em `agent_specialty_configs.values` do Daedalus. Lookup de specialty por operation_type retorna NULL → Daedalus nunca é matched. PR0b resolve.

**Ação**: nenhuma — apenas registro pra futura invocação do auditor não repetir o falso positivo.

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
