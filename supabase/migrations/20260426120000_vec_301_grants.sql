-- VEC-301: GRANTs for new tables (routines + agent_specialty_configs)
-- Without these, authenticated role gets 42501 even with RLS policies in place.

set search_path to vectraclip, public;

grant select, insert, update, delete on vectraclip.routines to authenticated;
grant select, insert, update, delete on vectraclip.agent_specialty_configs to authenticated;
