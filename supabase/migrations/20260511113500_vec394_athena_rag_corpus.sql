-- =============================================================================
-- VEC-394 — Athena RAG corpus dedicado: athena_documents + athena_chunks
-- =============================================================================
-- Continuação natural de VEC-388 PR1 (boot skeleton da Athena). Cria infra
-- RAG ISOLADA do corpus Mnemos (`vectraclip.rag_documents`/`rag_chunks`).
--
-- Decisão arquitetural (ADR-002): corpus completamente separado por agente.
-- Reusa pipeline `extractor`/`chunker`/`OpenAIEmbedder` mas com schema próprio.
--
-- Storage bucket esperado: 'athena-rag' (auto-provision via RAG_AUTO_PROVISION
-- na primeira upload). Path convention: {company_id}/{sha256}.{ext}
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;


-- ─────────────────────────────────────────────────────────────────────────────
-- ENUM reusado: vectraclip.rag_doc_status (criado em vec_rag_corpus.sql).
-- Athena não precisa de status próprio — ciclo de ingestão é idêntico.
-- ─────────────────────────────────────────────────────────────────────────────


-- ─────────────────────────────────────────────────────────────────────────────
-- vectraclip.athena_documents — origem dos chunks Heldman/PMBOK
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vectraclip.athena_documents (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,
  filename      text NOT NULL,
  storage_path  text NOT NULL,
  sha256        text NOT NULL,
  mime_type     text,
  size_bytes    bigint,
  page_count    integer,
  status        vectraclip.rag_doc_status NOT NULL DEFAULT 'uploaded',
  error_detail  text,
  ingest_task_id uuid,
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  uploaded_by   uuid,
  uploaded_at   timestamptz NOT NULL DEFAULT now(),
  indexed_at    timestamptz,
  CONSTRAINT athena_documents_company_sha256_unique UNIQUE (company_id, sha256)
);

CREATE INDEX IF NOT EXISTS athena_documents_company_status_idx
  ON vectraclip.athena_documents (company_id, status);

CREATE INDEX IF NOT EXISTS athena_documents_uploaded_at_idx
  ON vectraclip.athena_documents (uploaded_at DESC);

COMMENT ON TABLE vectraclip.athena_documents IS
  'Athena RAG: documento fonte (PDF/TXT/HTML/JSON/XLSX) per-tenant. Corpus PMBOK/Heldman isolado do rag_documents do Mnemos.';
COMMENT ON COLUMN vectraclip.athena_documents.sha256 IS
  'SHA-256 do conteúdo binário. UNIQUE per-tenant — re-upload do mesmo arquivo retorna o registro existente.';
COMMENT ON COLUMN vectraclip.athena_documents.storage_path IS
  'Caminho no bucket Storage athena-rag. Convenção: {company_id}/{sha256}.{ext}';


-- ─────────────────────────────────────────────────────────────────────────────
-- vectraclip.athena_chunks — segmentos indexáveis com embedding (1536-dim)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vectraclip.athena_chunks (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id   uuid NOT NULL REFERENCES vectraclip.athena_documents(id) ON DELETE CASCADE,
  company_id    uuid NOT NULL,
  chunk_index   integer NOT NULL,
  page_number   integer,
  content       text NOT NULL,
  token_count   integer,
  embedding     vector(1536) NOT NULL,
  embedding_model text NOT NULL DEFAULT 'text-embedding-3-small',
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT athena_chunks_doc_index_unique UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS athena_chunks_embedding_hnsw
  ON vectraclip.athena_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS athena_chunks_company_idx
  ON vectraclip.athena_chunks (company_id);

CREATE INDEX IF NOT EXISTS athena_chunks_document_idx
  ON vectraclip.athena_chunks (document_id);

COMMENT ON TABLE vectraclip.athena_chunks IS
  'Athena RAG: segmento indexado com embedding (1536-dim). Cosine via <=> operator + HNSW index. Isolado de rag_chunks.';
COMMENT ON COLUMN vectraclip.athena_chunks.company_id IS
  'Denormalizado de athena_documents para RLS sem JOIN. Trigger sync_athena_chunk_company_id mantém consistência.';


-- ─────────────────────────────────────────────────────────────────────────────
-- Trigger: sync_athena_chunk_company_id
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION vectraclip.sync_athena_chunk_company_id()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  SELECT company_id INTO NEW.company_id
  FROM vectraclip.athena_documents
  WHERE id = NEW.document_id;
  IF NEW.company_id IS NULL THEN
    RAISE EXCEPTION 'athena_chunks: document_id % não encontrado em athena_documents', NEW.document_id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_athena_chunk_company_id ON vectraclip.athena_chunks;
CREATE TRIGGER sync_athena_chunk_company_id
  BEFORE INSERT OR UPDATE OF document_id ON vectraclip.athena_chunks
  FOR EACH ROW
  EXECUTE FUNCTION vectraclip.sync_athena_chunk_company_id();


-- ─────────────────────────────────────────────────────────────────────────────
-- RLS — espelhada de rag_documents/rag_chunks (PR #18)
-- SELECT: authenticated da mesma company OU service_role
-- INSERT/UPDATE/DELETE: service_role apenas (daemon ingestor)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE vectraclip.athena_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.athena_chunks    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS athena_documents_select_own ON vectraclip.athena_documents;
CREATE POLICY athena_documents_select_own ON vectraclip.athena_documents
  FOR SELECT TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS athena_documents_service_role_all ON vectraclip.athena_documents;
CREATE POLICY athena_documents_service_role_all ON vectraclip.athena_documents
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS athena_chunks_select_own ON vectraclip.athena_chunks;
CREATE POLICY athena_chunks_select_own ON vectraclip.athena_chunks
  FOR SELECT TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS athena_chunks_service_role_all ON vectraclip.athena_chunks;
CREATE POLICY athena_chunks_service_role_all ON vectraclip.athena_chunks
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────────
-- Grants explícitos para PostgREST
-- ─────────────────────────────────────────────────────────────────────────────
GRANT SELECT ON vectraclip.athena_documents TO authenticated;
GRANT SELECT ON vectraclip.athena_chunks    TO authenticated;
GRANT ALL    ON vectraclip.athena_documents TO service_role;
GRANT ALL    ON vectraclip.athena_chunks    TO service_role;


NOTIFY pgrst, 'reload schema';
