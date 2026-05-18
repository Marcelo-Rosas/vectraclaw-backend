# Meta WhatsApp Cloud API — Webhook Setup

> Configurado pela primeira vez em **2026-05-18** pra company `VECTRA IA SERVICES`
> (`01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2`). Pipeline W3 + W3.1 + W4 + W5 + W5.1.
>
> **Toda credencial vive em `vault.secrets` + espelho em `vectraclip.company_secrets`**
> com refs `vault://<uuid>` em `vectraclip.company_adapter_values.field_values_json`.
> NENHUM segredo vai pro `.env`, `.env.example`, ou commit. Regra Ouro #2.

---

## Endereços públicos do webhook

| Ambiente | URL |
|---|---|
| Produção | `https://api-vectraclip.vectracargo.com.br/api/connectors/whatsapp/webhook` |
| Local (dev) | `http://localhost:3100/api/connectors/whatsapp/webhook` |

Mesmo endpoint atende `GET` (handshake) e `POST` (mensagens). `public_paths` em
`src/api.py` já libera middleware JWT (webhook externo não tem token Supabase).

---

## Setup no Meta App Dashboard

> Dashboard → seu app **WhatsApp Business** → menu lateral `WhatsApp` → `Configuração` → seção `Webhooks` → `Editar`.

### Campo "URL de callback"
```
https://api-vectraclip.vectracargo.com.br/api/connectors/whatsapp/webhook
```

### Campo "Token de verificação"
String forte (>= 32 chars) que voce inventa **e** cola aqui **e** salva no Vault
sob `vault.secrets.name = 'meta-whatsapp.company.webhook_verify_token'`.

Gerado em 2026-05-18:
- Vault secret name: `meta-whatsapp.company.webhook_verify_token`
- Vault secret ID (UUID): `c69c449f-25c1-4eb9-9142-32a2c8eb4457`
- Ref em `company_adapter_values.field_values_json.webhook_verify_token`: `vault://c69c449f-25c1-4eb9-9142-32a2c8eb4457`
- **Valor em si fica SÓ no Vault.** Pra ver, abra o Vault UI no Supabase Studio (Project → Settings → Vault → Secrets) ou descriptografe via:
  ```sql
  SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id='c69c449f-25c1-4eb9-9142-32a2c8eb4457';
  ```

### Subscribed Fields
Marque pelo menos `messages` (recebimento de mensagens entrantes).

Após clicar "Verificar e Salvar", Meta dispara `GET` no nosso webhook com
`?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...` e nosso backend
ecoa o `challenge` em `text/plain 200` se o token bater. Sem batimento → 403
e Meta rejeita a inscrição.

---

## Setup no nosso lado (estado atual da company VECTRA IA SERVICES)

Tabela `vectraclip.company_adapter_values` (1 row pra
`adapter_id=94b68e6a-0949-4908-8b52-e1ee911e600f` slug `meta-whatsapp`):

```jsonc
{
  "access_token":         "vault://376fa7b2-89ef-4e41-8165-bbc523dd917d",
  "phone_number_id":      "vault://9c9caaf0-872c-4ccb-b42d-46a305e72553",
  "app_secret":           "vault://e051c59e-0114-47ca-971b-1c785b607f9f",
  "webhook_verify_token": "vault://c69c449f-25c1-4eb9-9142-32a2c8eb4457"
}
```

Cada `vault://<uuid>` aponta pra row em `vault.secrets` com espelho em
`vectraclip.company_secrets` pra ownership-check per-tenant.

### Como o backend lê

`src/api_routes/connectors.py:_resolve_meta_config_for_company` chama
`resolve_adapter_field_value(field, agent_overrides, company_values, company_id)`
que delega pra `resolve_secret_ref(value, company_id)` que chama a RPC
`vectraclip.get_vault_secret(uuid, uuid)` (W5.1) — SECURITY DEFINER, valida
ownership em `company_secrets`, devolve `text` claro pra HMAC ou roteamento.

---

## Fluxos verificados

### 1. Handshake `GET` (Meta inicial verification)

```bash
curl 'https://api-vectraclip.vectracargo.com.br/api/connectors/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<token_claro>&hub.challenge=PING'
```

**Esperado:** `HTTP 200` + body `PING` (text/plain). Smoke validado 2026-05-18
com `PING_TEST_2026`.

**Erros possíveis:**
- `400 invalid_hub_mode` — Meta mandou modo diferente de `subscribe`
- `400 missing_hub_params` — sem `verify_token` ou `challenge`
- `403 verify_token_mismatch` — token não bate com nenhum
  `webhook_verify_token` resolvido via `_find_any_meta_config_with_verify_token`

### 2. Recebimento de mensagem `POST` (operação normal)

Meta envia `POST` com header `X-Hub-Signature-256: sha256=<hmac>` + body JSON
formato Meta Cloud API (`entry[].changes[].value.messages[]`).

Backend:
1. Lê body bytes (necessário pra HMAC validar antes de parsear)
2. Parse `_parse_meta_message` extrai `phone_number_id`, `external_id` (from),
   `content`, `wamid`
3. `_find_meta_config_by_phone_number_id` resolve config Meta da company-alvo
4. Valida `X-Hub-Signature-256` com `_verify_meta_signature` usando
   `app_secret` resolvido
5. Cria/atualiza `connector_session` em `vectraclip.connector_sessions`
6. `append_history` na sessão (ring buffer 50 trocas)

**Erros possíveis:**
- `400 invalid_json` / `empty_body`
- `400 missing_phone_number_id` / `missing_message_from`
- `404 no_adapter_config_for_phone_number_id` — Meta enviou pra `phone_number_id`
  que não está provisionado em nenhuma `company_adapter_values`
- `503 app_secret_not_configured_for_company` — config existe mas sem `app_secret` no Vault
- `401 invalid_meta_signature` — HMAC não bateu

---

## Rotacionando secrets

### `app_secret`
Quando regenerar no Meta App Dashboard → Configurações Básicas → "Atualizar segredo":

```sql
-- 1. Upsert no Vault (cria nova versão, mantém vault_secret_id antigo NULL)
SELECT vectraclip.upsert_company_secret(
  '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2'::uuid,
  'meta-whatsapp.company.app_secret',
  '<novo_valor>',
  'Meta WhatsApp App Secret — rotacionado YYYY-MM-DD'
);
-- Retorna novo vault_secret_id; cole no UPDATE abaixo:

UPDATE vectraclip.company_adapter_values
SET field_values_json = field_values_json
    || jsonb_build_object('app_secret', 'vault://<novo_uuid>'),
    updated_at = now()
WHERE company_id = '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2'
  AND adapter_id = '94b68e6a-0949-4908-8b52-e1ee911e600f';
```

### `webhook_verify_token`
Gerar novo valor forte:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Repita o fluxo `upsert_company_secret` + `UPDATE company_adapter_values` igual ao `app_secret`. **Atualize também no Meta App Dashboard → Webhooks → "Editar"** com o mesmo valor — senão handshake quebra na próxima reverificação da Meta.

### `access_token`
Tokens permanentes Meta nunca expiram, mas se for tokens System User com
expiração: gere novo no Meta App Dashboard → Configurações → Tokens, faça
upsert via RPC + update do `company_adapter_values.access_token`.

---

## Pra adicionar mais uma company com Meta WhatsApp

1. Provisiona o adapter pra company em `vectraclip.adapter_catalog` (já existe
   row pra company corrente, mas se for outra: copiar/criar)
2. UI: `/admin/connectors` → "Preencher Valores" no row meta-whatsapp (W5 frontend, PR #47 mergeado)
3. Preencher os 4 fields (UI faz split secret→Vault automaticamente)
4. Registrar webhook no Meta App Dashboard de **outra** Meta App da nova company,
   apontando pra mesma URL `/api/connectors/whatsapp/webhook`
5. Backend roteia por `phone_number_id` (cada company tem seu) → multi-tenant
   funciona sem mudança de código

---

## Referências cruzadas

- `src/api_routes/connectors.py` — handlers GET (handshake) + POST (mensagens)
- `src/api.py` — helpers `resolve_secret_ref`, `resolve_adapter_field_value`,
  `get_company_adapter_values`, endpoint `/secrets`, endpoint `/adapter-values`
- `supabase/migrations/20260517280000_meta_whatsapp_app_secret_field.sql` — campo `app_secret` no adapter
- `supabase/migrations/20260518000000_company_adapter_values.sql` — tabela company-level values (W5)
- `supabase/migrations/20260518010000_get_vault_secret_rpc.sql` — RPC `get_vault_secret` (W5.1)
- `src/services/whatsapp/meta_client.py` — wrapper outbound (envio de templates/mensagens) — ainda lê env `META_WA_TOKEN`, será migrado pra adapter config em PR futuro
