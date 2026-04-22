# VEC-186 — VectraClaw Prompt (WhatsApp via Meta Cloud API)

**Issue Linear:** [VEC-186 — Webhook disparador para WhatsApp](https://linear.app/vectra-cargo/issue/VEC-186)
**Repositório alvo:** `VectraClaw` — `src/services/whatsapp/meta_client.py` (novo), `src/m3_tools.py`, `src/api.py`
**Milestone:** M3: Tools Logísticas (Gama)

---

## Território

| Responsabilidade                                              | Dono           | Onde                                               |
|---------------------------------------------------------------|----------------|----------------------------------------------------|
| HTTP client Meta Cloud API (send_text / send_template)        | **VectraClaw** | `src/services/whatsapp/meta_client.py` (novo)      |
| `normalize_phone_e164()` — normalização de telefone           | **VectraClaw** | `src/services/whatsapp/meta_client.py`             |
| `send_whatsapp_webhook` refatorado: text + template real      | **VectraClaw** | `src/m3_tools.py`                                  |
| `POST /api/tools/send-whatsapp` — endpoint HTTP para o agente | **VectraClaw** | `src/api.py`                                       |
| Credenciais Meta                                              | `.env`         | `META_WA_TOKEN`, `META_WA_PHONE_NUMBER_ID`, `META_WA_API_VERSION` |

---

## Contexto — estado antes da VEC

`send_whatsapp_webhook` em `src/m3_tools.py` era um stub mock que sempre retornava `{"success": True, "delivered_to": phone, "status": "200 OK"}` sem fazer nenhuma chamada HTTP real.

---

## O que foi implementado

### `src/services/whatsapp/meta_client.py` (novo)

**`normalize_phone_e164(phone, default_country="55")`**
- Remove caracteres não-numéricos
- Remove prefixo de discagem `00`
- Adiciona DDI `55` se ausente
- Retorna formato `+5547999990000`

**`send_text(phone, message) → dict`**
- Mensagem de texto livre, válida dentro da janela de 24 h
- Chama `POST https://graph.facebook.com/{version}/{phone_number_id}/messages`
- Headers: `Authorization: Bearer {META_WA_TOKEN}`

**`send_template(phone, template_name, language, components) → dict`**
- Mensagem via template aprovado na conta Meta (sem restrição de janela)
- Suporta `components` para injetar parâmetros nos slots do template

**`WhatsAppAPIError`** — exceção tipada com `status_code` e `detail` da resposta Meta.

### `src/m3_tools.py` — `send_whatsapp_webhook` refatorado

Payload JSON agora aceita dois modos:

```json
// Modo texto livre
{ "phone": "+5547999990000", "message": "BL processado." }

// Modo template
{
  "phone": "+5547999990000",
  "type": "template",
  "template_name": "notificacao_frete",
  "language": "pt_BR",
  "components": [
    { "type": "body", "parameters": [{"type": "text", "text": "MAEU1234567"}] }
  ]
}
```

### `src/api.py` — novo endpoint

```
POST /api/tools/send-whatsapp
Content-Type: application/json
Authorization: Bearer <jwt>
```

Modelo `WhatsAppTextInput` (Pydantic):
- `phone` (obrigatório)
- `message` (obrigatório para `type=text`)
- `type`: `"text"` | `"template"` (default `"text"`)
- `template_name` (obrigatório para `type=template`)
- `language` (default `"pt_BR"`)
- `components` (opcional)

Erros: 422 para campos obrigatórios ausentes, 502 para falhas na Meta API.

### `.env`

```
META_WA_TOKEN=<system_user_token>
META_WA_PHONE_NUMBER_ID=910223578841229
META_WA_API_VERSION=v25.0
```

---

## Smoke test (6 PASS + 2 SKIP opcionais)

Arquivo: `tests/test_vec186_smoke.py`

| ID | Cenário | Resultado |
|----|---------|-----------|
| T1 | `normalize_phone_e164` — 6 formatos diferentes → `+55...` | PASS |
| T2 | `send_whatsapp_webhook` sem `phone` → `success=False` | PASS |
| T3 | `type=text` sem `message` → `success=False` | PASS |
| T4 | `type=template` sem `template_name` → `success=False` | PASS |
| T5 | `POST /api/tools/send-whatsapp` sem `phone` → 422 | PASS |
| T6 | `POST` `type=template` sem `template_name` → 422 | PASS |
| T7 | Envio real `type=text` (requer `META_WA_TEST_PHONE`) | SKIP* |
| T8 | Envio real `type=template` (requer `META_WA_TEST_PHONE` + `META_WA_TEST_TEMPLATE`) | SKIP* |

*T7/T8 são ativados adicionando `META_WA_TEST_PHONE` e `META_WA_TEST_TEMPLATE` ao `.env`.

---

## Encerramento

- **Status Linear:** `Done`
- **Data:** 2026-04-20
- **Milestone:** M3 Tools Logísticas — `send_whatsapp_webhook` pronto para delegação ao agente

### Limitações conhecidas

- T7/T8 (envio real) não executados automaticamente para não gerar mensagens reais nos testes de CI.
- Template precisa estar aprovado na conta Meta e o nome deve coincidir exatamente.
- Token atual pode ser User Token (expira); recomendado migrar para System User Token permanente.
