-- Ativa Claude 3.5 Haiku + Claude 3.5 Sonnet no catálogo vectraclip.llm_models
--
-- Contexto: as 2 rows já existem no DB (foram seedadas em migrations anteriores)
-- mas estão com is_active=false, por isso não aparecem no dropdown da UI:
--   - /admin/models
--   - tab Configuration do agente (campo Model)
--
-- Motivo de ativar agora: Kronos roda via adapter_type='claude_code' (subprocess
-- do CLI local, custo fixo via subscription Max plan). Para esse caso de uso,
-- Haiku 3.5 e Sonnet 3.5 são alternativas válidas que oferecem:
--   - Haiku 3.5:  rápido, ideal para fallbacks LLM raros e classificação leve
--   - Sonnet 3.5: balanceado, alternativa estável ao 4.6
--
-- Custo de tokens (apenas se algum agente futuro for migrado para adapter via API
-- direta — claude_code/CLI continua com custo flat):
--   - Haiku 3.5:  $0.80 input / $4.00 output por 1M tokens
--   - Sonnet 3.5: $3.00 input / $15.00 output por 1M tokens
--
-- Idempotente: UPDATE WHERE is_active = false (re-run não faz nada).

set search_path to vectraclip, public;

-- Nota: vectraclip.llm_models não tem coluna updated_at (PK composta por
-- (id, effective_from); novas versões viram INSERTs, não UPDATEs).
-- Por isso este UPDATE só toca o flag is_active.
update vectraclip.llm_models
   set is_active = true
 where id in (
   'claude-3-5-haiku-20241022',
   'claude-3-5-sonnet-20241022'
 )
   and is_active = false;

-- Verificação
do $$
declare
  v_active_count int;
begin
  select count(*) into v_active_count
    from vectraclip.llm_models
   where id in ('claude-3-5-haiku-20241022', 'claude-3-5-sonnet-20241022')
     and is_active = true;

  if v_active_count = 2 then
    raise notice 'Claude 3.5 Haiku + Sonnet ativados com sucesso';
  else
    raise warning 'Esperado 2 modelos ativos, encontrei % — verificar', v_active_count;
  end if;
end $$;
