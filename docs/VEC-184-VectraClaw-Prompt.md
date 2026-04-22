# VEC-184 — VectraClaw Prompt (OCR Pipeline: extract_bl_pl)

**Issue Linear:** [VEC-184 — Implementar ferramenta 'extract_bl_pl' para OCR em arquivos pdf](https://linear.app/vectra-cargo/issue/VEC-184)
**Repositório alvo:** `VectraClaw` — `src/services/logistics/bl_pl_parser.py` (novo), `src/m3_tools.py`, `src/api.py`
**Milestone:** M3: Tools Logísticas (Gama)
**Relaciona-se com:** `VEC-185` (calculate_cbm delegado)

---

## Território

| Responsabilidade                                             | Dono           | Onde                                              |
|--------------------------------------------------------------|----------------|---------------------------------------------------|
| Parser OCR de BL e PL com regex field extraction            | **VectraClaw** | `src/services/logistics/bl_pl_parser.py` (novo)   |
| `extract_bl_pl` refatorado: aceita `file_path` ou `base64_content` | **VectraClaw** | `src/m3_tools.py`                          |
| `POST /api/tools/extract-bl-pl` — multipart PDF upload      | **VectraClaw** | `src/api.py`                                      |
| `pdfplumber` + `python-multipart` no requirements           | **VectraClaw** | `requirements.txt`                                |

---

## Contexto — estado antes da VEC

`extract_bl_pl` em `src/m3_tools.py` era um stub mock que retornava sempre os mesmos dados fixos (`bl_number: "MEDU1234567"`, dois containers hardcoded). Não havia integração com biblioteca de PDF, e o endpoint HTTP para upload não existia.

---

## O que foi implementado

### `src/services/logistics/bl_pl_parser.py` (novo)

Módulo de parsing com pipeline em 3 etapas:

1. **Extração de texto** via `pdfplumber` — suporta PDFs texto (não depende de OCR por imagem para PDFs nativos).
2. **Auto-detecção de tipo** — `_detect_doc_type()` pontua keywords BL vs PL para classificar como `bl`, `pl`, `mixed` ou `unknown`.
3. **Extração de campos** — bateria de regex para BL (`bl_number`, `shipper`, `consignee`, `vessel`, `port_of_loading`, `port_of_discharge`, `gross_weight`, `net_weight`, `packages`, `measurement`) e PL (`po_number`, `invoice_number`, `total_cartons`, `total_gross_weight`, `total_net_weight`, `total_cbm`).
4. **Containers e datas** — extração transversal com `[A-Z]{4}[0-9]{7}` (ISO container) e padrões de data multi-formato.
5. **`cross_reference()`** — cruza containers BL x PL, aponta divergências.

**API pública:**
```python
parse_pdf_bytes(pdf_bytes: bytes) -> dict
parse_pdf_file(file_path: str) -> dict
parse_pdf_base64(b64_content: str) -> dict
cross_reference(bl_data: dict, pl_data: dict) -> dict
```

### `src/m3_tools.py` — `extract_bl_pl` refatorado

Payload JSON agora aceita:
```json
{ "file_path": "path/to/doc.pdf" }
// OU
{ "base64_content": "<base64>", "cross_ref": true }
```
- Lazy import do parser para não criar dependência circular.
- Erros específicos: `FileNotFoundError`, `ValueError`, fallback genérico.

### `src/api.py` — novo endpoint

```
POST /api/tools/extract-bl-pl
Content-Type: multipart/form-data

file: <PDF binary>
cross_ref: bool (opcional, default false)
```

- Valida extensão `.pdf` → 422 `only_pdf_accepted` para outros formatos.
- Arquivo vazio → 422 `empty_file`.
- `pdfplumber` não instalado → 503 com mensagem de instrução.
- Protegido pelo middleware de auth global (Bearer JWT).

### `requirements.txt`

```
pdfplumber>=0.11.0
python-multipart>=0.0.9
```

---

## Contrato de resposta

```json
{
  "success": true,
  "filename": "bl_navigantes_2026.pdf",
  "doc_type": "bl",
  "bl": {
    "bl_number": "Maeu1234567",
    "shipper": "Vectra Cargo Asia Ltd",
    "consignee": "Vectra Brasil Ltda",
    "vessel": "Msc Gulsun",
    "port_of_loading": "Shanghai Cn",
    "port_of_discharge": "Navegantes Br",
    "gross_weight": "45000 Kgs"
  },
  "containers": ["MSCU9999999", "MSCU8888888"],
  "dates": ["2026-04-20"],
  "raw_text_snippet": "BILL OF LADING NO: MAEU1234567..."
}
```

---

## Smoke test (7/7 PASS)

Arquivo: `tests/test_vec184_smoke.py`

| ID | Cenário | Resultado |
|----|---------|-----------|
| T1 | `parse_pdf_bytes` com PDF sintético BL — extrai `bl_number` + containers | PASS |
| T2 | `parse_pdf_bytes` com PDF sintético PL — `doc_type=pl`, campo PL extraído | PASS |
| T3 | PDF misto BL+PL — `doc_type=mixed`, `cross_reference` retorna dict | PASS |
| T4 | `extract_bl_pl` (m3_tools) via `base64_content` — `success=True` | PASS |
| T5 | `extract_bl_pl` sem payload — `success=False`, `error` presente | PASS |
| T6 | `POST /api/tools/extract-bl-pl` com PDF real (multipart) — 200, `doc_type=bl` | PASS |
| T7 | Upload de arquivo `.txt` → 422 `only_pdf_accepted` | PASS |

---

## Encerramento

- **Status Linear:** `Done`
- **Data:** 2026-04-20
- **Milestone:** M3 Tools Logísticas — `extract_bl_pl` pronto para delegação ao agente

### Limitações conhecidas

- Parsing depende de PDFs com texto nativo (não funciona com PDFs escaneados como imagem — esses exigiriam AWS Textract ou Tesseract, fora do escopo M3).
- Regex calibrada para documentos em inglês; documentos em outros idiomas podem requerer padrões adicionais.
- A ferramenta pode ser expandida com: suporte a multi-página de tabela de PL, extração de HS codes, e cruzamento com dados cadastrais do Supabase.
