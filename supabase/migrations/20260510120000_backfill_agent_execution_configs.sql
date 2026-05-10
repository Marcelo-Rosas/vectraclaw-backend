-- =============================================================================
-- 20260510120000_backfill_agent_execution_configs
-- =============================================================================
--
-- Garante que TODO agent ativo tem uma row em vectraclip.agent_execution_configs.
-- Sem isso, GET /api/agents/{id}/execution-config dava 404 e o frontend
-- (AgentExecutionCard) não conseguia abrir a tela do agente.
--
-- Causa: agentes-sistema (Morpheus, Mnemos, Kronos, HermesReporter) foram
-- criados via seed/migration sem inserir a row de execution_config. Em paralelo,
-- _persist_agent_atomic() em src/api.py também tem bug (insere em colunas
-- inexistentes 'cron_expression' e 'timezone') e captura o erro silenciosamente,
-- mas isso é tratado em PR separado.
--
-- Estratégia: INSERT idempotente baseado em NOT EXISTS — pega QUALQUER agent
-- sem row, não só os 4 conhecidos hoje. Backfill seguro de re-rodar (no-op).
-- Default = REALTIME ativo, trigger_config vazio.
-- =============================================================================

INSERT INTO vectraclip.agent_execution_configs
  (company_id, agent_id, execution_mode, trigger_config, is_active)
SELECT a.company_id, a.id, 'REALTIME', '{}'::jsonb, true
FROM vectraclip.agents a
WHERE NOT EXISTS (
  SELECT 1 FROM vectraclip.agent_execution_configs ec
  WHERE ec.agent_id = a.id
)
ON CONFLICT (agent_id) DO NOTHING;
