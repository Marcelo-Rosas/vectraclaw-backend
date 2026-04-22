-- =====================================================================
-- VEC-199: Seed de Company Tier para ambiente de dev
-- =====================================================================

-- Vectra Cargo = enterprise desde o dia 1.
update vectraclip.companies
   set tier = 'enterprise'
 where id = (select id from vectraclip.companies order by created_at asc limit 1);
