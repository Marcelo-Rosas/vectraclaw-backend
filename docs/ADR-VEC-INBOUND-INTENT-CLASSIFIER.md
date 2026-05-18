# ADR-VEC-INBOUND-INTENT-CLASSIFIER

> **Status:** OPEN — aguarda decisão Marcelo antes de qualquer correção adicional no fluxo inbound
>
> **Data:** 2026-05-18
>
> **Bloqueia:** W6, W7 P0-10/11 (smoke real), W8 (em parte), qualquer feature de auto-reply WhatsApp

---

## Contexto

Mensagem real recebida pelo webhook Meta WhatsApp em 2026-05-18:

> **Fabio Cavalcanti** (via formulário do site Vectra Cargo):
> *"Olá! Vim pelo site da Vectra Cargo e quero saber mais sobre a empresa, pois tenho interesse me contratar!"*

Fluxo atual (pós W7 P0-9 mergeado):
```
Webhook recebe → _dispatch_inbound_task → op_type=freight-quotation (HARDCODED default)
                                       → Mercator (agente comercial)
                                       → claude -p tenta cotar sem dados (origem/destino/peso/valor)
                                       → BLOCKED em 12s
                                       → Fabio sem resposta
```

A correção W7 P0-9 trocou `oracle-research → freight-quotation`. Continua errado: **qualquer default fixo é errado** porque a entrada é heterogênea.

| Tipo de mensagem | Destino correto |
|---|---|
| "Quanto custa frete CE→SP, 500kg" | `freight-quotation` → Mercator |
| "Quero me candidatar a vaga" | `hr-intake` → ??? (não existe) |
| "Cadê minha OS 12345" | `order-status` → ??? (parcial no NAVI) |
| "Reclamação sobre atraso" | `complaint` → ??? (não existe) |
| "Olá!" (sem contexto) / Fabio | `triage` → roteador decide |

## Problema central

**Não existe componente que CLASSIFIQUE intent antes de criar task.** Webhook é cego, default é loteria. W6 (auto-reply LLM) só faz sentido depois de ter intent correto.

W8 (claude-cli adapter) é fundação útil mas não resolve o roteamento. Mesmo com claude-cli funcionando, Mercator vai responder cotação a quem não pediu cotação.

## Opções arquiteturais

### Opção A — Default = Morpheus router task (mais simples / mais alinhado com VectraClaw existente)

```
Webhook → cria task `inbound-triage` assigned=Morpheus
       → Morpheus (já existe como dispatcher) classifica via LLM/regra
       → cria task filha com op_type correto + assign correto
       → essa task filha executa normalmente
```

**Prós:**
- Reusa Morpheus que já é orquestrador (`src/services/morpheus_dispatcher.py`)
- Padrão "default + dispatcher" canônico em VectraClaw
- Zero serviço externo
- Morpheus pode usar Claude CLI (W8) pra classificar — single source of truth

**Contras:**
- Morpheus hoje só roteia via `workflow_steps` (regras estruturadas), não classifica texto livre
- Precisa adicionar capacidade de classificação LLM no Morpheus
- 2 saltos (triage → execução), latência maior

**Esforço:** médio. Migration novo op_type `inbound-triage` + lógica classifier em `morpheus_dispatcher.py` + branch no `agent_daemon.py` pra esse op_type.

### Opção B — Intent classifier INLINE no webhook (mais rápido)

```
Webhook recebe → função classify_inbound_intent(content, history) → op_type
               → cria task com op_type correto direto
```

Classifier pode ser:
- **B1**: keyword matcher (regex contendo "cotação"/"frete" → freight; "candidato"/"vaga" → hr-intake; etc.)
- **B2**: Claude CLI zero-shot (`claude -p "Classifica: 'XYZ'. Categorias: freight-quotation, hr-intake, order-status, complaint, triage. Responda só o slug."`)
- **B3**: Híbrido (B1 primeiro, B2 fallback)

**Prós:**
- 1 salto só
- Menor latência
- Reusa W8 adapter (chama via CMA mesmo padrão)
- Pode evoluir B1→B2→B3 sem mudar interface

**Contras:**
- Webhook fica acoplado a regras de negócio (lista de intents)
- Cada intent novo exige PR no webhook OU vira tabela `inbound_intent_routing` (catalog-driven)

**Esforço:** baixo (B1) → médio (B2/B3). Tabela `inbound_intent_routing(intent_slug, keywords[], operation_type, primary_agent_id)` mantém catalog-driven (Regra Ouro #2).

### Opção C — NAVI faz a classificação (plano original do Miro)

```
Meta → NAVI (Edge Function) → intent detection + Meta Flow form → POST /api/quotation/intake
                                                                → POST /api/hr/intake (futuro)
                                                                → etc.
```

VectraClaw apenas recebe payloads JÁ ESTRUTURADOS via endpoints específicos por intent. Webhook genérico só pra mensagens não-classificadas.

**Prós:**
- Separação clara: NAVI = camada de conversa, Claw = camada de execução
- Meta Flow nativo (forms estruturados — melhor UX que perguntar peso/origem por texto)
- Multi-canal natural: NAVI também atende Telegram/Email/etc.
- Estado de conversa fica em NAVI (não polui VectraClaw)

**Contras:**
- Requer NAVI implementado (P0-3, P0-5, P0-6 do Miro — todas "Falta")
- Decisão de stack/host NAVI ainda aberta (Supabase Edge? Cloudflare Workers? Container separado?)
- Custo: 1 hop extra na cadeia

**Esforço:** alto. NAVI é projeto à parte. Não dá pra W8 viabilizar.

## Implicações por opção

| Critério | A (Morpheus) | B (Inline) | C (NAVI) |
|---|---|---|---|
| MVP em dias | 3-5 | 1-2 (B1) / 3-5 (B2) | 15-30 |
| Latência inbound | +5-15s (triage + LLM) | +0.1s (B1) / +3-5s (B2) | +variável |
| Custo por msg | 1 chamada LLM | 0 (B1) / 1 chamada (B2) | depende |
| Mantém arquitetura atual | ✅ | ⚠️ (acopla webhook) | ❌ (NAVI externo) |
| Multi-canal futuro | ✅ | ⚠️ (precisa replicar por canal) | ✅ |
| Bloqueia outros caminhos | Não | Pode evoluir pra C | É o caminho final |
| Resolve Fabio hoje | Sim | Sim | Sim (quando pronto) |

## Recomendação técnica

**Sequência sugerida:** B1 agora (1-2 dias destrava Fabio) → B3 (B1 + B2 fallback) → C (quando NAVI nascer).

A se justifica se houver decisão de "Morpheus é o classifier universal mesmo a longo prazo". Caso contrário, B é mais barato e converte naturalmente em C.

## Decisões pendentes (Marcelo)

1. **Qual opção (A/B/C)?**
2. Se B: subopção B1/B2/B3?
3. Se A ou B com tabela: nome da tabela e schema?
4. Catálogo inicial de intents: quais slugs já criar? (freight-quotation existe; hr-intake novo? order-status?)
5. O que Mercator faz se receber task com dados incompletos? **erro útil + sugestão** ou marca blocked? (independente da opção escolhida)

## Não fazer enquanto a decisão não fechar

- ❌ Adicionar mais `_INBOUND_DEFAULT_*` em qualquer lugar
- ❌ Implementar handler Mercator sem antes ter intent garantido
- ❌ Mergear W8 sem nota explícita de que adapter é fundação, NÃO resolve roteamento
- ❌ Pedir "mais um teste WhatsApp" — vai dar blocked igual o Fabio

## Estado atual dos PRs relacionados

| PR | Status | Avaliação pós-Fabio |
|---|---|---|
| #205 W3 | mergeado | OK (infra connector_session) |
| #206 W3.1 | mergeado | OK (Meta webhook + secrets) |
| #207-209 W4/W5/W5.1 | mergeado | OK (Vault catalog-driven) |
| #211 W7 P0-9 | mergeado | **Default ainda errado** — só removeu hardcode (foi catalog), não resolve intent |
| #212 W7 P0-10/11 | mergeado | OK como infra (hook reply pós-done), mas hoje sempre cai em blocked |
| #213 W8 | aberto | OK como **fundação** (claude-cli adapter), MAS sem intent classifier o cliente nunca é chamado com dados úteis |

## Próximo passo

Marcelo decide A/B/C aqui. Sem isso, nenhum código adicional faz sentido nesse fluxo.
