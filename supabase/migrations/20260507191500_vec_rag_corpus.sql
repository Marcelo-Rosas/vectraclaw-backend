-- =============================================================================
-- VEC-359 (Step 10) — RAG corpus: documents + chunks com pgvector
-- =============================================================================
-- Fundação do RAG nativo do VectraClaw. Substitui o RAG PHP standalone
-- (C:\Users\marce\VectraClaw\RAG\AGENTE RAG\rag-php) por uma stack:
--   • multi-tenant via company_id + RLS
--   • chunking com citação (page_number + chunk_index)
--   • busca via pgvector HNSW (substitui cosineSimilarity em PHP em memória)
--   • async ingestion via vectraclip.tasks (operation_type='rag-ingest')
--
-- Storage bucket esperado: 'rag-documents' (criar via dashboard ou
-- supabase storage create-bucket; este migration NÃO cria o bucket).
-- Path convention: {company_id}/{sha256}.{ext}
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;


-- ─────────────────────────────────────────────────────────────────────────────
-- ENUM: status do ciclo de ingestão
-- uploaded   → file no Storage, task rag-ingest enfileirada
-- processing → daemon Mnemos está extraindo + chunking + embedding
-- indexed    → todos os chunks no rag_chunks; documento queryable
-- failed     → erro no pipeline; ver error_detail
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rag_doc_status') THEN
    CREATE TYPE vectraclip.rag_doc_status AS ENUM (
      'uploaded', 'processing', 'indexed', 'failed'
    );
  END IF;
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- vectraclip.rag_documents — origem dos chunks
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vectraclip.rag_documents (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,
  filename      text NOT NULL,
  storage_path  text NOT NULL,
  -- sha256 do conteúdo binário; UNIQUE per-tenant evita re-ingest do mesmo arquivo
  sha256        text NOT NULL,
  mime_type     text,
  size_bytes    bigint,
  page_count    integer,
  status        vectraclip.rag_doc_status NOT NULL DEFAULT 'uploaded',
  error_detail  text,
  -- referência à task que disparou a ingestão (vectraclip.tasks.id)
  ingest_task_id uuid,
  -- metadados livres (origem, autor, tags, classificação)
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  uploaded_by   uuid,
  uploaded_at   timestamptz NOT NULL DEFAULT now(),
  indexed_at    timestamptz,
  CONSTRAINT rag_documents_company_sha256_unique UNIQUE (company_id, sha256)
);

CREATE INDEX IF NOT EXISTS rag_documents_company_status_idx
  ON vectraclip.rag_documents (company_id, status);

CREATE INDEX IF NOT EXISTS rag_documents_uploaded_at_idx
  ON vectraclip.rag_documents (uploaded_at DESC);

COMMENT ON TABLE vectraclip.rag_documents IS
  'RAG: documento fonte (PDF/TXT/HTML/JSON/XLSX) per-tenant. Chunks indexáveis em rag_chunks.';
COMMENT ON COLUMN vectraclip.rag_documents.sha256 IS
  'SHA-256 do conteúdo binário. UNIQUE per-tenant via constraint composta — re-upload do mesmo arquivo retorna o registro existente.';
COMMENT ON COLUMN vectraclip.rag_documents.storage_path IS
  'Caminho no bucket Storage. Convenção: {company_id}/{sha256}.{ext}';


-- ─────────────────────────────────────────────────────────────────────────────
-- vectraclip.rag_chunks — segmentos indexáveis com embedding
-- ─────────────────────────────────────────────────────────────────────────────
-- Embedding fixado em 1536 dim (OpenAI text-embedding-3-small) — parity com
-- RAG PHP atual. Para mudar de modelo, criar tabela paralela rag_chunks_<dim>
-- ou adicionar coluna model_id e índices por modelo.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vectraclip.rag_chunks (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id   uuid NOT NULL REFERENCES vectraclip.rag_documents(id) ON DELETE CASCADE,
  -- DENORMALIZADO de rag_documents.company_id; mantido sincronizado por trigger
  -- abaixo. Permite RLS rápida sem JOIN e index composto company_id + embedding.
  company_id    uuid NOT NULL,
  chunk_index   integer NOT NULL,
  page_number   integer,
  content       text NOT NULL,
  -- texto pode ter overlap com chunk vizinho (ex: 100 tokens) — útil para
  -- fronteiras semânticas. Tamanho típico: 500 tokens, max ~2000.
  token_count   integer,
  embedding     vector(1536) NOT NULL,
  -- model usado para gerar este embedding — permite mixar modelos no futuro
  embedding_model text NOT NULL DEFAULT 'text-embedding-3-small',
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT rag_chunks_doc_index_unique UNIQUE (document_id, chunk_index)
);

-- HNSW: melhor para read-heavy. Cosine distance via <=> operator.
-- m=16, ef_construction=64 são defaults razoáveis; tunar se recall ruim.
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
  ON vectraclip.rag_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS rag_chunks_company_idx
  ON vectraclip.rag_chunks (company_id);

CREATE INDEX IF NOT EXISTS rag_chunks_document_idx
  ON vectraclip.rag_chunks (document_id);

COMMENT ON TABLE vectraclip.rag_chunks IS
  'RAG: segmento indexado com embedding (1536-dim). Cosine via <=> operator + HNSW index.';
COMMENT ON COLUMN vectraclip.rag_chunks.company_id IS
  'Denormalizado de rag_documents para RLS sem JOIN. Trigger sync_company mantém consistência.';


-- ─────────────────────────────────────────────────────────────────────────────
-- Trigger: sync_chunk_company_id
-- Garante que rag_chunks.company_id sempre reflete rag_documents.company_id.
-- INSERT/UPDATE: pega do documento pai. Evita drift entre as duas tabelas.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION vectraclip.sync_chunk_company_id()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  SELECT company_id INTO NEW.company_id
  FROM vectraclip.rag_documents
  WHERE id = NEW.document_id;
  IF NEW.company_id IS NULL THEN
    RAISE EXCEPTION 'rag_chunks: document_id % não encontrado em rag_documents', NEW.document_id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_chunk_company_id ON vectraclip.rag_chunks;
CREATE TRIGGER sync_chunk_company_id
  BEFORE INSERT OR UPDATE OF document_id ON vectraclip.rag_chunks
  FOR EACH ROW
  EXECUTE FUNCTION vectraclip.sync_chunk_company_id();


-- ─────────────────────────────────────────────────────────────────────────────
-- RLS — alinhada ao padrão research_templates (PR #17 / VEC-360)
-- SELECT: authenticated da mesma company OU service_role
-- INSERT/UPDATE/DELETE: service_role apenas (daemon ingestor)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE vectraclip.rag_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.rag_chunks    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rag_documents_select_own ON vectraclip.rag_documents;
CREATE POLICY rag_documents_select_own ON vectraclip.rag_documents
  FOR SELECT TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS rag_documents_service_role_all ON vectraclip.rag_documents;
CREATE POLICY rag_documents_service_role_all ON vectraclip.rag_documents
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS rag_chunks_select_own ON vectraclip.rag_chunks;
CREATE POLICY rag_chunks_select_own ON vectraclip.rag_chunks
  FOR SELECT TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS rag_chunks_service_role_all ON vectraclip.rag_chunks;
CREATE POLICY rag_chunks_service_role_all ON vectraclip.rag_chunks
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────────
-- Grants — explícitos para PostgREST expor as tabelas
-- ─────────────────────────────────────────────────────────────────────────────
GRANT SELECT ON vectraclip.rag_documents TO authenticated;
GRANT SELECT ON vectraclip.rag_chunks    TO authenticated;
GRANT ALL    ON vectraclip.rag_documents TO service_role;
GRANT ALL    ON vectraclip.rag_chunks    TO service_role;


-- ─────────────────────────────────────────────────────────────────────────────
-- NOTIFY pgrst — força reload do schema cache em PostgREST
-- ─────────────────────────────────────────────────────────────────────────────
NOTIFY pgrst, 'reload schema';
