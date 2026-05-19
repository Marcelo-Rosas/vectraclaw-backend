# Daedalus — Agent Hiring Profile

> **Status**: Retrofit M1 do plano Brain → Daedalus (autopilot 2026-05-19).
> **Memory ref**: `feedback_agent_hiring_ritual` — Daedalus era ponta solta criada
> pré-ritual McKinsey. Este doc fecha a dívida.

---

## 1. Identidade

| Campo | Valor |
|---|---|
| **Nome** | Daedalus |
| **AGENT_ID** | `d4ed4145-0000-4000-8000-000000000005` (imutável) |
| **Role atual no DB** | `BPMN Process Modeler` |
| **Role pós-M1** | `Process Architect & Workflow Orchestrator` |
| **Daemon log** | `daemon-daedalus.log` |
| **Provider primário** | Gemini (R1 bloqueado hoje; fallback estatístico ativo) |
| **Provider fallback** | Statistical (sem LLM) |
| **Onboarding date** | PR F #158 (2026-05-XX) |
| **Hiring ritual** | M1 (este doc) — 2026-05-19 |

---

## 2. Mission

> **Materializar mapeamentos de processo em artefatos executáveis** — desde
> SIPOC textual até workflow rodando no daemon, garantindo aderência ao
> BPMN-Lite custom do VectraClaw (engine própria, sem Camunda).

Daedalus é a **ponte entre design e execução**. Quando o cliente terminou
de mapear no Oracle chat ou no editor BPMN, Daedalus traduz a intenção
visual em estrutura de dados que o agent_daemon consegue rodar.

---

## 3. Scope (RACI)

| Atividade | R | A | C | I |
|---|---|---|---|---|
| Gerar BPMN visual a partir de SIPOC | **D** | Athena | — | Cliente |
| Gerar BPMN visual a partir de texto livre | **D** | Athena | — | Cliente |
| Materializar BPMN em workflow_definitions + steps | **D** | Athena | Oracle (validation) | Cliente |
| Compilar system_prompt dinâmico do orchestrator | **D** (pós-M4) | Athena | — | Demais agentes |
| Bind de tools (`workflow_steps.ferramentas`) à task | **D** (pós-M4) | Athena | — | Agentes executores |
| Decisão de qual agente delega o step | **D** (pós-M4) | Morpheus (routing) | Athena (HR) | — |
| Monitoring de workflow_run em andamento | **D** (pós-PR4) | — | Heartbeat Doctor | Humano |
| Replan quando step falha 3x | **D** (pós-M4) | Athena | — | Humano |
| Validação BPMN (start único, gateways consistentes) | — | — | Oracle | **D** |
| Tracking financeiro de tokens consumidos | — | Athena HR | — | **D** |

**Resumindo**: Daedalus é **R** em tudo que materializa design → execução.
**A** quase sempre é Athena (HR + governance). **C** é quem precisa validar
nicho específico (Oracle pro SIPOC structure, Morpheus pro routing decision).

---

## 4. Specialties

Após M1, Daedalus tem 4 specialties registradas em `agent_specialty_configs`:

### 4.1 `bpmn-modeling` (existente — não muda)
- Operation types: `bpmn-generate`, `sipoc-to-bpmn`, `bpmn-approved-to-workflow`
- Output: row em `vectraclip.bpmn_diagrams`
- Estado: production-ready (fallback estatístico; LLM aguarda R1)

### 4.2 `workflow-orchestration` (M1)
- Operation types: `workflow-orchestrate-step`, `workflow-route-task`, `workflow-replan`
- Output: `vectraclip.tasks` (cria task filha pro agente delegado)
- Estado: stub até M4 implementar. Specialty registrada agora pra UI.

### 4.3 `tool-binding` (M1)
- Operation types: `bind-step-tools`
- Output: enrichment de `task.input_json.allowed_tools` antes do dispatch
- Estado: stub até W14.1 (tools_catalog) + M4 (dispatch hook) — depende de
  ambos.

### 4.4 `system-prompt-compilation` (M1)
- Operation types: `compile-orchestrator-prompt`
- Output: string compilada (não persiste DB — retornada na response)
- Estado: stub até M4. Substitui `src/services/brain/system_prompt.py` quando
  ativo.

---

## 5. Relationships (mapa interno)

```
        Cliente (humano)
              |
              v
  +-----------+-----------+
  | Oracle chat ─┐         |
  |              v         |
  |       SIPOC structure  |
  |              |         |
  |              v         |
  +---------> Daedalus ─────┐
                  |          |
                  | gera BPMN visual
                  v          |
              bpmn_diagrams  |
                  |          |
                  | materialize
                  v          |
        workflow_definitions |
        + workflow_steps     |
                  |          |
                  | orchestrate (M4)
                  v          |
        tasks (filhas) ──────+──> Morpheus (routing)
                                  Mercator (commercial)
                                  Plutus (financial)
                                  Hodos (logistics)
                                  Kronos (audit)
                                  Athena (PMO governance)
                                  HermesReporter (email)
                                  Hermes (inbox)
                                  Oracle (research)
```

**Upstream** (quem manda input pra Daedalus):
- Cliente humano via UI editor BPMN
- Oracle chat ao terminar SIPOC
- Athena ao aprovar Charter (PMBOK → workflow)

**Downstream** (quem Daedalus aciona):
- Cria tasks pra todos os 8 daemons executores via `workflow-route-task`
- Morpheus quando precisa de routing inteligente
- Athena HR pra approval de hire_agent (se workflow precisa de specialty
  inexistente)

**Peers** (consulta horizontal):
- Oracle (validar SIPOC structure antes de materialize)
- Morpheus (routing de task quando há múltiplos agentes possíveis)
- Heartbeat Doctor (alerta se step trava)

---

## 6. Metrics

| KPI | Threshold | Source |
|---|---|---|
| Tasks `bpmn-generate` succeeded rate | ≥ 90% | `tasks` count by status |
| Latência média `bpmn-generate` | < 30s (fallback) / < 60s (LLM) | task.created_at vs completed_at |
| Tokens consumidos médios | < 5k input + 2k output | heartbeats.tokens_per_second |
| Workflows materializados que rodaram com sucesso | ≥ 80% | join workflow_steps × tasks |
| Replans necessários por workflow | < 1.0 média | count `workflow-replan` por workflow_id |
| Aprovações pendentes (`hire_agent` solicitado) | — | approvals WHERE request_type='hire_agent' |

Coletado por Athena HR (memory `project_athena_hr_telemetry_optimization`).

---

## 7. Rollback rules

| Trigger | Ação automática | Ação humana |
|---|---|---|
| 3 tasks `bpmn-generate` consecutivas falhando | Pausa daemon Daedalus + cria incident | Investigar logs |
| LLM call latência > 60s | Fallback estatístico + warning na response | — |
| BPMN gerado tem ciclo no graph | Reject + cria task `bpmn-replan` | Editor humano |
| Workflow materializado tem 0 steps executáveis | Marca workflow_definition.is_active=false | Cliente revisa BPMN |
| > 50% tasks de um workflow falham em 24h | Pausa workflow + alerta humano | Decidir replan ou abort |

---

## 8. Aprovação

| Item | Status |
|---|---|
| Perfil escrito | ✅ (este doc) |
| Skills declaradas | ✅ (Seção 4) |
| RACI definido | ✅ (Seção 3) |
| Relacionamentos mapeados | ✅ (Seção 5) |
| Métricas + thresholds | ✅ (Seção 6) |
| Rollback rules | ✅ (Seção 7) |
| Marcelo aprova | ✅ "Aprovar agora" (autopilot 2026-05-19) |

**Hiring complete.** Memory `feedback_agent_hiring_ritual` cravado como ponta
solta — esta é a regularização.

---

## 9. Próximas frentes (post-M1)

| PR | O que entrega | Bloqueante |
|---|---|---|
| M3 | Migra workflow_aduaneiro pra DB + 5 catalogs cross-tenant + tools_catalog | Permite M4 ter dados pra orquestrar |
| W14.1 | tools_catalog seed | Pré-req M3 (subset incluído) |
| M4 | Daedalus orchestration loop (4 handlers novos: orchestrate-step, route-task, replan, compile-prompt) | M1 + M2 + M3 verdes |
| Workflow runs (PR separado) | `vectraclip.workflow_runs` table + UI monitoring | M4 verde |
| M5 | Aposenta Brain (deleta `src/services/brain/`) | M4 funcionando 1 semana |

---

## 10. Referências

- Memory `feedback_agent_hiring_ritual` (2026-05-17): cravou Daedalus como ponta solta
- Memory `project_athena_hr_telemetry_optimization`: Athena HR coleta métricas
- `docs/AUDITORIA-BRAIN-VS-DAEDALUS.md`: mapeamento das 3 responsabilidades migradas
- `docs/HANDOFF-BPMN-WORKFLOW-BRIDGE.md`: Phase 3 (já entregue PR #236)
- `docs/AUDITORIA-FERRAMENTAS-W14.md`: porque tools_catalog precisa existir
- `src/agents/daedalus.py`: handler atual
- `src/agent_ids.py:DAEDALUS_AGENT_ID`: SSOT do UUID
