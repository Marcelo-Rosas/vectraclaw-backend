-- HOTFIX-4: fn_snapshot_agent_prompt precisa SECURITY DEFINER para o trigger
-- conseguir INSERT em vectraclip.agent_prompt_history quando o UPDATE em
-- vectraclip.agents é feito por um usuário com role `authenticated`.
--
-- Sintoma em produção:
--
--   PATCH /api/agents/9c8d7e6f-... HTTP/1.1 500 Internal Server Error
--   patch_agent failed: {
--     'code': '42501',
--     'message': 'permission denied for table agent_prompt_history'
--   }
--
-- Causa: o trigger `trg_agent_prompt_history` chama a função
-- `fn_snapshot_agent_prompt` que está marcada como SECURITY INVOKER (default).
-- Isso significa que ela herda as permissões do usuário que disparou o UPDATE
-- (no caso, role `authenticated`). Como esse role só tem GRANT SELECT em
-- `agent_prompt_history`, o INSERT do snapshot falha.
--
-- Fix: recriar a função com SECURITY DEFINER. Função passa a rodar como o
-- owner (postgres) que tem todos os grants. Adicionar `SET search_path` é
-- padrão de segurança recomendado pelo Supabase para evitar hijacking de
-- schema em funções DEFINER.
--
-- Idempotente: CREATE OR REPLACE.

set search_path to vectraclip, public;

create or replace function vectraclip.fn_snapshot_agent_prompt()
  returns trigger
  language plpgsql
  security definer
  set search_path = vectraclip, public
as $function$
declare
  next_version integer;
begin
  if old.system_prompt is distinct from new.system_prompt then
    select coalesce(max(version), 0) + 1 into next_version
    from vectraclip.agent_prompt_history
    where agent_id = new.id;

    insert into vectraclip.agent_prompt_history
      (agent_id, company_id, version, system_prompt, source, change_reason)
    values
      (new.id, new.company_id, next_version, old.system_prompt,
       'manual', 'Auto-snapshot before UPDATE in vectraclip.agents');
  end if;
  return new;
end;
$function$;

-- Garante que o owner da função é postgres (não o role que rodou esta migration)
alter function vectraclip.fn_snapshot_agent_prompt() owner to postgres;

-- Verificação
do $$
declare
  v_is_definer boolean;
begin
  select prosecdef into v_is_definer
  from pg_proc
  where oid = 'vectraclip.fn_snapshot_agent_prompt'::regproc;

  if v_is_definer then
    raise notice 'HOTFIX-4: fn_snapshot_agent_prompt agora é SECURITY DEFINER';
  else
    raise warning 'HOTFIX-4: função ainda como SECURITY INVOKER — verifique';
  end if;
end $$;
