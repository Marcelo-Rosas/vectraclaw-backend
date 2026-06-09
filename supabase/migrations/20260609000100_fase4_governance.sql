-- =============================================================================
-- FASE 4 — Governança e Ciclo de Melhoria (Telemetry + Athena Monitor + Approval Gate)
--
-- Contexto:
--   Fecha o loop DEMAIC com telemetria acumulada e recomendações Athena
--   baseadas em métricas reais de execução.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Amplia CHECK constraint de athena_recommendations.kind
--    Adiciona 'prompt_adjust' (informativo — sugere tweak no prompt de um agente
--    que está com baixa performance ou alto custo por token).
-- -----------------------------------------------------------------------------
ALTER TABLE vectraclip.athena_recommendations
    DROP CONSTRAINT IF EXISTS athena_recommendations_kind_check;

ALTER TABLE vectraclip.athena_recommendations
    ADD CONSTRAINT athena_recommendations_kind_check
    CHECK (kind = ANY (ARRAY[
        -- Executáveis (Athena auto-aplica após aprovação humana)
        'hire_new_agent'::text,
        'add_specialty'::text,
        'rewrite_system_prompt'::text,
        'create_specialty'::text,
        'consolidate_agents'::text,
        -- Informativos (Athena só reporta; humano decide)
        'diagnose_gap'::text,
        'suggest_automation'::text,
        'suggest_hire_agent'::text,
        'prompt_adjust'::text
    ]));

COMMENT ON COLUMN vectraclip.athena_recommendations.kind IS
    'Tipo da recomendação Athena. EXECUTÁVEIS: hire_new_agent, add_specialty, rewrite_system_prompt, create_specialty, consolidate_agents. INFORMATIVOS: diagnose_gap, suggest_automation, suggest_hire_agent, prompt_adjust.';

-- -----------------------------------------------------------------------------
-- 2. Views de Telemetry Aggregation
-- -----------------------------------------------------------------------------

-- 2.1 cost_by_workflow — custo total (tasks + heartbeats) por workflow_definition
CREATE OR REPLACE VIEW vectraclip.cost_by_workflow AS
SELECT
    wd.id AS workflow_definition_id,
    wd.slug AS workflow_slug,
    wd.name AS workflow_name,
    wd.goal_id,
    COUNT(t.id) AS total_tasks,
    SUM(COALESCE(t.cost_usd, 0)) AS tasks_cost_usd,
    SUM(COALESCE(hb.heartbeat_cost_usd, 0)) AS heartbeats_cost_usd,
    SUM(COALESCE(t.cost_usd, 0)) + SUM(COALESCE(hb.heartbeat_cost_usd, 0)) AS total_cost_usd,
    AVG(COALESCE(t.cost_usd, 0)) AS avg_task_cost_usd,
    COUNT(CASE WHEN t.status = 'done' THEN 1 END) AS completed_tasks,
    COUNT(CASE WHEN t.status = 'blocked' THEN 1 END) AS blocked_tasks,
    COUNT(CASE WHEN t.status = 'errored' THEN 1 END) AS errored_tasks
FROM vectraclip.workflow_definitions wd
LEFT JOIN vectraclip.tasks t ON t.workflow_definition_id = wd.id
LEFT JOIN (
    SELECT task_id, SUM(COALESCE(cost_usd, 0)) AS heartbeat_cost_usd
    FROM vectraclip.heartbeats
    WHERE task_id IS NOT NULL
    GROUP BY task_id
) hb ON hb.task_id = t.id
GROUP BY wd.id, wd.slug, wd.name, wd.goal_id;

-- 2.2 cost_by_goal — custo total (tasks + heartbeats) por goal
CREATE OR REPLACE VIEW vectraclip.cost_by_goal AS
SELECT
    g.id AS goal_id,
    g.title AS goal_title,
    g.company_id,
    COUNT(t.id) AS total_tasks,
    SUM(COALESCE(t.cost_usd, 0)) AS tasks_cost_usd,
    SUM(COALESCE(hb.heartbeat_cost_usd, 0)) AS heartbeats_cost_usd,
    SUM(COALESCE(t.cost_usd, 0)) + SUM(COALESCE(hb.heartbeat_cost_usd, 0)) AS total_cost_usd,
    COUNT(CASE WHEN t.status = 'done' THEN 1 END) AS completed_tasks,
    COUNT(CASE WHEN t.status = 'blocked' THEN 1 END) AS blocked_tasks
FROM vectraclip.goals g
LEFT JOIN vectraclip.tasks t ON t.goal_id = g.id
LEFT JOIN (
    SELECT task_id, SUM(COALESCE(cost_usd, 0)) AS heartbeat_cost_usd
    FROM vectraclip.heartbeats
    WHERE task_id IS NOT NULL
    GROUP BY task_id
) hb ON hb.task_id = t.id
GROUP BY g.id, g.title, g.company_id;

-- 2.3 sla_compliance_by_step — cumprimento de SLA por workflow_step
CREATE OR REPLACE VIEW vectraclip.sla_compliance_by_step AS
SELECT
    ws.id AS workflow_step_id,
    ws.slug AS step_slug,
    ws.name AS step_name,
    ws.sla_horas,
    wd.id AS workflow_definition_id,
    wd.slug AS workflow_slug,
    COUNT(t.id) AS total_tasks,
    COUNT(CASE WHEN t.status = 'done' THEN 1 END) AS completed_tasks,
    AVG(
        EXTRACT(EPOCH FROM (COALESCE(t.approved_at, t.updated_at) - t.claimed_at)) / 3600.0
    ) FILTER (WHERE t.status = 'done' AND t.claimed_at IS NOT NULL) AS avg_completion_hours,
    COUNT(CASE
        WHEN t.status = 'done'
            AND ws.sla_horas IS NOT NULL
            AND t.claimed_at IS NOT NULL
            AND EXTRACT(EPOCH FROM (COALESCE(t.approved_at, t.updated_at) - t.claimed_at)) / 3600.0 <= ws.sla_horas
        THEN 1
    END) AS sla_met_count,
    CASE
        WHEN COUNT(CASE WHEN t.status = 'done' THEN 1 END) > 0
        THEN COUNT(CASE
            WHEN t.status = 'done'
                AND ws.sla_horas IS NOT NULL
                AND t.claimed_at IS NOT NULL
                AND EXTRACT(EPOCH FROM (COALESCE(t.approved_at, t.updated_at) - t.claimed_at)) / 3600.0 <= ws.sla_horas
            THEN 1
        END) * 100.0 / COUNT(CASE WHEN t.status = 'done' THEN 1 END)
        ELSE NULL
    END AS sla_compliance_pct
FROM vectraclip.workflow_steps ws
JOIN vectraclip.workflow_definitions wd ON wd.id = ws.workflow_id
LEFT JOIN vectraclip.tasks t ON t.workflow_step_id = ws.id
GROUP BY ws.id, ws.slug, ws.name, ws.sla_horas, wd.id, wd.slug;

-- -----------------------------------------------------------------------------
-- 3. Índices auxiliares para as views (garantem performance em bases grandes)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tasks_workflow_definition_id_status
    ON vectraclip.tasks (workflow_definition_id, status)
    WHERE workflow_definition_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_heartbeats_task_id_cost
    ON vectraclip.heartbeats (task_id, cost_usd)
    WHERE task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_workflow_step_id_claimed
    ON vectraclip.tasks (workflow_step_id, claimed_at)
    WHERE workflow_step_id IS NOT NULL;
