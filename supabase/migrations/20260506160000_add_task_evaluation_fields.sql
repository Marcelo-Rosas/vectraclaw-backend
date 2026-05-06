-- VEC-Semana-2: campos de avaliação por task.
-- Permite que o agente (após concluir), um humano (na revisão) ou um job
-- automatizado registrem score 1-5 + notas + autor da avaliação.
-- Os 4 campos são nullable: tasks antigas continuam válidas sem reprocessamento.
--
-- evaluated_by: 'agent' (auto-avaliação ao concluir), 'human' (revisor),
--               'auto' (job de qualidade que avalia em batch).

ALTER TABLE vectraclip.tasks
  ADD COLUMN IF NOT EXISTS evaluation_score integer
    CHECK (evaluation_score IS NULL OR (evaluation_score BETWEEN 1 AND 5));

ALTER TABLE vectraclip.tasks
  ADD COLUMN IF NOT EXISTS evaluation_notes text;

ALTER TABLE vectraclip.tasks
  ADD COLUMN IF NOT EXISTS evaluated_by text
    CHECK (evaluated_by IS NULL OR evaluated_by IN ('agent', 'human', 'auto'));

ALTER TABLE vectraclip.tasks
  ADD COLUMN IF NOT EXISTS evaluated_at timestamptz;

COMMENT ON COLUMN vectraclip.tasks.evaluation_score IS
  'Score de qualidade da execução (1=ruim, 5=excelente). NULL = não avaliada.';
COMMENT ON COLUMN vectraclip.tasks.evaluation_notes IS
  'Justificativa textual da avaliação. Útil para auditoria e calibração.';
COMMENT ON COLUMN vectraclip.tasks.evaluated_by IS
  'Origem da avaliação: agent (auto-avaliação ao concluir), human (revisor), auto (job batch).';
COMMENT ON COLUMN vectraclip.tasks.evaluated_at IS
  'Timestamp da avaliação. Pode ser >= updated_at quando reavaliação ocorre.';

-- Índice parcial: foco em tasks já avaliadas (filtros do dashboard /evaluation).
CREATE INDEX IF NOT EXISTS tasks_evaluated_idx
  ON vectraclip.tasks (company_id, evaluated_at DESC, evaluation_score)
  WHERE evaluation_score IS NOT NULL;
