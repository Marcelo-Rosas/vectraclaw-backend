-- =============================================================================
-- Mnemos RAG local embeddings — Ollama nomic-embed-text (768-dim) catalog-driven
-- =============================================================================
-- Contexto: Gemini embedding API caiu em prod (403 PERMISSION_DENIED, conta
-- Google Cloud) e a cota OpenAI estourou (VEC-394). O pipeline RAG do Mnemos
-- ficou sem embedder funcional. Solução: rodar embeddings localmente via Ollama
-- (nomic-embed-text, 274MB, 768-dim, supera text-embedding-ada-002), SEM
-- dependência de API key/quota externa.
--
-- Regra de Ouro #2 (NO HARDCODE): o embedder é resolvido pelo ADAPTER do
-- agente (provider/model/base_url/dimensions vêm de agent_adapter_configs +
-- adapter_catalog), nunca hardcodado no .py. Esta migration cria o adapter
-- `ollama-embedding` e aponta a config do Mnemos para ele.
--
-- Schema lock (rag/CLAUDE.md): trocar dimensões exige recriar índice HNSW +
-- alterar RPC. Como o re-embed é trivial (7 docs rag + 1 athena), limpamos os
-- chunks 1536-dim antigos e resetamos os documentos para re-ingestão (768-dim).
--
-- Tabelas afetadas: llm_models, adapter_catalog, adapter_field_definitions,
-- agent_adapter_configs, rag_chunks, athena_chunks + RPCs match_*_chunks.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Catálogo do modelo de embedding (alimenta o dropdown model_id do adapter)
-- -----------------------------------------------------------------------------
-- id == nome real do modelo Ollama, para que o valor selecionado no dropdown
-- seja exatamente o que vai no POST /api/embeddings {"model": ...}.
INSERT INTO vectraclip.llm_models (
  id, provider, display_name, input_cost_per_1m, output_cost_per_1m,
  cache_read_cost_per_1m, context_window_k, is_active, effective_from,
  supports_tool_calling
) VALUES (
  'nomic-embed-text', 'ollama', 'nomic-embed-text (Embedding 768d, local)',
  0, 0, 0, 2, true, CURRENT_DATE, false
)
ON CONFLICT (id, effective_from) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. Adapter `ollama-embedding` (provider=ollama) — por company
-- -----------------------------------------------------------------------------
-- Distinto do adapter `ollama` (chat): embedding tem propósito, modelo e campo
-- `dimensions` próprios. provider='ollama' faz resolve_embedder() rotear para
-- OllamaEmbedder.
DO $$
DECLARE
  rec RECORD;
  v_adapter_id uuid;
BEGIN
  FOR rec IN SELECT DISTINCT company_id FROM vectraclip.adapter_catalog LOOP
    INSERT INTO vectraclip.adapter_catalog (company_id, slug, display_name, provider, is_active)
    VALUES (rec.company_id, 'ollama-embedding', 'Ollama Embeddings (Local)', 'ollama', true)
    ON CONFLICT (company_id, slug) DO NOTHING;

    SELECT id INTO v_adapter_id
    FROM vectraclip.adapter_catalog
    WHERE company_id = rec.company_id AND slug = 'ollama-embedding';

    -- field_definitions (espelha shape do adapter ollama chat; applies_to=company)
    -- base_url
    INSERT INTO vectraclip.adapter_field_definitions (
      company_id, adapter_id, field_key, field_label, field_type,
      is_required, options_json, sort_order, is_active, applies_to
    )
    SELECT rec.company_id, v_adapter_id, 'base_url', 'URL do servidor Ollama', 'text',
           true, NULL, 10, true, 'company'
    WHERE NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions
      WHERE adapter_id = v_adapter_id AND field_key = 'base_url'
    );

    -- model_id (select alimentado por llm_models provider=ollama)
    INSERT INTO vectraclip.adapter_field_definitions (
      company_id, adapter_id, field_key, field_label, field_type,
      is_required, options_json, sort_order, is_active, applies_to
    )
    SELECT rec.company_id, v_adapter_id, 'model_id', 'Modelo de Embedding', 'select',
           true, '{"source": "llm_models", "provider": "ollama"}'::jsonb, 20, true, 'company'
    WHERE NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions
      WHERE adapter_id = v_adapter_id AND field_key = 'model_id'
    );

    -- dimensions (número — deve casar com vector(N) das tabelas de chunks)
    INSERT INTO vectraclip.adapter_field_definitions (
      company_id, adapter_id, field_key, field_label, field_type,
      is_required, options_json, sort_order, is_active, applies_to
    )
    SELECT rec.company_id, v_adapter_id, 'dimensions', 'Dimensões do vetor', 'number',
           true, NULL, 30, true, 'company'
    WHERE NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions
      WHERE adapter_id = v_adapter_id AND field_key = 'dimensions'
    );
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- 3. Aponta a config do Mnemos para o adapter de embedding
-- -----------------------------------------------------------------------------
-- Mnemos (00000000-0000-0000-0000-000000000003) é embedder-only (não faz chat).
-- A config antiga apontava para claude_code (não usado). UNIQUE(agent_id) impede
-- 2 configs, então fazemos UPDATE para o ollama-embedding da MESMA company.
DO $$
DECLARE
  v_company uuid;
  v_adapter_id uuid;
BEGIN
  SELECT company_id INTO v_company
  FROM vectraclip.agent_adapter_configs
  WHERE agent_id = '00000000-0000-0000-0000-000000000003'
  LIMIT 1;

  IF v_company IS NOT NULL THEN
    SELECT id INTO v_adapter_id
    FROM vectraclip.adapter_catalog
    WHERE company_id = v_company AND slug = 'ollama-embedding';

    IF v_adapter_id IS NOT NULL THEN
      UPDATE vectraclip.agent_adapter_configs
      SET adapter_id = v_adapter_id,
          field_values_json = jsonb_build_object(
            'base_url', 'http://localhost:11434',
            'model_id', 'nomic-embed-text',
            'dimensions', 768
          ),
          is_active = true,
          updated_at = now()
      WHERE agent_id = '00000000-0000-0000-0000-000000000003';
    END IF;
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 4. Schema lock: vector(1536) → vector(768) em rag_chunks + athena_chunks
-- -----------------------------------------------------------------------------
-- pgvector não trunca dims automaticamente: limpamos os chunks 1536 antigos e
-- resetamos os documentos para re-ingestão (Mnemos re-embeda em 768).
DELETE FROM vectraclip.rag_chunks;
DELETE FROM vectraclip.athena_chunks;

-- volta documentos indexados para 'uploaded' (re-ingest dispara novo embed)
UPDATE vectraclip.rag_documents
SET status = 'uploaded', indexed_at = NULL
WHERE status IN ('indexed', 'failed');

UPDATE vectraclip.athena_documents
SET status = 'uploaded', indexed_at = NULL
WHERE status IN ('indexed', 'failed');

-- drop índices HNSW (atrelados à dimensão antiga)
DROP INDEX IF EXISTS vectraclip.rag_chunks_embedding_hnsw;
DROP INDEX IF EXISTS vectraclip.athena_chunks_embedding_hnsw;

-- altera dimensão das colunas
ALTER TABLE vectraclip.rag_chunks
  ALTER COLUMN embedding TYPE vector(768),
  ALTER COLUMN embedding_model SET DEFAULT 'nomic-embed-text';

ALTER TABLE vectraclip.athena_chunks
  ALTER COLUMN embedding TYPE vector(768),
  ALTER COLUMN embedding_model SET DEFAULT 'nomic-embed-text';

-- recria índices HNSW na nova dimensão
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
  ON vectraclip.rag_chunks
  USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS athena_chunks_embedding_hnsw
  ON vectraclip.athena_chunks
  USING hnsw (embedding vector_cosine_ops);

-- -----------------------------------------------------------------------------
-- 5. RPCs match_*_chunks: assinatura vector(1536) → vector(768)
-- -----------------------------------------------------------------------------
-- DROP necessário: mudar o tipo de um parâmetro cria nova assinatura (a antiga
-- 1536 sobreviveria a um CREATE OR REPLACE e quebraria por overload ambíguo).
DROP FUNCTION IF EXISTS vectraclip.match_rag_chunks(vector(1536), uuid, int, float);
DROP FUNCTION IF EXISTS vectraclip.match_athena_chunks(vector(1536), uuid, int, float);

CREATE OR REPLACE FUNCTION vectraclip.match_rag_chunks(
  query_embedding vector(768),
  p_company_id   uuid,
  p_match_count  int DEFAULT 5,
  p_min_score    float DEFAULT 0.0
)
RETURNS TABLE (
  id              uuid,
  document_id     uuid,
  chunk_index     int,
  page_number     int,
  content         text,
  score           float,
  metadata        jsonb,
  document_filename text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = vectraclip, public
AS $$
  SELECT
    c.id,
    c.document_id,
    c.chunk_index,
    c.page_number,
    c.content,
    1.0 - (c.embedding <=> query_embedding) / 2.0 AS score,
    c.metadata,
    d.filename AS document_filename
  FROM vectraclip.rag_chunks c
  JOIN vectraclip.rag_documents d ON d.id = c.document_id
  WHERE c.company_id = p_company_id
    AND (1.0 - (c.embedding <=> query_embedding) / 2.0) >= p_min_score
  ORDER BY c.embedding <=> query_embedding ASC
  LIMIT GREATEST(p_match_count, 1);
$$;

COMMENT ON FUNCTION vectraclip.match_rag_chunks IS
  'RAG: top-k chunks por cosine similarity (768-dim, nomic-embed-text). company_id obrigatório (multi-tenant).';

GRANT EXECUTE ON FUNCTION vectraclip.match_rag_chunks TO authenticated, service_role;

CREATE OR REPLACE FUNCTION vectraclip.match_athena_chunks(
  query_embedding vector(768),
  p_company_id   uuid,
  p_match_count  int DEFAULT 5,
  p_min_score    float DEFAULT 0.0
)
RETURNS TABLE (
  id              uuid,
  document_id     uuid,
  chunk_index     int,
  page_number     int,
  content         text,
  score           float,
  metadata        jsonb,
  document_filename text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = vectraclip, public
AS $$
  SELECT
    c.id,
    c.document_id,
    c.chunk_index,
    c.page_number,
    c.content,
    1.0 - (c.embedding <=> query_embedding) / 2.0 AS score,
    c.metadata,
    d.filename AS document_filename
  FROM vectraclip.athena_chunks c
  JOIN vectraclip.athena_documents d ON d.id = c.document_id
  WHERE c.company_id = p_company_id
    AND (1.0 - (c.embedding <=> query_embedding) / 2.0) >= p_min_score
  ORDER BY c.embedding <=> query_embedding ASC
  LIMIT GREATEST(p_match_count, 1);
$$;

COMMENT ON FUNCTION vectraclip.match_athena_chunks IS
  'Athena RAG: top-k chunks por cosine similarity (768-dim, nomic-embed-text). company_id obrigatório. Isolado de match_rag_chunks.';

GRANT EXECUTE ON FUNCTION vectraclip.match_athena_chunks TO authenticated, service_role;

NOTIFY pgrst, 'reload schema';
