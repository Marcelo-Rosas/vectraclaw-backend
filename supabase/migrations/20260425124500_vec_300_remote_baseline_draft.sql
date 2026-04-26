


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE SCHEMA IF NOT EXISTS "vectraclip";


ALTER SCHEMA "vectraclip" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."agent_execution_configs_sync_company_agent"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'vectraclip', 'public', 'pg_temp'
    AS $$
declare
  agent_company uuid;
begin
  select a.company_id
    into agent_company
  from vectraclip.agents a
  where a.id = new.agent_id;

  if agent_company is null then
    raise exception 'agent_id % not found in vectraclip.agents', new.agent_id;
  end if;

  if new.company_id is distinct from agent_company then
    raise exception 'company_id mismatch for agent_id % (expected %, got %)',
      new.agent_id, agent_company, new.company_id;
  end if;

  return new;
end;
$$;


ALTER FUNCTION "vectraclip"."agent_execution_configs_sync_company_agent"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."handle_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'vectraclip', 'public', 'pg_temp'
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "vectraclip"."handle_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."increment_task_cost"("p_task_id" "uuid", "p_delta" numeric) RETURNS "void"
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'vectraclip', 'public', 'pg_temp'
    AS $$
    UPDATE vectraclip.tasks
       SET cost_usd   = COALESCE(cost_usd, 0) + p_delta,
           updated_at = now()
     WHERE id = p_task_id;
$$;


ALTER FUNCTION "vectraclip"."increment_task_cost"("p_task_id" "uuid", "p_delta" numeric) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."sipoc_company_id"() RETURNS "uuid"
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'vectraclip', 'public', 'pg_temp'
    AS $$
    SELECT ((auth.jwt() -> 'app_metadata' -> 'vectraclip') ->> 'company_id')::UUID;
$$;


ALTER FUNCTION "vectraclip"."sipoc_company_id"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."validate_heartbeat_model_id"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'vectraclip', 'public', 'pg_temp'
    AS $$
begin
  if new.model_id is null then
    return new;
  end if;

  if exists (
    select 1
    from vectraclip.llm_models m
    where m.id = new.model_id
  ) then
    return new;
  end if;

  raise exception 'model_id % not found in vectraclip.llm_models', new.model_id;
end;
$$;


ALTER FUNCTION "vectraclip"."validate_heartbeat_model_id"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "vectraclip"."adapter_catalog" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "slug" "text" NOT NULL,
    "display_name" "text" NOT NULL,
    "provider" "text" NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."adapter_catalog" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."adapter_field_definitions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "adapter_id" "uuid" NOT NULL,
    "field_key" "text" NOT NULL,
    "field_label" "text" NOT NULL,
    "field_type" "text" NOT NULL,
    "is_required" boolean DEFAULT false NOT NULL,
    "options_json" "jsonb",
    "trigger_condition" "jsonb",
    "sort_order" integer DEFAULT 100 NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "adapter_field_definitions_field_type_check" CHECK (("field_type" = ANY (ARRAY['text'::"text", 'textarea'::"text", 'number'::"text", 'boolean'::"text", 'select'::"text", 'multiselect'::"text", 'file_upload'::"text", 'secret'::"text"])))
);


ALTER TABLE "vectraclip"."adapter_field_definitions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."agent_adapter_configs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "agent_id" "uuid" NOT NULL,
    "adapter_id" "uuid" NOT NULL,
    "field_values_json" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."agent_adapter_configs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."agent_execution_configs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "agent_id" "uuid" NOT NULL,
    "execution_mode" "text" NOT NULL,
    "trigger_config" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "function_url" "text",
    "auth_secret_ref" "text",
    "auth_header_name" "text",
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "agent_execution_configs_execution_mode_check" CHECK (("execution_mode" = ANY (ARRAY['REALTIME'::"text", 'CRON'::"text", 'TRIGGER'::"text"])))
);


ALTER TABLE "vectraclip"."agent_execution_configs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."agent_specialties" (
    "id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "slug" "text" NOT NULL,
    "domain" "text" NOT NULL,
    "description" "text",
    "compatible_roles" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "system_prompt_template" "text" DEFAULT ''::"text" NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."agent_specialties" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."agents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "role" "text" DEFAULT ''::"text" NOT NULL,
    "reports_to_id" "uuid",
    "status" "text" NOT NULL,
    "token_budget" integer DEFAULT 0 NOT NULL,
    "current_burn_rate" numeric DEFAULT 0 NOT NULL,
    "adapter_type" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "agents_adapter_type_check" CHECK (("adapter_type" = ANY (ARRAY['claude_code'::"text", 'cursor'::"text", 'bot'::"text"]))),
    CONSTRAINT "agents_current_burn_rate_check" CHECK (("current_burn_rate" >= (0)::numeric)),
    CONSTRAINT "agents_status_check" CHECK (("status" = ANY (ARRAY['working'::"text", 'idle'::"text", 'paused'::"text", 'errored'::"text", 'offline'::"text"]))),
    CONSTRAINT "agents_token_budget_check" CHECK (("token_budget" >= 0))
);


ALTER TABLE "vectraclip"."agents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."app_users" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "email" "text" NOT NULL,
    "name" "text" NOT NULL,
    "role" "text" NOT NULL,
    "company_id" "uuid" NOT NULL,
    "avatar_url" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "app_users_role_check" CHECK (("role" = ANY (ARRAY['admin'::"text", 'operator'::"text", 'viewer'::"text"])))
);


ALTER TABLE "vectraclip"."app_users" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."companies" (
    "company_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "tier" "text" DEFAULT 'trial'::"text" NOT NULL,
    CONSTRAINT "companies_tier_check" CHECK (("tier" = ANY (ARRAY['trial'::"text", 'standard'::"text", 'enterprise'::"text"])))
);


ALTER TABLE "vectraclip"."companies" OWNER TO "postgres";


COMMENT ON COLUMN "vectraclip"."companies"."company_id" IS 'company';



CREATE TABLE IF NOT EXISTS "vectraclip"."goals" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "parent_goal_id" "uuid",
    "title" "text" NOT NULL,
    "metric" "text" DEFAULT ''::"text" NOT NULL,
    "target" numeric DEFAULT 100 NOT NULL,
    "current" numeric DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."goals" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."heartbeats" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "agent_id" "uuid" NOT NULL,
    "task_id" "uuid",
    "status" "text" NOT NULL,
    "tokens_used" integer DEFAULT 0 NOT NULL,
    "log_excerpt" "text" DEFAULT ''::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "input_tokens" integer DEFAULT 0 NOT NULL,
    "output_tokens" integer DEFAULT 0 NOT NULL,
    "cache_read_tokens" integer DEFAULT 0 NOT NULL,
    "model_id" "text",
    "cost_usd" numeric(12,8),
    CONSTRAINT "heartbeats_cache_read_tokens_nonnegative" CHECK (("cache_read_tokens" >= 0)),
    CONSTRAINT "heartbeats_cost_usd_nonnegative" CHECK ((("cost_usd" IS NULL) OR ("cost_usd" >= (0)::numeric))),
    CONSTRAINT "heartbeats_input_tokens_nonnegative" CHECK (("input_tokens" >= 0)),
    CONSTRAINT "heartbeats_output_tokens_nonnegative" CHECK (("output_tokens" >= 0)),
    CONSTRAINT "heartbeats_status_check" CHECK (("status" = ANY (ARRAY['working'::"text", 'idle'::"text", 'paused'::"text", 'errored'::"text", 'offline'::"text"]))),
    CONSTRAINT "heartbeats_tokens_used_check" CHECK (("tokens_used" >= 0))
);


ALTER TABLE "vectraclip"."heartbeats" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."incident_audit" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "incident_id" "uuid" NOT NULL,
    "event" "text" NOT NULL,
    "actor" "text" NOT NULL,
    "payload" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."incident_audit" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."incidents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "agent_id" "uuid" NOT NULL,
    "symptom" "text" NOT NULL,
    "fix_applied" "text",
    "severity" "text" NOT NULL,
    "severity_score" integer NOT NULL,
    "agent_snapshot" "jsonb" NOT NULL,
    "decision" "text" NOT NULL,
    "undo_expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolved_at" timestamp with time zone,
    CONSTRAINT "incidents_decision_check" CHECK (("decision" = ANY (ARRAY['auto_healed'::"text", 'pending_council'::"text", 'approved'::"text", 'rejected'::"text", 'undone'::"text", 'manual_fix_required'::"text"]))),
    CONSTRAINT "incidents_severity_check" CHECK (("severity" = ANY (ARRAY['low'::"text", 'medium'::"text", 'high'::"text"]))),
    CONSTRAINT "incidents_severity_score_check" CHECK ((("severity_score" >= 0) AND ("severity_score" <= 10)))
);


ALTER TABLE "vectraclip"."incidents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."llm_models" (
    "id" "text" NOT NULL,
    "provider" "text" NOT NULL,
    "display_name" "text" NOT NULL,
    "input_cost_per_1m" numeric(12,4) NOT NULL,
    "output_cost_per_1m" numeric(12,4) NOT NULL,
    "cache_read_cost_per_1m" numeric(12,4) NOT NULL,
    "context_window_k" integer NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "effective_from" "date" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "llm_models_cache_read_cost_per_1m_check" CHECK (("cache_read_cost_per_1m" >= (0)::numeric)),
    CONSTRAINT "llm_models_context_window_k_check" CHECK (("context_window_k" > 0)),
    CONSTRAINT "llm_models_input_cost_per_1m_check" CHECK (("input_cost_per_1m" >= (0)::numeric)),
    CONSTRAINT "llm_models_output_cost_per_1m_check" CHECK (("output_cost_per_1m" >= (0)::numeric))
);


ALTER TABLE "vectraclip"."llm_models" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."managed_agent_sessions" (
    "session_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "task_id" "uuid" NOT NULL,
    "agent_id" "uuid",
    "model" "text" DEFAULT 'claude-haiku-4-5-20251001'::"text" NOT NULL,
    "status" "text" DEFAULT 'in_progress'::"text" NOT NULL,
    "executor_type" "text" DEFAULT 'managed_agent'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "started_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "completed_at" timestamp with time zone,
    "final_output" "text",
    "error_message" "text",
    "tokens_input" integer DEFAULT 0 NOT NULL,
    "tokens_output" integer DEFAULT 0 NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    CONSTRAINT "managed_agent_sessions_status_check" CHECK (("status" = ANY (ARRAY['in_progress'::"text", 'completed'::"text", 'failed'::"text"])))
);


ALTER TABLE "vectraclip"."managed_agent_sessions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."managed_agent_turn_logs" (
    "id" bigint NOT NULL,
    "session_id" "uuid" NOT NULL,
    "turn_number" integer NOT NULL,
    "input_text" "text" DEFAULT ''::"text" NOT NULL,
    "tool_used" "text",
    "tool_input" "jsonb",
    "output_text" "text" DEFAULT ''::"text" NOT NULL,
    "stop_reason" "text" DEFAULT 'end_turn'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."managed_agent_turn_logs" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "vectraclip"."managed_agent_turn_logs_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "vectraclip"."managed_agent_turn_logs_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "vectraclip"."managed_agent_turn_logs_id_seq" OWNED BY "vectraclip"."managed_agent_turn_logs"."id";



CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_companies" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "logo_url" "text",
    "website" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "vectraclip"."sipoc_companies" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_components" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "process_id" "uuid" NOT NULL,
    "type" "text" NOT NULL,
    "content" "jsonb" NOT NULL,
    "order" integer DEFAULT 0 NOT NULL,
    "validation_status" "text" DEFAULT 'verde'::"text",
    "validation_notes" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "vectraclip"."sipoc_components" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_positions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "sector_id" "uuid",
    "title" "text" NOT NULL,
    "description" "text",
    "reports_to_id" "uuid",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "vectraclip"."sipoc_positions" OWNER TO "postgres";


COMMENT ON TABLE "vectraclip"."sipoc_positions" IS 'Representa o organograma corporativo vinculado ao SIPOC';



CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_processes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sector_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "status" "text" DEFAULT 'rascunho'::"text",
    "version" integer DEFAULT 1,
    "responsible_id" "uuid",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "position_id" "uuid"
);


ALTER TABLE "vectraclip"."sipoc_processes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_sector_baselines" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sector_slug" "text" NOT NULL,
    "sector_display_name" "text" NOT NULL,
    "baseline" "jsonb" NOT NULL,
    "source" "text" DEFAULT 'seed'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "vectraclip"."sipoc_sector_baselines" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_sectors" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "slug" "text" NOT NULL,
    "icon" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "parent_sector_id" "uuid"
);


ALTER TABLE "vectraclip"."sipoc_sectors" OWNER TO "postgres";


COMMENT ON COLUMN "vectraclip"."sipoc_sectors"."parent_sector_id" IS 'ID do setor pai para hierarquia organizacional';



CREATE TABLE IF NOT EXISTS "vectraclip"."tasks" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "assigned_to_agent_id" "uuid",
    "parent_task_id" "uuid",
    "goal_id" "uuid",
    "title" "text" NOT NULL,
    "description" "text" DEFAULT ''::"text" NOT NULL,
    "status" "text" DEFAULT 'backlog'::"text" NOT NULL,
    "budget_limit" integer DEFAULT 0 NOT NULL,
    "spent" numeric DEFAULT 0 NOT NULL,
    "claimed_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "operation_type" "text" DEFAULT 'other'::"text" NOT NULL,
    "cost_usd" numeric(12,8) DEFAULT 0 NOT NULL,
    "executor_type" "text" DEFAULT 'auto'::"text",
    "managed_agent_session_id" "uuid",
    "executor_selected_at" timestamp with time zone,
    "executor_rationale" "text",
    CONSTRAINT "tasks_budget_limit_check" CHECK (("budget_limit" >= 0)),
    CONSTRAINT "tasks_cost_usd_nonnegative" CHECK (("cost_usd" >= (0)::numeric)),
    CONSTRAINT "tasks_executor_type_check" CHECK (("executor_type" = ANY (ARRAY['harness'::"text", 'managed_agent'::"text", 'auto'::"text"]))),
    CONSTRAINT "tasks_operation_type_check" CHECK (("operation_type" = ANY (ARRAY['orchestration'::"text", 'code_generation'::"text", 'code_review'::"text", 'research'::"text", 'document_generation'::"text", 'qa_testing'::"text", 'other'::"text"]))),
    CONSTRAINT "tasks_spent_check" CHECK (("spent" >= (0)::numeric)),
    CONSTRAINT "tasks_status_check" CHECK (("status" = ANY (ARRAY['backlog'::"text", 'queued'::"text", 'in_progress'::"text", 'review'::"text", 'done'::"text"])))
);


ALTER TABLE "vectraclip"."tasks" OWNER TO "postgres";


ALTER TABLE ONLY "vectraclip"."managed_agent_turn_logs" ALTER COLUMN "id" SET DEFAULT "nextval"('"vectraclip"."managed_agent_turn_logs_id_seq"'::"regclass");



ALTER TABLE ONLY "vectraclip"."adapter_catalog"
    ADD CONSTRAINT "adapter_catalog_company_entity_key" UNIQUE ("company_id", "id");



ALTER TABLE ONLY "vectraclip"."adapter_catalog"
    ADD CONSTRAINT "adapter_catalog_company_id_slug_key" UNIQUE ("company_id", "slug");



ALTER TABLE ONLY "vectraclip"."adapter_catalog"
    ADD CONSTRAINT "adapter_catalog_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."adapter_field_definitions"
    ADD CONSTRAINT "adapter_field_definitions_company_id_adapter_id_field_key_key" UNIQUE ("company_id", "adapter_id", "field_key");



ALTER TABLE ONLY "vectraclip"."adapter_field_definitions"
    ADD CONSTRAINT "adapter_field_definitions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."agent_adapter_configs"
    ADD CONSTRAINT "agent_adapter_configs_agent_id_key" UNIQUE ("agent_id");



ALTER TABLE ONLY "vectraclip"."agent_adapter_configs"
    ADD CONSTRAINT "agent_adapter_configs_company_id_agent_id_key" UNIQUE ("company_id", "agent_id");



ALTER TABLE ONLY "vectraclip"."agent_adapter_configs"
    ADD CONSTRAINT "agent_adapter_configs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."agent_execution_configs"
    ADD CONSTRAINT "agent_execution_configs_agent_id_key" UNIQUE ("agent_id");



ALTER TABLE ONLY "vectraclip"."agent_execution_configs"
    ADD CONSTRAINT "agent_execution_configs_company_id_agent_id_key" UNIQUE ("company_id", "agent_id");



ALTER TABLE ONLY "vectraclip"."agent_execution_configs"
    ADD CONSTRAINT "agent_execution_configs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."agent_specialties"
    ADD CONSTRAINT "agent_specialties_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."agent_specialties"
    ADD CONSTRAINT "agent_specialties_slug_key" UNIQUE ("slug");



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_company_entity_key" UNIQUE ("company_id", "id");



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."app_users"
    ADD CONSTRAINT "app_users_email_key" UNIQUE ("email");



ALTER TABLE ONLY "vectraclip"."app_users"
    ADD CONSTRAINT "app_users_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."companies"
    ADD CONSTRAINT "companies_pkey" PRIMARY KEY ("company_id");



ALTER TABLE ONLY "vectraclip"."goals"
    ADD CONSTRAINT "goals_company_entity_key" UNIQUE ("company_id", "id");



ALTER TABLE ONLY "vectraclip"."goals"
    ADD CONSTRAINT "goals_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."heartbeats"
    ADD CONSTRAINT "heartbeats_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."incident_audit"
    ADD CONSTRAINT "incident_audit_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."incidents"
    ADD CONSTRAINT "incidents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."llm_models"
    ADD CONSTRAINT "llm_models_pkey" PRIMARY KEY ("id", "effective_from");



ALTER TABLE ONLY "vectraclip"."managed_agent_sessions"
    ADD CONSTRAINT "managed_agent_sessions_pkey" PRIMARY KEY ("session_id");



ALTER TABLE ONLY "vectraclip"."managed_agent_turn_logs"
    ADD CONSTRAINT "managed_agent_turn_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_companies"
    ADD CONSTRAINT "sipoc_companies_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_components"
    ADD CONSTRAINT "sipoc_components_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_positions"
    ADD CONSTRAINT "sipoc_positions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_processes"
    ADD CONSTRAINT "sipoc_processes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_sector_baselines"
    ADD CONSTRAINT "sipoc_sector_baselines_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_sector_baselines"
    ADD CONSTRAINT "sipoc_sector_baselines_sector_slug_key" UNIQUE ("sector_slug");



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_company_id_slug_key" UNIQUE ("company_id", "slug");



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_company_entity_key" UNIQUE ("company_id", "id");



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_pkey" PRIMARY KEY ("id");



CREATE INDEX "adapter_catalog_company_active_idx" ON "vectraclip"."adapter_catalog" USING "btree" ("company_id", "is_active");



CREATE INDEX "adapter_field_definitions_adapter_active_idx" ON "vectraclip"."adapter_field_definitions" USING "btree" ("adapter_id", "is_active", "sort_order");



CREATE INDEX "adapter_field_definitions_company_adapter_idx" ON "vectraclip"."adapter_field_definitions" USING "btree" ("company_id", "adapter_id");



CREATE INDEX "agent_adapter_configs_adapter_idx" ON "vectraclip"."agent_adapter_configs" USING "btree" ("adapter_id");



CREATE INDEX "agent_adapter_configs_company_agent_idx" ON "vectraclip"."agent_adapter_configs" USING "btree" ("company_id", "agent_id");



CREATE INDEX "agent_execution_configs_agent_idx" ON "vectraclip"."agent_execution_configs" USING "btree" ("agent_id");



CREATE INDEX "agent_execution_configs_company_active_idx" ON "vectraclip"."agent_execution_configs" USING "btree" ("company_id", "is_active");



CREATE INDEX "agent_specialties_is_active_idx" ON "vectraclip"."agent_specialties" USING "btree" ("is_active");



CREATE INDEX "goals_company_id_idx" ON "vectraclip"."goals" USING "btree" ("company_id");



CREATE INDEX "goals_parent_goal_id_idx" ON "vectraclip"."goals" USING "btree" ("parent_goal_id");



CREATE INDEX "heartbeats_model_id_idx" ON "vectraclip"."heartbeats" USING "btree" ("model_id");



CREATE INDEX "idx_vectraclip_agents_company_id" ON "vectraclip"."agents" USING "btree" ("company_id");



CREATE INDEX "idx_vectraclip_agents_company_status" ON "vectraclip"."agents" USING "btree" ("company_id", "status");



CREATE INDEX "idx_vectraclip_agents_reports_to_id" ON "vectraclip"."agents" USING "btree" ("reports_to_id");



CREATE INDEX "idx_vectraclip_app_users_company_id" ON "vectraclip"."app_users" USING "btree" ("company_id");



CREATE INDEX "idx_vectraclip_heartbeats_agent_created_desc" ON "vectraclip"."heartbeats" USING "btree" ("agent_id", "created_at" DESC);



CREATE INDEX "idx_vectraclip_heartbeats_agent_id" ON "vectraclip"."heartbeats" USING "btree" ("agent_id");



CREATE INDEX "idx_vectraclip_heartbeats_company_created_desc" ON "vectraclip"."heartbeats" USING "btree" ("company_id", "created_at" DESC);



CREATE INDEX "idx_vectraclip_heartbeats_company_id" ON "vectraclip"."heartbeats" USING "btree" ("company_id");



CREATE INDEX "idx_vectraclip_heartbeats_task_id" ON "vectraclip"."heartbeats" USING "btree" ("task_id");



CREATE INDEX "idx_vectraclip_tasks_assigned_to_agent_id" ON "vectraclip"."tasks" USING "btree" ("assigned_to_agent_id");



CREATE INDEX "idx_vectraclip_tasks_company_id" ON "vectraclip"."tasks" USING "btree" ("company_id");



CREATE INDEX "idx_vectraclip_tasks_company_status" ON "vectraclip"."tasks" USING "btree" ("company_id", "status");



CREATE INDEX "idx_vectraclip_tasks_goal_id" ON "vectraclip"."tasks" USING "btree" ("goal_id");



CREATE INDEX "idx_vectraclip_tasks_parent_task_id" ON "vectraclip"."tasks" USING "btree" ("parent_task_id");



CREATE INDEX "incident_audit_incident_idx" ON "vectraclip"."incident_audit" USING "btree" ("incident_id", "created_at");



CREATE INDEX "incidents_agent_created_idx" ON "vectraclip"."incidents" USING "btree" ("agent_id", "created_at" DESC);



CREATE INDEX "incidents_company_created_idx" ON "vectraclip"."incidents" USING "btree" ("company_id", "created_at" DESC);



CREATE INDEX "incidents_pending_idx" ON "vectraclip"."incidents" USING "btree" ("company_id") WHERE ("decision" = 'pending_council'::"text");



CREATE INDEX "llm_models_id_effective_from_desc_idx" ON "vectraclip"."llm_models" USING "btree" ("id", "effective_from" DESC);



CREATE INDEX "llm_models_provider_is_active_idx" ON "vectraclip"."llm_models" USING "btree" ("provider", "is_active");



CREATE INDEX "managed_agent_sessions_status_idx" ON "vectraclip"."managed_agent_sessions" USING "btree" ("status");



CREATE INDEX "managed_agent_sessions_task_id_idx" ON "vectraclip"."managed_agent_sessions" USING "btree" ("task_id");



CREATE INDEX "managed_agent_turn_logs_session_idx" ON "vectraclip"."managed_agent_turn_logs" USING "btree" ("session_id", "turn_number");



CREATE INDEX "tasks_operation_type_idx" ON "vectraclip"."tasks" USING "btree" ("operation_type");



CREATE OR REPLACE TRIGGER "set_updated_at_agents" BEFORE UPDATE ON "vectraclip"."agents" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_app_users" BEFORE UPDATE ON "vectraclip"."app_users" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_companies" BEFORE UPDATE ON "vectraclip"."companies" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_heartbeats" BEFORE UPDATE ON "vectraclip"."heartbeats" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_companies" BEFORE UPDATE ON "vectraclip"."sipoc_companies" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_components" BEFORE UPDATE ON "vectraclip"."sipoc_components" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_positions" BEFORE UPDATE ON "vectraclip"."sipoc_positions" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_processes" BEFORE UPDATE ON "vectraclip"."sipoc_processes" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_sector_baselines" BEFORE UPDATE ON "vectraclip"."sipoc_sector_baselines" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_sectors" BEFORE UPDATE ON "vectraclip"."sipoc_sectors" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_tasks" BEFORE UPDATE ON "vectraclip"."tasks" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "trg_agent_execution_configs_sync_company_agent" BEFORE INSERT OR UPDATE OF "company_id", "agent_id" ON "vectraclip"."agent_execution_configs" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."agent_execution_configs_sync_company_agent"();



CREATE OR REPLACE TRIGGER "trg_heartbeats_validate_model_id" BEFORE INSERT OR UPDATE OF "model_id" ON "vectraclip"."heartbeats" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."validate_heartbeat_model_id"();



ALTER TABLE ONLY "vectraclip"."adapter_catalog"
    ADD CONSTRAINT "adapter_catalog_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."adapter_field_definitions"
    ADD CONSTRAINT "adapter_field_definitions_adapter_company_fkey" FOREIGN KEY ("company_id", "adapter_id") REFERENCES "vectraclip"."adapter_catalog"("company_id", "id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."adapter_field_definitions"
    ADD CONSTRAINT "adapter_field_definitions_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agent_adapter_configs"
    ADD CONSTRAINT "agent_adapter_configs_adapter_company_fkey" FOREIGN KEY ("company_id", "adapter_id") REFERENCES "vectraclip"."adapter_catalog"("company_id", "id") ON DELETE RESTRICT;



ALTER TABLE ONLY "vectraclip"."agent_adapter_configs"
    ADD CONSTRAINT "agent_adapter_configs_agent_company_fkey" FOREIGN KEY ("company_id", "agent_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agent_adapter_configs"
    ADD CONSTRAINT "agent_adapter_configs_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agent_execution_configs"
    ADD CONSTRAINT "agent_execution_configs_agent_company_fkey" FOREIGN KEY ("company_id", "agent_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agent_execution_configs"
    ADD CONSTRAINT "agent_execution_configs_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_reports_to_company_fkey" FOREIGN KEY ("company_id", "reports_to_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."app_users"
    ADD CONSTRAINT "app_users_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."goals"
    ADD CONSTRAINT "goals_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."goals"
    ADD CONSTRAINT "goals_parent_goal_company_fkey" FOREIGN KEY ("company_id", "parent_goal_id") REFERENCES "vectraclip"."goals"("company_id", "id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."heartbeats"
    ADD CONSTRAINT "heartbeats_agent_company_fkey" FOREIGN KEY ("company_id", "agent_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."heartbeats"
    ADD CONSTRAINT "heartbeats_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."heartbeats"
    ADD CONSTRAINT "heartbeats_task_company_fkey" FOREIGN KEY ("company_id", "task_id") REFERENCES "vectraclip"."tasks"("company_id", "id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."incident_audit"
    ADD CONSTRAINT "incident_audit_incident_id_fkey" FOREIGN KEY ("incident_id") REFERENCES "vectraclip"."incidents"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."incidents"
    ADD CONSTRAINT "incidents_agent_company_fkey" FOREIGN KEY ("company_id", "agent_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."incidents"
    ADD CONSTRAINT "incidents_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."managed_agent_sessions"
    ADD CONSTRAINT "managed_agent_sessions_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "vectraclip"."agents"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."managed_agent_sessions"
    ADD CONSTRAINT "managed_agent_sessions_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "vectraclip"."tasks"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."managed_agent_turn_logs"
    ADD CONSTRAINT "managed_agent_turn_logs_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "vectraclip"."managed_agent_sessions"("session_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_components"
    ADD CONSTRAINT "sipoc_components_process_id_fkey" FOREIGN KEY ("process_id") REFERENCES "vectraclip"."sipoc_processes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_positions"
    ADD CONSTRAINT "sipoc_positions_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."sipoc_companies"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_positions"
    ADD CONSTRAINT "sipoc_positions_reports_to_id_fkey" FOREIGN KEY ("reports_to_id") REFERENCES "vectraclip"."sipoc_positions"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."sipoc_positions"
    ADD CONSTRAINT "sipoc_positions_sector_id_fkey" FOREIGN KEY ("sector_id") REFERENCES "vectraclip"."sipoc_sectors"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."sipoc_processes"
    ADD CONSTRAINT "sipoc_processes_position_id_fkey" FOREIGN KEY ("position_id") REFERENCES "vectraclip"."sipoc_positions"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."sipoc_processes"
    ADD CONSTRAINT "sipoc_processes_sector_id_fkey" FOREIGN KEY ("sector_id") REFERENCES "vectraclip"."sipoc_sectors"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."sipoc_companies"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_parent_sector_id_fkey" FOREIGN KEY ("parent_sector_id") REFERENCES "vectraclip"."sipoc_sectors"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_assigned_agent_company_fkey" FOREIGN KEY ("company_id", "assigned_to_agent_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_goal_company_fkey" FOREIGN KEY ("company_id", "goal_id") REFERENCES "vectraclip"."goals"("company_id", "id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_parent_task_company_fkey" FOREIGN KEY ("company_id", "parent_task_id") REFERENCES "vectraclip"."tasks"("company_id", "id") ON DELETE SET NULL;



ALTER TABLE "vectraclip"."adapter_catalog" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "adapter_catalog_select_authenticated" ON "vectraclip"."adapter_catalog" FOR SELECT TO "authenticated" USING (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id"));



CREATE POLICY "adapter_catalog_write_service_role" ON "vectraclip"."adapter_catalog" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."adapter_field_definitions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "adapter_fields_select_authenticated" ON "vectraclip"."adapter_field_definitions" FOR SELECT TO "authenticated" USING (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id"));



CREATE POLICY "adapter_fields_write_service_role" ON "vectraclip"."adapter_field_definitions" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agent_adapter_configs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_adapter_configs_select_authenticated" ON "vectraclip"."agent_adapter_configs" FOR SELECT TO "authenticated" USING (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id"));



CREATE POLICY "agent_adapter_configs_write_service_role" ON "vectraclip"."agent_adapter_configs" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agent_execution_configs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_execution_configs_select_authenticated" ON "vectraclip"."agent_execution_configs" FOR SELECT TO "authenticated" USING (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id"));



CREATE POLICY "agent_execution_configs_write_service_role" ON "vectraclip"."agent_execution_configs" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agent_specialties" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_specialties_select_authenticated" ON "vectraclip"."agent_specialties" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "agent_specialties_write_service_role" ON "vectraclip"."agent_specialties" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agents_delete_own_company_admin" ON "vectraclip"."agents" FOR DELETE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "agents_insert_own_company_admin_op" ON "vectraclip"."agents" FOR INSERT TO "authenticated" WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "agents_select_own_company" ON "vectraclip"."agents" FOR SELECT TO "authenticated" USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "agents_update_own_company_admin_op" ON "vectraclip"."agents" FOR UPDATE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = ANY (ARRAY['admin'::"text", 'operator'::"text"])))) WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "agents_write_service_role" ON "vectraclip"."agents" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."app_users" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "app_users_delete_admin" ON "vectraclip"."app_users" FOR DELETE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "app_users_insert_admin" ON "vectraclip"."app_users" FOR INSERT TO "authenticated" WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "app_users_select_own_company" ON "vectraclip"."app_users" FOR SELECT TO "authenticated" USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "app_users_update_admin" ON "vectraclip"."app_users" FOR UPDATE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text"))) WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



ALTER TABLE "vectraclip"."companies" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "companies_select_own" ON "vectraclip"."companies" FOR SELECT TO "authenticated" USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "companies_update_admin" ON "vectraclip"."companies" FOR UPDATE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text"))) WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "company members can manage goals" ON "vectraclip"."goals" USING (("company_id" = ( SELECT (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" AS "uuid")));



ALTER TABLE "vectraclip"."goals" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."heartbeats" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "heartbeats_delete_own_company_admin" ON "vectraclip"."heartbeats" FOR DELETE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "heartbeats_insert_own_company" ON "vectraclip"."heartbeats" FOR INSERT TO "authenticated" WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "heartbeats_select_own_company" ON "vectraclip"."heartbeats" FOR SELECT TO "authenticated" USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "heartbeats_update_own_company_admin" ON "vectraclip"."heartbeats" FOR UPDATE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text"))) WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



ALTER TABLE "vectraclip"."incident_audit" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "incident_audit_select_own_company" ON "vectraclip"."incident_audit" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "vectraclip"."incidents" "i"
  WHERE (("i"."id" = "incident_audit"."incident_id") AND ("i"."company_id" = (("auth"."jwt"() ->> 'company_id'::"text"))::"uuid")))));



ALTER TABLE "vectraclip"."incidents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "incidents_select_own_company" ON "vectraclip"."incidents" FOR SELECT TO "authenticated" USING (("company_id" = (("auth"."jwt"() ->> 'company_id'::"text"))::"uuid"));



ALTER TABLE "vectraclip"."llm_models" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "llm_models_select_authenticated" ON "vectraclip"."llm_models" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "llm_models_write_service_role" ON "vectraclip"."llm_models" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."managed_agent_sessions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."managed_agent_turn_logs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "service_role full access on managed_agent_sessions" ON "vectraclip"."managed_agent_sessions" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "service_role full access on managed_agent_turn_logs" ON "vectraclip"."managed_agent_turn_logs" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."sipoc_companies" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_companies_tenant_delete" ON "vectraclip"."sipoc_companies" FOR DELETE USING (("id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_companies_tenant_select" ON "vectraclip"."sipoc_companies" FOR SELECT USING (("id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_companies_tenant_update" ON "vectraclip"."sipoc_companies" FOR UPDATE USING (("id" = "vectraclip"."sipoc_company_id"())) WITH CHECK (("id" = "vectraclip"."sipoc_company_id"()));



ALTER TABLE "vectraclip"."sipoc_components" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_components_tenant_delete" ON "vectraclip"."sipoc_components" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_components"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_components_tenant_insert" ON "vectraclip"."sipoc_components" FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_components"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_components_tenant_select" ON "vectraclip"."sipoc_components" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_components"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_components_tenant_update" ON "vectraclip"."sipoc_components" FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_components"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



ALTER TABLE "vectraclip"."sipoc_positions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_positions_tenant_delete" ON "vectraclip"."sipoc_positions" FOR DELETE USING (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_positions_tenant_insert" ON "vectraclip"."sipoc_positions" FOR INSERT WITH CHECK (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_positions_tenant_select" ON "vectraclip"."sipoc_positions" FOR SELECT USING (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_positions_tenant_update" ON "vectraclip"."sipoc_positions" FOR UPDATE USING (("company_id" = "vectraclip"."sipoc_company_id"())) WITH CHECK (("company_id" = "vectraclip"."sipoc_company_id"()));



ALTER TABLE "vectraclip"."sipoc_processes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_processes_tenant_delete" ON "vectraclip"."sipoc_processes" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM "vectraclip"."sipoc_sectors" "s"
  WHERE (("s"."id" = "sipoc_processes"."sector_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_processes_tenant_insert" ON "vectraclip"."sipoc_processes" FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM "vectraclip"."sipoc_sectors" "s"
  WHERE (("s"."id" = "sipoc_processes"."sector_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_processes_tenant_select" ON "vectraclip"."sipoc_processes" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "vectraclip"."sipoc_sectors" "s"
  WHERE (("s"."id" = "sipoc_processes"."sector_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_processes_tenant_update" ON "vectraclip"."sipoc_processes" FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM "vectraclip"."sipoc_sectors" "s"
  WHERE (("s"."id" = "sipoc_processes"."sector_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



ALTER TABLE "vectraclip"."sipoc_sector_baselines" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_sector_baselines_select_all" ON "vectraclip"."sipoc_sector_baselines" FOR SELECT USING (true);



ALTER TABLE "vectraclip"."sipoc_sectors" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_sectors_tenant_delete" ON "vectraclip"."sipoc_sectors" FOR DELETE USING (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_sectors_tenant_insert" ON "vectraclip"."sipoc_sectors" FOR INSERT WITH CHECK (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_sectors_tenant_select" ON "vectraclip"."sipoc_sectors" FOR SELECT USING (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_sectors_tenant_update" ON "vectraclip"."sipoc_sectors" FOR UPDATE USING (("company_id" = "vectraclip"."sipoc_company_id"())) WITH CHECK (("company_id" = "vectraclip"."sipoc_company_id"()));



ALTER TABLE "vectraclip"."tasks" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tasks_delete_own_company_admin" ON "vectraclip"."tasks" FOR DELETE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "tasks_insert_own_company_admin_op" ON "vectraclip"."tasks" FOR INSERT TO "authenticated" WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "tasks_select_own_company" ON "vectraclip"."tasks" FOR SELECT TO "authenticated" USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "tasks_update_own_company_admin_op" ON "vectraclip"."tasks" FOR UPDATE TO "authenticated" USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = ANY (ARRAY['admin'::"text", 'operator'::"text"])))) WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "tasks_write_service_role" ON "vectraclip"."tasks" TO "service_role" USING (true) WITH CHECK (true);



GRANT USAGE ON SCHEMA "vectraclip" TO "anon";
GRANT USAGE ON SCHEMA "vectraclip" TO "authenticated";
GRANT USAGE ON SCHEMA "vectraclip" TO "service_role";



REVOKE ALL ON FUNCTION "vectraclip"."increment_task_cost"("p_task_id" "uuid", "p_delta" numeric) FROM PUBLIC;
GRANT ALL ON FUNCTION "vectraclip"."increment_task_cost"("p_task_id" "uuid", "p_delta" numeric) TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."adapter_catalog" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."adapter_catalog" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."adapter_field_definitions" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."adapter_field_definitions" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."agent_adapter_configs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_adapter_configs" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."agent_execution_configs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_execution_configs" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."agent_specialties" TO "authenticated";
GRANT SELECT,INSERT,UPDATE ON TABLE "vectraclip"."agent_specialties" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agents" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."agents" TO "authenticated";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."app_users" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."app_users" TO "authenticated";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."companies" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."companies" TO "authenticated";



GRANT ALL ON TABLE "vectraclip"."goals" TO "authenticated";
GRANT ALL ON TABLE "vectraclip"."goals" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."heartbeats" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."heartbeats" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."incident_audit" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."incident_audit" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."incidents" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."incidents" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."llm_models" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."llm_models" TO "authenticated";



GRANT SELECT ON TABLE "vectraclip"."managed_agent_sessions" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."managed_agent_sessions" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."managed_agent_turn_logs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."managed_agent_turn_logs" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_companies" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_companies" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_components" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_components" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_positions" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_positions" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_processes" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_processes" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_sector_baselines" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_sector_baselines" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_sectors" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_sectors" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."tasks" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."tasks" TO "authenticated";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "vectraclip" GRANT SELECT ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "vectraclip" GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO "service_role";




