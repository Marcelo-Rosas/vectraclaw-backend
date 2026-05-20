# HANDOFF — MCP Fase A: Comunidade GitHub (curadoria) no VectraClip

**Origem**: plano Skills Library + sessão Cursor, 2026-05-18  
**Destino**: agente frontend **VectraClip** (`C:\Users\marce\VectraClip`)  
**Escopo**: **somente frontend** — zero alteração em `VectraClaw/src/`, migrations ou `agent_mcp_bindings.py`  
**Paralelo**: outro spawn cobre **F1–F3** (types CONTRACTS §2, tab MCP no `AgentDetail`, hooks N6). **Este doc é só Fase A.**

---

## 1. Problema que resolve

`/admin/mcp` hoje lista apenas o **catálogo produto** (`vectraclip.mcp_server_catalog` via `GET /mcp/servers`).  
Não existe UI para **curar MCPs da comunidade GitHub** antes de virarem row no catálogo.

**Fase A** adiciona aba **Comunidade GitHub** em `/admin/mcp`:

- Browse + filtros sobre `docs/THE_RESOURCES_TABLE.csv` (comunidade awesome-claude-code).
- Diff vs catálogo live (`useMcpServers`).
- Fila local (`localStorage`) + export JSON para PMO / Fase B (`mcp_proposals`).

**Não faz:** POST catálogo, Athena, aprovação no backend.

---

## 2. Divisão de trabalho (não duplicar)

| Faixa | Dono | Entregar |
|-------|------|----------|
| **F1** | Spawn paralelo | Tipos MCP alinhados a [`CONTRACTS-MCP-BINDINGS.md`](./CONTRACTS-MCP-BINDINGS.md) §2; opcional Zod |
| **F2** | Spawn paralelo | `AgentMcpSection` espelhando padrão `SpecialtyConfigCard` no `AgentDetail` |
| **F3** | Spawn paralelo | Hooks React Query N6 (`useMcpServers`, bindings, handshake) |
| **Fase A (este doc)** | Agente deste handoff | Aba Comunidade + CSV→JSON + fila curadoria |

### Já implementado (não refazer)

| Artefato | Caminho VectraClip |
|----------|-------------------|
| Tipos MCP | `src/types/api.ts` (`McpServerCatalogItem`, `AgentMcpBinding`, …) |
| Endpoints | `src/lib/api/endpoints/mcpBindings.ts` |
| Hooks | `src/lib/queries/mcpBindings.ts` |
| Catálogo admin | `src/pages/AdminMcp.tsx` (somente produto) |
| Binding agente | `src/components/agents/detail/AgentMcpSection.tsx` |
| Rota + menu | `App.tsx` `/admin/mcp`, `Sidebar.tsx` |

**Fase A pode consumir** `useMcpServers()` — não alterar assinaturas dos hooks sem combinar com F3.

---

## 3. Decisões cravadas

1. **SSOT comunidade** = `VectraClaw/docs/THE_RESOURCES_TABLE.csv` (não editar na UI).
2. **`categories.yaml`** (Bloco de Notas) = vocabulário de **skills** import — **não** filtro primário de MCP.
3. **`mcp-github` em `adapter_catalog`** = adapter legado — badge `maybe_adapter`, não tratar como `mcp_server_catalog`.
4. **Curadoria Fase A** = `localStorage` + export JSON; publicação no DB = migration/seed ou Fase B.
5. **Português BR** em labels, toasts e comentários novos.

---

## 4. UX alvo — `/admin/mcp`

```text
┌─ MCP Servers ─────────────────────────────────────────────┐
│ [ Catálogo produto ] [ Comunidade GitHub ]     Fila (2) ▼ │
├───────────────────────────────────────────────────────────┤
│ Tab Comunidade:                                             │
│  Banner: marcar ≠ publicar no catálogo                      │
│  [ Busca ] [ Category ▼ ] [ Preset: MCP candidates ▼ ]      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Status │ Nome │ Cat. │ Repo │ Licença │ Ações        │  │
│  │ candidate │ VoiceMode MCP │ Tooling │ ... │ MIT │ …  │  │
│  └──────────────────────────────────────────────────────┘  │
│  Rodapé: N filtrados · X no catálogo · Fila: Y              │
└─────────────────────────────────────────────────────────────┘
```

### Preset de filtro `mcp-candidates` (default)

```text
active === true
AND category NOT IN ('Hooks', 'Status Lines', 'Output Styles', 'Slash-Commands')
AND (
  category IN ('Tooling', 'CLAUDE.md Files')
  OR LOWER(description) CONTAINS 'mcp'
  OR LOWER(displayName) CONTAINS 'mcp'
)
```

Chips adicionais: `tooling`, `claude-md-mcp`, `all-active`.

### Badges `catalogStatus` (diff vs `useMcpServers()`)

| Badge | Regra |
|-------|--------|
| `in_catalog` | `suggestedCatalogId` === algum `server.id` |
| `candidate` | não está no catálogo |
| `maybe_adapter` | slug/repo sugere `mcp-github`, `mcp-gmail`, `mcp-slack`, `mcp-imap` |

---

## 5. Tipos novos (Fase A — `src/lib/community/types.ts`)

```typescript
export type CommunityResource = {
  id: string
  displayName: string
  category: string
  subCategory: string | null
  primaryLink: string
  authorName: string | null
  license: string | null
  description: string
  active: boolean
  stale: boolean
  githubRepo: string | null       // "owner/repo" parseado de Primary Link
  suggestedCatalogId: string      // kebab-case do repo ou displayName
  mcpRelevance: 'high' | 'medium' | 'low'
}

export type McpCurationQueueItem = {
  resourceId: string
  displayName: string
  githubRepo: string | null
  primaryLink: string
  suggestedCatalogId: string
  proposedCategory: import('@/types/api').McpCategory
  proposedTransport: import('@/types/api').McpTransport
  notes: string
  markedAt: string
}

export type CatalogMatchStatus = 'in_catalog' | 'candidate' | 'maybe_adapter'
```

**Storage key fila:** `vectraclip-mcp-curation-queue-v1`

---

## 6. Build CSV → JSON

### Script

`VectraClip/scripts/build-community-resources.mjs`

- Input (default): `../../VectraClaw/docs/THE_RESOURCES_TABLE.csv` (path configurável por env `RESOURCES_CSV`).
- Output: `VectraClip/public/data/the-resources.json`
- Derivar: `githubRepo`, `suggestedCatalogId`, `mcpRelevance`, booleans `active`/`stale`.

### package.json

```json
"build:community-resources": "node scripts/build-community-resources.mjs"
```

Opcional: rodar em `prebuild` ou documentar passo manual no README do clip.

### Runtime

`useCommunityResources()` → `fetch('/data/the-resources.json')` + filtros client-side.

---

## 7. Árvore de arquivos a criar/alterar

```text
VectraClip/
  scripts/build-community-resources.mjs          # NOVO
  public/data/the-resources.json               # GERADO (commitar ou CI)
  src/lib/community/
    types.ts                                     # NOVO
    parseGithubRepo.ts                           # NOVO
    mcpRelevance.ts                              # NOVO
    catalogMatch.ts                              # NOVO
  src/lib/hooks/
    useCommunityResources.ts                     # NOVO
    useMcpCurationQueue.ts                       # NOVO
  src/components/admin/mcp/
    McpCatalogTab.tsx                            # NOVO (extrair AdminMcp atual)
    McpCommunityTab.tsx                          # NOVO
    McpCommunityTable.tsx                        # NOVO
    McpCurationQueueDrawer.tsx                   # NOVO
    McpCatalogStatusBadge.tsx                    # NOVO
  src/pages/AdminMcp.tsx                         # ALTERAR → Tabs
```

### Não tocar neste patch

- `VectraClaw/**` (backend)
- `AgentMcpSection.tsx` (spawn F2)
- `mcpBindings.ts` endpoints (spawn F3), exceto **import** de `useMcpServers` na aba Comunidade

---

## 8. Ações da UI (sem API nova)

| Ação | Comportamento |
|------|----------------|
| Abrir GitHub | `window.open(primaryLink)` |
| Marcar para curadoria | Append em `localStorage` (dedupe por `resourceId`) |
| Copiar id sugerido | `navigator.clipboard.writeText(suggestedCatalogId)` + toast |
| Exportar fila | Download `mcp-curation-queue-YYYY-MM-DD.json` |
| Remover da fila | Drawer |
| Ver draft catálogo (opcional) | Dialog read-only com shape `McpServerCatalogItem` default — **não persiste** |

---

## 9. Refatorar `AdminMcp.tsx`

```tsx
// Estrutura alvo
export function AdminMcp() {
  return (
    <div className="p-6 space-y-6">
      <Header />
      <Tabs defaultValue="catalog">
        <TabsList>
          <TabsTrigger value="catalog">Catálogo produto</TabsTrigger>
          <TabsTrigger value="community">Comunidade GitHub</TabsTrigger>
        </TabsList>
        <TabsContent value="catalog"><McpCatalogTab /></TabsContent>
        <TabsContent value="community"><McpCommunityTab /></TabsContent>
      </Tabs>
      <McpCurationQueueDrawer />
    </div>
  )
}
```

`McpCatalogTab` = conteúdo atual de `AdminMcp` (cards + `useMcpServers` + banner escopo global).

---

## 10. Heurísticas implementação

### `parseGithubRepo(url: string): string | null`

- Match `https://github.com/{owner}/{repo}` (strip `.git`, trailing slash).

### `suggestedCatalogId(displayName, githubRepo)`

1. Se `githubRepo` → último segmento do repo em kebab.  
2. Senão → `displayName` normalizado (lowercase, espaços → `-`, remove chars inválidos).

### `mcpRelevance(row)`

- `high`: "mcp" no nome ou descrição + category Tooling ou CLAUDE.md Files  
- `medium`: category Tooling sem mcp explícito  
- `low`: demais

### `catalogMatch(resource, servers, adapterSlugs?)`

- `in_catalog` se `servers.some(s => s.id === resource.suggestedCatalogId)`  
- `maybe_adapter` se `suggestedCatalogId` ou repo bate `mcp-github|mcp-gmail|mcp-slack|mcp-imap`  
- senão `candidate`

---

## 11. MSW / dev

- Servir `public/data/the-resources.json` no Vite dev.  
- Se JSON ausente, toast: *"Rode npm run build:community-resources"*.  
- `useMcpServers` pode falhar sem backend — aba Comunidade ainda funciona; badges `in_catalog` ficam vazios.

---

## 12. Critérios de aceite

- [ ] `/admin/mcp` com duas abas: **Catálogo produto** | **Comunidade GitHub**
- [ ] JSON gerado a partir do CSV com script documentado
- [ ] Preset `mcp-candidates` + busca + chips de categoria
- [ ] Badges `in_catalog` / `candidate` / `maybe_adapter` quando API online
- [ ] Fila localStorage + drawer + export JSON
- [ ] `npm run build` passa em VectraClip
- [ ] Zero diff em `VectraClaw/src/` e `supabase/migrations/`

---

## 13. Fase B (fora deste patch)

| Entrega Fase A | Consumo Fase B |
|----------------|----------------|
| `mcp-curation-queue-*.json` | Seed SQL ou `POST /api/mcp/proposals` |
| `suggestedCatalogId` | PK `mcp_server_catalog.id` |
| `maybe_adapter` | Não duplicar em MCP catalog |

Ver plano: `.cursor/plans/skills_library_architecture_31fdd4b2.plan.md` (todos `ddl-skill-proposals`, `admin-mcp-marketplace`).

---

## 14. Referências

| Doc | Uso |
|-----|-----|
| [`CONTRACTS-MCP-BINDINGS.md`](./CONTRACTS-MCP-BINDINGS.md) | Tipos + endpoints N6 (F1/F3) |
| [`THE_RESOURCES_TABLE.csv`](./THE_RESOURCES_TABLE.csv) | Input do build JSON |
| [`skills_library_architecture_31fdd4b2.plan.md`](../.cursor/plans/skills_library_architecture_31fdd4b2.plan.md) | Roadmap biblioteca |
| `VectraClip/src/pages/AdminMcp.tsx` | Refatorar em tabs |

---

## 15. Prompt copy-paste para o agente

```text
Implemente HANDOFF-MCP-PHASE-A-COMMUNITY.md no repo VectraClip (C:\Users\marce\VectraClip).

Regras:
- Somente frontend VectraClip. Não altere VectraClaw/src nem migrations.
- Não refaça tipos/hooks MCP já existentes (types/api.ts, mcpBindings.ts, mcpBindings queries).
- Não altere AgentMcpSection.tsx (outro agente cuida F2).

Entregas:
1. scripts/build-community-resources.mjs + npm script build:community-resources
2. public/data/the-resources.json (gerar uma vez)
3. src/lib/community/* + useCommunityResources + useMcpCurationQueue
4. Refatorar AdminMcp em Tabs: McpCatalogTab (extrair UI atual) + McpCommunityTab
5. Tabela comunidade com preset mcp-candidates, badges catalogStatus, fila localStorage, export JSON

Validar: npm run build
```

---

## 16. Smoke manual pós-patch

1. `cd VectraClip && npm run build:community-resources && npm run dev`
2. Login admin → `/admin/mcp` → aba **Comunidade GitHub** lista linhas.
3. Marcar 2 itens → drawer fila → export JSON.
4. Com API `:3100` up → badges `in_catalog` batem com tab **Catálogo produto**.
5. Agente → Configuração → MCP inalterado e funcional (regressão F2/F3).
