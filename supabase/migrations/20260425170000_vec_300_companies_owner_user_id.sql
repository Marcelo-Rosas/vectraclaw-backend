set search_path to vectraclip, public;

alter table vectraclip.companies
add column if not exists owner_user_id uuid;

do $$
begin
  if not exists (
    select 1
    from information_schema.table_constraints
    where table_schema = 'vectraclip'
      and table_name = 'companies'
      and constraint_name = 'companies_owner_user_id_fkey'
  ) then
    alter table vectraclip.companies
      add constraint companies_owner_user_id_fkey
      foreign key (owner_user_id)
      references auth.users(id)
      on delete restrict
      deferrable initially immediate;
  end if;
end $$;

with first_admin as (
  select distinct on (au.company_id)
         au.company_id,
         au.id as user_id
  from vectraclip.app_users au
  where lower(coalesce(au.role, '')) = 'admin'
  order by au.company_id, au.created_at asc
),
first_any as (
  select distinct on (au.company_id)
         au.company_id,
         au.id as user_id
  from vectraclip.app_users au
  order by au.company_id, au.created_at asc
),
chosen as (
  select c.company_id,
         coalesce(fa.user_id, fy.user_id) as user_id
  from vectraclip.companies c
  left join first_admin fa on fa.company_id = c.company_id
  left join first_any fy on fy.company_id = c.company_id
)
update vectraclip.companies c
set owner_user_id = ch.user_id
from chosen ch
where c.company_id = ch.company_id
  and c.owner_user_id is null
  and ch.user_id is not null;

create index if not exists idx_companies_owner_user_id
  on vectraclip.companies(owner_user_id);
