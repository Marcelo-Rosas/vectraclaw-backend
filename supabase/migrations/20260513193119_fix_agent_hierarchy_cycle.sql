-- HOTFIX (Task #35) — resolver inconsistências em vectraclip.agents.reports_to_id
--
-- Auditoria de hoje expôs:
--
--   Hermes (Email Monitoring)  reports_to → Hermes Reporter (executor)
--   Hermes Reporter (executor) reports_to → Hermes (Email Monitoring)
--   ⚠️ CICLO — cada um reporta pro outro
--
--   Plutus (role=CRM, financeiro originalmente)  reports_to → Hodos (Route/Cost)
--   ⚠️ DRIFT — domínios divergentes, sem rationale operacional
--
-- Fix:
--   - Hermes (top-level): reports_to = NULL (agente sistêmico, igual Morpheus/Oracle/Mnemos/Athena)
--   - Hermes Reporter: continua reports_to = Hermes (subordinado natural)
--   - Plutus: reports_to = NULL (sem chefia natural — domínio CRM isolado)
--
-- Demais agentes (Kronos, Mercator, Hodos) continuam reportando para Hermes,
-- que faz sentido como "agente coordenador de comunicação" do tier operacional.
--
-- Idempotente: UPDATE WHERE específico.

set search_path to vectraclip, public;

-- 1. Hermes vira top-level (quebra o ciclo)
update vectraclip.agents
   set reports_to_id = null,
       updated_at = now()
 where id = '59b7a69e-cc53-4063-85f9-5dcc5619ac96'   -- Hermes
   and reports_to_id = '360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1';  -- Hermes Reporter

-- 2. Plutus vira top-level (sem chefia natural via domínio)
update vectraclip.agents
   set reports_to_id = null,
       updated_at = now()
 where id = '80fd6d0e-53ab-4638-b6e9-05cbbd121092'   -- Plutus
   and reports_to_id = '0d6e56cc-28b6-4382-96cd-1952b890d412';  -- Hodos

-- Verificação
do $$
declare
  v_hermes_chief uuid;
  v_reporter_chief uuid;
  v_plutus_chief uuid;
  v_cycle_count int;
begin
  select reports_to_id into v_hermes_chief
    from vectraclip.agents where id = '59b7a69e-cc53-4063-85f9-5dcc5619ac96';
  select reports_to_id into v_reporter_chief
    from vectraclip.agents where id = '360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1';
  select reports_to_id into v_plutus_chief
    from vectraclip.agents where id = '80fd6d0e-53ab-4638-b6e9-05cbbd121092';

  -- Conta ciclos restantes (a reports_to b AND b reports_to a)
  select count(*) into v_cycle_count
    from vectraclip.agents a
    join vectraclip.agents b on b.id = a.reports_to_id
   where b.reports_to_id = a.id;

  if v_hermes_chief is null
     and v_reporter_chief = '59b7a69e-cc53-4063-85f9-5dcc5619ac96'
     and v_plutus_chief is null
     and v_cycle_count = 0 then
    raise notice 'Task #35 OK: hierarquia consistente (Hermes/Plutus top-level, Reporter→Hermes, 0 ciclos)';
  else
    raise warning 'Task #35: hermes=%, reporter=%, plutus=%, ciclos_restantes=%',
      v_hermes_chief, v_reporter_chief, v_plutus_chief, v_cycle_count;
  end if;
end $$;
