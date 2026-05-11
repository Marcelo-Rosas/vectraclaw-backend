-- =============================================================================
-- VEC-394 — RPC match_athena_chunks: top-k cosine similarity (Athena corpus)
-- =============================================================================
-- Espelho de vectraclip.match_rag_chunks (VEC-359), apontando para
-- vectraclip.athena_chunks + vectraclip.athena_documents.
--
-- Ordena por cosine distance ASC (mais próximo = score maior).
-- Score normalizado em [0, 1]: similarity = 1 - distance/2.
-- =============================================================================

CREATE OR REPLACE FUNCTION vectraclip.match_athena_chunks(
  query_embedding vector(1536),
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
  'Athena RAG: top-k chunks por cosine similarity. company_id obrigatório. Isolado de match_rag_chunks (corpus PMBOK/Heldman).';

GRANT EXECUTE ON FUNCTION vectraclip.match_athena_chunks TO authenticated, service_role;

NOTIFY pgrst, 'reload schema';
