# `src/services/rag/` — Pipeline RAG

Stack que substitui o RAG PHP standalone por uma implementação Python integrada ao VectraClaw. Schema em `vectraclip.rag_documents` + `vectraclip.rag_chunks` (PR #18 + #19).

---

## Pipeline

```
upload (api/rag) → tasks(rag-ingest) → daemon Mnemos → extract → chunk → embed → insert
                                                                                    ↓
query (api/rag/query OR tool query_rag) ← retriever ← RPC match_rag_chunks ← rag_chunks
```

---

## Módulos

| Arquivo | Responsabilidade | Dependências externas |
|---|---|---|
| `models.py` | Pydantic: `PageText`, `ExtractedDocument`, `ChunkInput`, `ChunkResult` | — |
| `extractor.py` | Extrai texto de PDF/TXT/HTML/JSON/XLSX → `ExtractedDocument` | `pdfplumber`, `openpyxl` |
| `chunker.py` | Splita em chunks com overlap; **não cruza fronteira de página** | — |
| `embedder.py` | `OpenAIEmbedder.embed_one/batch` → `vector(1536)` | `openai` |
| `retriever.py` | `query_top_k(query, company_id)` via RPC `match_rag_chunks` | Supabase RPC |

---

## Contratos

**`extract_text(file_path, mime_type=None) -> ExtractedDocument`**
- Detecta mime por extensão se não informado.
- PDF/XLSX: páginas 1-indexed; TXT/HTML/JSON: single-page.
- XLSX: cada sheet vira uma "página"; rows renderizadas como TSV.

**`chunk_text(pages, *, max_tokens=500, overlap=100) -> list[ChunkInput]`**
- Token approx: 1 token ≈ 0.75 palavras (cl100k_base avg).
- `chunk_index` é **global** (sequencial entre páginas), não por página.
- Página inteira menor que `max_tokens` → 1 chunk único (sem split).
- Overlap só dentro da mesma página.

**`OpenAIEmbedder(model='text-embedding-3-small', dimensions=1536)`**
- Lê `OPENAI_KEY` ou `OPENAI_API_KEY` do env.
- `embed_batch` filtra strings vazias mantendo posição (vetor zero).
- Síncrono → async via `asyncio.to_thread`.

**`query_top_k(query_text, company_id, *, k=5, min_score=0.0, embedder=None, supabase_client=None)`**
- Multi-tenant via `company_id` no RPC (filtro WHERE no banco).
- Score normalizado em `[0, 1]` (`1.0 - distance/2`).
- Ordenado por score DESC.

---

## Schema lock — vector(1536)

`rag_chunks.embedding` é `vector(1536)` (PR #18). **Mudar o modelo de embedding requer:**

1. Criar tabela paralela `rag_chunks_<dim>` com `vector(<dim>)` + HNSW index
2. Adicionar lógica de roteamento por `embedding_model` no retriever
3. Migration de re-embed dos docs existentes

Não simplesmente trocar `dimensions=1536` por outro valor — o índice HNSW falha.

---

## RPC `vectraclip.match_rag_chunks`

Encapsula o operador `<=>` (não exposto via PostgREST direto).

```sql
match_rag_chunks(
  query_embedding vector(1536),
  p_company_id uuid,
  p_match_count int DEFAULT 5,
  p_min_score float DEFAULT 0.0
) RETURNS TABLE (id, document_id, chunk_index, page_number, content, score, metadata, document_filename)
```

`SECURITY DEFINER` + filtro `WHERE company_id = p_company_id` garante isolamento mesmo via service_role.

---

## Padrões obrigatórios

1. **Toda inserção em `rag_chunks` deve passar pelo trigger** `sync_chunk_company_id` (BEFORE INSERT/UPDATE) — não tente popular `company_id` manualmente.
2. **`embedding_model` em `rag_chunks` deve coincidir com o modelo do embedder** que gerou o vetor — caso contrário, queries de re-embed falham.
3. **Storage path**: `{company_id}/{sha256}.{ext}` no bucket `rag-documents`.
4. **Idempotência via sha256**: re-upload do mesmo arquivo → upsert (não duplica).
5. **Async em todos os entry points públicos** (`embed_*`, `query_top_k`) — daemons e API são async.

---

## Pitfalls conhecidos

- **openpyxl `read_only=True` + Windows**: precisa `wb.close()` explícito ou tempfile fica locked. Ver `_extract_xlsx`.
- **OpenAI rejeita strings vazias** em `embeddings.create`. Embedder filtra antes de chamar.
- **`text-embedding-3-large` com dimensions=1536** funciona (Matryoshka truncation), mas queries vão coexistir com vetores 3-small no mesmo índice — recall pode degradar. Preferir manter um único modelo por tabela.
- **HNSW recall** depende de `m` e `ef_construction`. Defaults `m=16, ef_construction=64` cobrem até ~1M chunks. Para mais, tunar.

---

## Próximas PRs do Step 10

- **3/5** — Daemon Mnemos: handler `rag-ingest` em `agent_daemon.py` que orquestra extract → chunk → embed → insert
- **4/5** — `src/api_routes/rag.py`: endpoints upload/list/query/delete
- **5/5** — Tool `query_rag` em `m3_tools.py` + registro em `tool_translator.ANTHROPIC_TOOLS`
