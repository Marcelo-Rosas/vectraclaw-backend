# Documentação do backend VectraClaw

| Documento | Conteúdo |
|-----------|----------|
| [**SUPABASE_DUAL_CLIENT.md**](./SUPABASE_DUAL_CLIENT.md) | Dois clients Supabase (service_role vs anon): motivo, env vars, critério de aceite, `serve`, porta presa no Windows. |
| [VEC-199b-VectraClaw-Prompt-V1.1.md](./VEC-199b-VectraClaw-Prompt-V1.1.md) | Heartbeat Doctor V1.1 — persistência Postgres, dual client, audit 6-eventos, fix undo/get-by-id. |
| [VEC-189-VectraClaw-Prompt.md](./VEC-189-VectraClaw-Prompt.md) | E2E audit trail: parity report 9/9 checks + trilha task→claim→heartbeat→done. **Encerrado Done.** |
| [VEC-188-VectraClaw-Prompt.md](./VEC-188-VectraClaw-Prompt.md) | Self-healing DB: `db_failover.py`, 8 categorias de erro, `POST /api/db/retry`. **Encerrado Done.** |
| [VEC-187-VectraClaw-Prompt.md](./VEC-187-VectraClaw-Prompt.md) | Master System Prompt + Workflow Aduaneiro W1–W7: `brain/`, 3 endpoints `/api/agent/*`. **Encerrado Done.** |
| [VEC-186-VectraClaw-Prompt.md](./VEC-186-VectraClaw-Prompt.md) | WhatsApp via Meta Cloud API: `meta_client.py`, text + template, `POST /api/tools/send-whatsapp`. **Encerrado Done.** |
| [VEC-184-VectraClaw-Prompt.md](./VEC-184-VectraClaw-Prompt.md) | OCR Pipeline BL/PL: `bl_pl_parser.py`, `extract_bl_pl` real, `POST /api/tools/extract-bl-pl`. **Encerrado Done.** |
| [VEC-183-VectraClaw-Prompt.md](./VEC-183-VectraClaw-Prompt.md) | WebSocket em tempo real: `ConnectionManager`, `/ws/companies/{id}`, broadcasts task/agent/heartbeat. **Encerrado Done.** |
| [VEC-182-VectraClaw-Prompt.md](./VEC-182-VectraClaw-Prompt.md) | CRUD Tasks: POST real + PATCH parcial + `NewTaskInput` completo + status `blocked`. **Encerrado Done.** |
| [VEC-197b-…](./VEC-197b-VectraClaw-Prompt-V8.1.md), [VEC-194-…](./VEC-194-VectraClaw-Prompt-V6.1.md) | Contexto RLS / auth (resume→idle, kill zera burn, PATCH agents, CORS). |
