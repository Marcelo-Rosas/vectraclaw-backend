-- Migration: Função atômica para acúmulo de custo em tasks
-- Issue: VEC-202
-- Motivo: o padrão read-modify-write no Python tem race condition com múltiplos workers.
-- Esta função garante UPDATE atômico no banco sem janela de concorrência.

CREATE OR REPLACE FUNCTION vectraclip.increment_task_cost(
    p_task_id UUID,
    p_delta    NUMERIC
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
AS $$
    UPDATE vectraclip.tasks
       SET cost_usd    = COALESCE(cost_usd, 0) + p_delta,
           updated_at  = now()
     WHERE id = p_task_id;
$$;

REVOKE ALL ON FUNCTION vectraclip.increment_task_cost(UUID, NUMERIC) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION vectraclip.increment_task_cost(UUID, NUMERIC) TO service_role;
