-- A.2 do ADR Fase A (decidido P10/P13 — 2026-05-17): aposenta validação
-- hardcoded de `operation_type` em CHECK constraints.
--
-- ANTES: validação dupla (Pydantic Literal[...] em models.py + DB CHECK aqui).
-- Toda adição de operation_type novo exigia 3 PRs sincronizados (Pydantic + CHECK
-- + handler de dispatch). Memory `operation-type-three-lists` documenta o problema.
--
-- DEPOIS: validação única catalog-driven via `_validate_operation_type()` em
-- src/api.py (lookup cacheado 60s contra `vectraclip.operation_types_catalog`).
-- Novo operation_type = INSERT no catálogo via UI /admin (sem migration, sem PR).
-- Regra de ouro #2 (NO HARDCODE) — `docs/CODE-PATTERNS.md` P1.
--
-- Dispatch nos daemons (`agent_daemon.py if op_type ==`, `_SPECIALTY_DISPATCH`
-- em `athena.py`) continua hardcoded — é roteamento de handler, NÃO validação.
-- Adicionar op_type novo sem handler = task fica em queued sem dispatch (esperado).
--
-- Risco operacional: ~zero. Pydantic + cache do catálogo já validam antes do
-- INSERT chegar no DB. Tipos inválidos retornam 422 (Pydantic) antes do SQL.

ALTER TABLE vectraclip.tasks
  DROP CONSTRAINT IF EXISTS tasks_operation_type_check;

ALTER TABLE vectraclip.routines
  DROP CONSTRAINT IF EXISTS routines_operation_type_check;

COMMENT ON COLUMN vectraclip.tasks.operation_type IS
  'Catalog-driven (vectraclip.operation_types_catalog.id). Validação em src/api.py:_validate_operation_type. Sem CHECK desde A.2 do ADR Fase A (2026-05-17).';

COMMENT ON COLUMN vectraclip.routines.operation_type IS
  'Catalog-driven (vectraclip.operation_types_catalog.id). Validação em src/api.py:_validate_operation_type. Sem CHECK desde A.2 do ADR Fase A (2026-05-17).';
