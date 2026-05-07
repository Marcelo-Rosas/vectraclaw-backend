-- =============================================================================
-- VEC-359 (Step 10) — RPC match_rag_chunks: top-k cosine similarity
-- =============================================================================
-- PostgREST não expõe o operador `<=>` diretamente; encapsulamos a busca
-- em função SQL chamada via supabase.rpc("match_rag_chunks", ...).
--
-- Ordena por cosine distance ASC (mais próximo = score maior).
-- Retorna score normalizado em [0, 1] para uso no frontend (0=oposto, 1=idêntico).
-- =============================================================================

CREATE OR REPLACE FUNCTION vectraclip.match_rag_chunks(
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
    -- cosine distance está em [0, 2]; cosine similarity em [-1, 1]
    -- normalizamos para [0, 1]: similarity = 1 - distance/2
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
  'RAG: top-k chunks por cosine similarity. company_id obrigatório (multi-tenant). p_min_score filtra ruído.';

-- Grants: authenticated pode invocar via PostgREST RPC; service_role tudo
GRANT EXECUTE ON FUNCTION vectraclip.match_rag_chunks TO authenticated, service_role;

NOTIFY pgrst, 'reload schema';
