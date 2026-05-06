


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


CREATE EXTENSION IF NOT EXISTS "pg_cron" WITH SCHEMA "pg_catalog";






CREATE EXTENSION IF NOT EXISTS "pg_net" WITH SCHEMA "extensions";






COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE SCHEMA IF NOT EXISTS "vectraclip";


ALTER SCHEMA "vectraclip" OWNER TO "postgres";


CREATE EXTENSION IF NOT EXISTS "moddatetime" WITH SCHEMA "public";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE TYPE "public"."app_role" AS ENUM (
    'admin',
    'comercial',
    'operacao',
    'financeiro',
    'leitura'
);


ALTER TYPE "public"."app_role" OWNER TO "postgres";


CREATE TYPE "public"."collection_order_status" AS ENUM (
    'emitida',
    'cancelada'
);


ALTER TYPE "public"."collection_order_status" OWNER TO "postgres";


CREATE TYPE "public"."compliance_check_status" AS ENUM (
    'ok',
    'warning',
    'violation'
);


ALTER TYPE "public"."compliance_check_status" OWNER TO "postgres";


CREATE TYPE "public"."compliance_check_type" AS ENUM (
    'pre_contratacao',
    'pre_coleta',
    'pre_entrega',
    'auditoria_periodica'
);


ALTER TYPE "public"."compliance_check_type" OWNER TO "postgres";


CREATE TYPE "public"."document_type" AS ENUM (
    'nfe',
    'cte',
    'pod',
    'outros',
    'cnh',
    'crlv',
    'comp_residencia',
    'antt_motorista',
    'mdfe',
    'adiantamento',
    'analise_gr',
    'doc_rota',
    'comprovante_vpo',
    'adiantamento_carreteiro',
    'saldo_carreteiro',
    'comprovante_descarga',
    'a_vista_fat',
    'saldo_fat',
    'a_prazo_fat'
);


ALTER TYPE "public"."document_type" OWNER TO "postgres";


CREATE TYPE "public"."driver_contract_type" AS ENUM (
    'proprio',
    'agregado',
    'terceiro'
);


ALTER TYPE "public"."driver_contract_type" OWNER TO "postgres";


CREATE TYPE "public"."driver_offer_status" AS ENUM (
    'pending',
    'sent',
    'accepted',
    'declined',
    'timeout',
    'skipped'
);


ALTER TYPE "public"."driver_offer_status" OWNER TO "postgres";


CREATE TYPE "public"."driver_qualification_status" AS ENUM (
    'pendente',
    'em_analise',
    'aprovado',
    'reprovado',
    'bloqueado'
);


ALTER TYPE "public"."driver_qualification_status" OWNER TO "postgres";


CREATE TYPE "public"."financial_doc_type" AS ENUM (
    'FAT',
    'PAG'
);


ALTER TYPE "public"."financial_doc_type" OWNER TO "postgres";


CREATE TYPE "public"."financial_installment_status" AS ENUM (
    'pendente',
    'baixado'
);


ALTER TYPE "public"."financial_installment_status" OWNER TO "postgres";


CREATE TYPE "public"."financial_source_type" AS ENUM (
    'quote',
    'order'
);


ALTER TYPE "public"."financial_source_type" OWNER TO "postgres";


CREATE TYPE "public"."occurrence_severity" AS ENUM (
    'baixa',
    'media',
    'alta',
    'critica'
);


ALTER TYPE "public"."occurrence_severity" OWNER TO "postgres";


CREATE TYPE "public"."offer_sequence_status" AS ENUM (
    'ranking',
    'in_progress',
    'completed',
    'exhausted',
    'escalated',
    'cancelled'
);


ALTER TYPE "public"."offer_sequence_status" OWNER TO "postgres";


CREATE TYPE "public"."order_stage" AS ENUM (
    'ordem_criada',
    'busca_motorista',
    'documentacao',
    'coleta_realizada',
    'em_transito',
    'entregue'
);


ALTER TYPE "public"."order_stage" OWNER TO "postgres";


CREATE TYPE "public"."pedagio_charge_type" AS ENUM (
    'VALE_PEDAGIO_EMBARCADOR',
    'PEDAGIO_DEBITADO_CTE',
    'RATEIO_FRACIONADO'
);


ALTER TYPE "public"."pedagio_charge_type" OWNER TO "postgres";


CREATE TYPE "public"."pricing_rule_category" AS ENUM (
    'taxa',
    'estadia',
    'veiculo',
    'markup',
    'imposto',
    'prazo',
    'carga_descarga',
    'aluguel',
    'risco',
    'taxas_adicionais',
    'conteiner',
    'pedagio',
    'ntc'
);


ALTER TYPE "public"."pricing_rule_category" OWNER TO "postgres";


CREATE TYPE "public"."pricing_rule_value_type" AS ENUM (
    'fixed',
    'percentage',
    'per_km',
    'per_ton'
);


ALTER TYPE "public"."pricing_rule_value_type" OWNER TO "postgres";


CREATE TYPE "public"."quote_stage" AS ENUM (
    'novo_pedido',
    'qualificacao',
    'precificacao',
    'enviado',
    'negociacao',
    'ganho',
    'perdido'
);


ALTER TYPE "public"."quote_stage" OWNER TO "postgres";


CREATE TYPE "public"."risk_criticality" AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL'
);


ALTER TYPE "public"."risk_criticality" OWNER TO "postgres";


CREATE TYPE "public"."risk_evaluation_status" AS ENUM (
    'pending',
    'evaluated',
    'approved',
    'rejected',
    'expired'
);


ALTER TYPE "public"."risk_evaluation_status" OWNER TO "postgres";


CREATE TYPE "public"."rntrc_registry_type" AS ENUM (
    'TAC',
    'ETC'
);


ALTER TYPE "public"."rntrc_registry_type" OWNER TO "postgres";


CREATE TYPE "public"."route_stop_type" AS ENUM (
    'origin',
    'stop',
    'destination'
);


ALTER TYPE "public"."route_stop_type" OWNER TO "postgres";


CREATE TYPE "public"."user_profile" AS ENUM (
    'admin',
    'operacional',
    'financeiro',
    'comercial'
);


ALTER TYPE "public"."user_profile" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."audit_trigger_func"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO public.audit_logs (table_name, record_id, action, new_values, user_id)
    VALUES (TG_TABLE_NAME, NEW.id, 'INSERT', to_jsonb(NEW), auth.uid());
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO public.audit_logs (table_name, record_id, action, old_values, new_values, user_id)
    VALUES (TG_TABLE_NAME, NEW.id, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW), auth.uid());
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO public.audit_logs (table_name, record_id, action, old_values, user_id)
    VALUES (TG_TABLE_NAME, OLD.id, 'DELETE', to_jsonb(OLD), auth.uid());
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$;


ALTER FUNCTION "public"."audit_trigger_func"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."check_ai_budget"() RETURNS json
    LANGUAGE "plpgsql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
  daily_spend NUMERIC;
  monthly_spend NUMERIC;
  daily_limit NUMERIC;
  monthly_limit NUMERIC;
  alert_pct NUMERIC;
BEGIN
  daily_spend := get_ai_daily_spend();
  monthly_spend := get_ai_monthly_spend();

  SELECT value INTO daily_limit FROM ai_budget_config WHERE key = 'daily_limit_usd';
  SELECT value INTO monthly_limit FROM ai_budget_config WHERE key = 'monthly_limit_usd';
  SELECT value INTO alert_pct FROM ai_budget_config WHERE key = 'alert_threshold_pct';

  -- Defaults se não configurado
  daily_limit := COALESCE(daily_limit, 2.00);
  monthly_limit := COALESCE(monthly_limit, 30.00);
  alert_pct := COALESCE(alert_pct, 0.80);

  RETURN json_build_object(
    'allowed', (daily_spend < daily_limit AND monthly_spend < monthly_limit),
    'daily_remaining', GREATEST(daily_limit - daily_spend, 0),
    'monthly_remaining', GREATEST(monthly_limit - monthly_spend, 0),
    'daily_pct', CASE WHEN daily_limit > 0 THEN daily_spend / daily_limit ELSE 0 END,
    'monthly_pct', CASE WHEN monthly_limit > 0 THEN monthly_spend / monthly_limit ELSE 0 END,
    'alert', (daily_spend / daily_limit >= alert_pct OR monthly_spend / monthly_limit >= alert_pct)
  );
END;
$$;


ALTER FUNCTION "public"."check_ai_budget"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."copy_quote_adiantamento_to_fat"("p_quote_id" "uuid", "p_fat_id" "uuid") RETURNS "void"
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  insert into public.documents (
    file_name,
    file_url,
    file_size,
    type,
    uploaded_by,
    quote_id,
    fat_id,
    nfe_key,
    validation_status
  )
  select
    d.file_name,
    d.file_url,
    d.file_size,
    d.type,
    d.uploaded_by,
    d.quote_id,
    p_fat_id,
    d.nfe_key,
    d.validation_status
  from public.documents d
  where d.quote_id = p_quote_id
    and d.type = 'adiantamento'::public.document_type;
$$;


ALTER FUNCTION "public"."copy_quote_adiantamento_to_fat"("p_quote_id" "uuid", "p_fat_id" "uuid") OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."trips" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "trip_number" "text" NOT NULL,
    "vehicle_plate" "text",
    "driver_id" "uuid",
    "vehicle_type_id" "uuid",
    "departure_at" timestamp with time zone,
    "status_operational" "text" DEFAULT 'aberta'::"text" NOT NULL,
    "financial_status" "text" DEFAULT 'open'::"text" NOT NULL,
    "notes" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "closed_at" timestamp with time zone,
    "closed_by" "uuid",
    CONSTRAINT "trips_financial_status_check" CHECK (("financial_status" = ANY (ARRAY['open'::"text", 'closing'::"text", 'closed'::"text"]))),
    CONSTRAINT "trips_status_operational_check" CHECK (("status_operational" = ANY (ARRAY['aberta'::"text", 'em_transito'::"text", 'finalizada'::"text", 'cancelada'::"text"])))
);


ALTER TABLE "public"."trips" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."create_trip"("p_vehicle_plate" "text", "p_driver_id" "uuid", "p_vehicle_type_id" "uuid" DEFAULT NULL::"uuid", "p_departure_at" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_notes" "text" DEFAULT NULL::"text", "p_trip_number" "text" DEFAULT NULL::"text") RETURNS "public"."trips"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  r public.trips%ROWTYPE;
  v_plate text;
  v_num text;
BEGIN
  v_plate := trim(coalesce(p_vehicle_plate, ''));
  IF v_plate = '' THEN
    RAISE EXCEPTION 'vehicle_plate_required';
  END IF;
  IF p_driver_id IS NULL THEN
    RAISE EXCEPTION 'driver_id_required';
  END IF;

  IF p_trip_number IS NOT NULL AND btrim(p_trip_number) <> '' THEN
    v_num := btrim(p_trip_number);
  ELSE
    v_num := generate_trip_number();
  END IF;

  INSERT INTO public.trips (
    trip_number,
    vehicle_plate,
    driver_id,
    vehicle_type_id,
    departure_at,
    notes,
    status_operational,
    financial_status
  )
  VALUES (
    v_num,
    v_plate,
    p_driver_id,
    p_vehicle_type_id,
    p_departure_at,
    p_notes,
    'aberta',
    'open'
  )
  RETURNING * INTO r;

  RETURN r;
END;
$$;


ALTER FUNCTION "public"."create_trip"("p_vehicle_plate" "text", "p_driver_id" "uuid", "p_vehicle_type_id" "uuid", "p_departure_at" timestamp with time zone, "p_notes" "text", "p_trip_number" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."create_trip_from_composition"("p_composition_id" "uuid", "p_user_id" "uuid", "p_total_value_fat" numeric, "p_total_cost_pag" numeric, "p_notes" "text" DEFAULT NULL::"text") RETURNS "uuid"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
declare
  v_trip_id uuid;
  v_trip_number text;
  v_suggestion record;
  v_quote_id uuid;
  v_client_id uuid;
  v_fat_id uuid;
  v_pag_id uuid;
  v_payment_term_id uuid;
  v_order_id uuid;
begin
  -- 1. Fetch composition details
  select * into v_suggestion
  from load_composition_suggestions
  where id = p_composition_id;

  if v_suggestion.id is null then
    raise exception 'Composição não encontrada: %', p_composition_id;
  end if;

  -- 2. Generate Trip Number
  v_trip_number := generate_trip_number();

  -- 3. Create Trip
  insert into trips (
    trip_number,
    status_operational,
    financial_status,
    notes,
    created_by
  ) values (
    v_trip_number,
    'aberta',
    'open',
    p_notes,
    p_user_id
  ) returning id into v_trip_id;

  -- 4. Process each quote in the composition
  foreach v_quote_id in array v_suggestion.quote_ids loop
    -- Update quote status
    update quotes 
    set stage = 'ganho', 
        updated_at = now() 
    where id = v_quote_id;

    -- Ensure Order exists
    select id into v_order_id from orders where quote_id = v_quote_id;
    
    if v_order_id is null then
      insert into orders (
        os_number, quote_id, client_id, client_name, origin, destination, value, 
        created_by, shipper_id, shipper_name, cargo_type, weight, volume,
        origin_cep, destination_cep, freight_type, pricing_breakdown
      )
      select 
        generate_os_number(), id, client_id, client_name, origin, destination, value, 
        p_user_id, shipper_id, shipper_name, cargo_type, weight, volume,
        origin_cep, destination_cep, freight_type, pricing_breakdown
      from quotes
      where id = v_quote_id
      returning id into v_order_id;
    end if;

    -- Link to trip_orders
    insert into trip_orders (trip_id, order_id, apportion_key, apportion_factor)
    values (v_trip_id, v_order_id, 'revenue', 0)
    on conflict (trip_id, order_id) do nothing;
    
    -- Update order with trip_id
    update orders set trip_id = v_trip_id where id = v_order_id;
  end loop;

  -- 5. Financial Orchestration (T8)
  
  -- 5a. Create FAT (Faturamento Cliente)
  -- Associate with the primary order of the trip
  select client_id, payment_term_id into v_client_id, v_payment_term_id
  from quotes
  where id = v_suggestion.quote_ids[1];

  insert into financial_documents (
    owner_id,
    type,
    status,
    source_type,
    source_id,
    total_amount,
    notes
  ) values (
    v_client_id,
    'FAT',
    'INCLUIR',
    'order',
    (select id from orders where quote_id = v_suggestion.quote_ids[1] limit 1),
    p_total_value_fat,
    'Faturamento consolidado da Trip ' || v_trip_number
  ) returning id into v_fat_id;

  -- 5b. Create PAG (Pagamento Carreteiro)
  insert into financial_documents (
    type,
    status,
    source_type,
    source_id,
    total_amount,
    notes
  ) values (
    'PAG',
    'INCLUIR',
    'order',
    (select id from orders where quote_id = v_suggestion.quote_ids[1] limit 1),
    p_total_cost_pag,
    'Pagamento consolidado da Trip ' || v_trip_number
  ) returning id into v_pag_id;

  -- 6. Update suggestion status
  update load_composition_suggestions
  set status = 'executed',
      approved_by = p_user_id,
      approved_at = now()
  where id = p_composition_id;

  -- 7. Sync costs from breakdown
  perform sync_cost_items_from_breakdown(v_trip_id);

  return v_trip_id;
end;
$$;


ALTER FUNCTION "public"."create_trip_from_composition"("p_composition_id" "uuid", "p_user_id" "uuid", "p_total_value_fat" numeric, "p_total_cost_pag" numeric, "p_notes" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."current_user_profile"() RETURNS "public"."user_profile"
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT p.perfil
  FROM public.profiles p
  WHERE p.id = auth.uid() OR p.user_id = auth.uid()
  LIMIT 1;
$$;


ALTER FUNCTION "public"."current_user_profile"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."emit_approval_decided_event"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF OLD.status = 'pending' AND NEW.status IN ('approved', 'rejected') THEN
    INSERT INTO public.workflow_events (event_type, entity_type, entity_id, payload, created_by)
    VALUES (
      'approval.decided',
      NEW.entity_type,
      NEW.entity_id,
      jsonb_build_object(
        'approval_id', NEW.id,
        'approval_type', NEW.approval_type,
        'decision', NEW.status,
        'decision_notes', NEW.decision_notes,
        'decided_by', NEW.decided_by,
        'entity_type', NEW.entity_type,
        'entity_id', NEW.entity_id
      ),
      NEW.decided_by
    );
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."emit_approval_decided_event"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."emit_document_uploaded_event"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
begin
  if coalesce(NEW.source, 'upload') = 'inherited' then
    return NEW;
  end if;

  insert into public.workflow_events (event_type, entity_type, entity_id, payload, created_by)
  values (
    'document.uploaded',
    'document',
    NEW.id,
    jsonb_build_object(
      'type', NEW.type::text,
      'order_id', NEW.order_id,
      'quote_id', NEW.quote_id,
      'file_name', NEW.file_name
    ),
    NEW.uploaded_by
  );
  return NEW;
end;
$$;


ALTER FUNCTION "public"."emit_document_uploaded_event"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."emit_financial_status_event"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF OLD.status IS DISTINCT FROM NEW.status THEN
    INSERT INTO public.workflow_events (event_type, entity_type, entity_id, payload)
    VALUES (
      'financial.status_changed',
      'financial_document',
      NEW.id,
      jsonb_build_object(
        'old_status', OLD.status,
        'new_status', NEW.status,
        'type', NEW.type::TEXT,
        'code', NEW.code,
        'total_amount', NEW.total_amount,
        'source_type', NEW.source_type::TEXT,
        'source_id', NEW.source_id,
        'owner_id', NEW.owner_id
      )
    );
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."emit_financial_status_event"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."emit_order_created_event"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  INSERT INTO public.workflow_events (event_type, entity_type, entity_id, payload, created_by)
  VALUES (
    'order.created',
    'order',
    NEW.id,
    jsonb_build_object(
      'os_number', NEW.os_number,
      'quote_id', NEW.quote_id,
      'client_name', NEW.client_name,
      'client_id', NEW.client_id,
      'value', NEW.value,
      'origin', NEW.origin,
      'destination', NEW.destination,
      'carreteiro_antt', NEW.carreteiro_antt
    ),
    COALESCE(auth.uid(), NEW.created_by)
  );
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."emit_order_created_event"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."emit_order_stage_event"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF OLD.stage IS DISTINCT FROM NEW.stage THEN
    INSERT INTO public.workflow_events (event_type, entity_type, entity_id, payload, created_by)
    VALUES (
      'order.stage_changed',
      'order',
      NEW.id,
      jsonb_build_object(
        'old_stage', OLD.stage::TEXT,
        'new_stage', NEW.stage::TEXT,
        'os_number', NEW.os_number,
        'value', NEW.value,
        'client_name', NEW.client_name,
        'client_id', NEW.client_id,
        'driver_name', NEW.driver_name,
        'driver_phone', NEW.driver_phone,
        'origin', NEW.origin,
        'destination', NEW.destination,
        'quote_id', NEW.quote_id,
        'carreteiro_antt', NEW.carreteiro_antt,
        'carreteiro_real', NEW.carreteiro_real
      ),
      COALESCE(auth.uid(), NEW.created_by)
    );
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."emit_order_stage_event"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."emit_quote_stage_event"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF OLD.stage IS DISTINCT FROM NEW.stage THEN
    -- Standard stage changed event (always emitted)
    INSERT INTO public.workflow_events (event_type, entity_type, entity_id, payload, created_by)
    VALUES (
      'quote.stage_changed',
      'quote',
      NEW.id,
      jsonb_build_object(
        'old_stage', OLD.stage::TEXT,
        'new_stage', NEW.stage::TEXT,
        'quote_code', NEW.quote_code,
        'value', NEW.value,
        'client_name', NEW.client_name,
        'client_email', NEW.client_email,
        'client_id', NEW.client_id,
        'shipper_name', NEW.shipper_name,
        'shipper_email', NEW.shipper_email,
        'origin', NEW.origin,
        'destination', NEW.destination,
        'assigned_to', NEW.assigned_to
      ),
      COALESCE(auth.uid(), NEW.assigned_to)
    );

    -- Entering 'ganho': schedule deferred OS creation (24h grace period)
    IF NEW.stage = 'ganho' THEN
      -- Cancel any previous deferred events for this quote (handles ganho→X→ganho reset)
      UPDATE public.workflow_events
        SET status = 'cancelled', processed_at = now()
        WHERE entity_type = 'quote'
          AND entity_id = NEW.id
          AND event_type = 'quote.ganho_deferred'
          AND status = 'pending';

      -- Create new deferred event with 24h grace period
      INSERT INTO public.workflow_events
        (event_type, entity_type, entity_id, payload, created_by, execute_after)
      VALUES (
        'quote.ganho_deferred',
        'quote',
        NEW.id,
        jsonb_build_object(
          'quote_code', NEW.quote_code,
          'value', NEW.value,
          'client_name', NEW.client_name,
          'client_email', NEW.client_email,
          'client_id', NEW.client_id
        ),
        COALESCE(auth.uid(), NEW.assigned_to),
        now() + interval '24 hours'
      );
    END IF;

    -- Leaving 'ganho': cancel pending deferred event
    IF OLD.stage = 'ganho' AND NEW.stage != 'ganho' THEN
      UPDATE public.workflow_events
        SET status = 'cancelled', processed_at = now()
        WHERE entity_type = 'quote'
          AND entity_id = NEW.id
          AND event_type = 'quote.ganho_deferred'
          AND status = 'pending';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."emit_quote_stage_event"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enforce_company_domain"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
begin
  if new.email is null or lower(split_part(new.email,'@',2)) <> 'vectracargo.com.br' then
    update auth.users set banned_until = 'infinity' where id = new.id;
  end if;
  return new;
end;
$$;


ALTER FUNCTION "public"."enforce_company_domain"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enforce_pod_before_entregue"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  -- Only enforce when the resulting stage is 'entregue'
  IF NEW.stage = 'entregue' AND COALESCE(NEW.has_pod, false) = false THEN
    RAISE EXCEPTION 'POD obrigatório para finalizar (stage=entregue)';
  END IF;

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."enforce_pod_before_entregue"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enforce_uppercase_clients"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
begin
  NEW.name        := case when NEW.name        is null then null else upper(NEW.name) end;
  NEW.email       := case when NEW.email       is null then null else upper(NEW.email) end;
  NEW.phone       := case when NEW.phone       is null then null else upper(NEW.phone) end;
  NEW.cnpj        := case when NEW.cnpj        is null then null else upper(NEW.cnpj) end;
  NEW.address     := case when NEW.address     is null then null else upper(NEW.address) end;
  NEW.city        := case when NEW.city        is null then null else upper(NEW.city) end;
  NEW.state       := case when NEW.state       is null then null else upper(NEW.state) end;
  NEW.notes       := case when NEW.notes       is null then null else upper(NEW.notes) end;
  NEW.zip_code    := case when NEW.zip_code    is null then null else upper(NEW.zip_code) end;
  return NEW;
end;
$$;


ALTER FUNCTION "public"."enforce_uppercase_clients"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enforce_uppercase_drivers"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
begin
  NEW.name        := case when NEW.name        is null then null else upper(NEW.name) end;
  NEW.phone       := case when NEW.phone       is null then null else upper(NEW.phone) end;
  NEW.cnh         := case when NEW.cnh         is null then null else upper(NEW.cnh) end;
  NEW.cnh_category:= case when NEW.cnh_category is null then null else upper(NEW.cnh_category) end;
  return NEW;
end;
$$;


ALTER FUNCTION "public"."enforce_uppercase_drivers"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enforce_uppercase_owners"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
begin
  NEW.name        := case when NEW.name        is null then null else upper(NEW.name) end;
  NEW.cpf_cnpj    := case when NEW.cpf_cnpj    is null then null else upper(NEW.cpf_cnpj) end;
  NEW.rg          := case when NEW.rg          is null then null else upper(NEW.rg) end;
  NEW.rg_emitter  := case when NEW.rg_emitter  is null then null else upper(NEW.rg_emitter) end;
  NEW.phone       := case when NEW.phone       is null then null else upper(NEW.phone) end;
  NEW.email       := case when NEW.email       is null then null else upper(NEW.email) end;
  NEW.address     := case when NEW.address     is null then null else upper(NEW.address) end;
  NEW.city        := case when NEW.city        is null then null else upper(NEW.city) end;
  NEW.state       := case when NEW.state       is null then null else upper(NEW.state) end;
  NEW.zip_code    := case when NEW.zip_code    is null then null else upper(NEW.zip_code) end;
  NEW.notes       := case when NEW.notes       is null then null else upper(NEW.notes) end;
  return NEW;
end;
$$;


ALTER FUNCTION "public"."enforce_uppercase_owners"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enqueue_agent_job"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
  INSERT INTO agent_jobs (collected_data_id) VALUES (NEW.id);
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."enqueue_agent_job"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."ensure_financial_document"("doc_type" "public"."financial_doc_type", "source_id_in" "uuid", "total_amount_in" numeric DEFAULT NULL::numeric) RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
declare
  v_id uuid;
  v_code text;
  v_amount numeric;
  v_source_type public.financial_source_type;
begin
  if doc_type = 'FAT' then
    v_source_type := 'quote'::public.financial_source_type;
    if not exists (select 1 from public.quotes where id = source_id_in) then
      raise exception 'Quote not found: %', source_id_in;
    end if;
    select value, coalesce(quote_code, 'FAT-' || left(source_id_in::text, 8)) into v_amount, v_code
    from public.quotes where id = source_id_in;
  elsif doc_type = 'PAG' then
    v_source_type := 'order'::public.financial_source_type;
    if not exists (select 1 from public.orders where id = source_id_in) then
      raise exception 'Order not found: %', source_id_in;
    end if;
    select coalesce(carreteiro_real, value), coalesce(os_number, 'PAG-' || left(source_id_in::text, 8)) into v_amount, v_code
    from public.orders where id = source_id_in;
  else
    raise exception 'Invalid doc_type: %', doc_type;
  end if;

  v_amount := coalesce(total_amount_in, v_amount);

  select fd.id into v_id
  from public.financial_documents fd
  where fd.source_type = v_source_type and fd.source_id = source_id_in
  limit 1;

  if v_id is not null then
    update public.financial_documents
    set total_amount = v_amount
    where id = v_id;
    return jsonb_build_object('id', v_id, 'created', false);
  end if;

  insert into public.financial_documents (type, code, status, source_type, source_id, total_amount)
  values (doc_type, v_code, 'INCLUIR', v_source_type, source_id_in, v_amount)
  returning id into v_id;

  return jsonb_build_object('id', v_id, 'created', true);
end;
$$;


ALTER FUNCTION "public"."ensure_financial_document"("doc_type" "public"."financial_doc_type", "source_id_in" "uuid", "total_amount_in" numeric) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."find_price_row_by_km"("p_price_table_id" "uuid", "p_km_numeric" numeric, "p_rounding" "text" DEFAULT 'ceil'::"text") RETURNS TABLE("id" "uuid", "km_from" integer, "km_to" integer, "cost_per_ton" numeric, "matched_km" integer)
    LANGUAGE "plpgsql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
  v_km integer;
BEGIN
  IF p_rounding = 'floor' THEN
    v_km := FLOOR(p_km_numeric)::int;
  ELSIF p_rounding = 'round' THEN
    v_km := ROUND(p_km_numeric)::int;
  ELSE
    v_km := CEILING(p_km_numeric)::int;
  END IF;

  RETURN QUERY
  SELECT r.id, r.km_from, r.km_to, r.cost_per_ton, v_km AS matched_km
  FROM public.price_table_rows r
  WHERE r.price_table_id = p_price_table_id
    AND r.km_from <= v_km
    AND r.km_to >= v_km
  ORDER BY r.km_from DESC
  LIMIT 1;
END;
$$;


ALTER FUNCTION "public"."find_price_row_by_km"("p_price_table_id" "uuid", "p_km_numeric" numeric, "p_rounding" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_risk_evaluation_approved"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
  IF NEW.status = 'approved' AND OLD.status != 'approved' THEN
    INSERT INTO workflow_events (event_type, entity_type, entity_id, payload, status, retry_count, max_retries)
    VALUES (
      'risk.evaluation_approved',
      NEW.entity_type,
      NEW.entity_id,
      jsonb_build_object('criticality', NEW.criticality, 'policy_id', NEW.policy_id, 'evaluation_id', NEW.id),
      'pending', 0, 3
    );
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."fn_risk_evaluation_approved"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."generate_os_number"() RETURNS "text"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public'
    AS $$
DECLARE
  year_part TEXT;
  month_part TEXT;
  next_seq INTEGER;
BEGIN
  year_part := TO_CHAR(NOW(), 'YYYY');
  month_part := TO_CHAR(NOW(), 'MM');

  SELECT COALESCE(
    MAX(CAST(SPLIT_PART(os_number, '-', 4) AS INTEGER)),
    0
  ) + 1
  INTO next_seq
  FROM public.orders
  WHERE SPLIT_PART(os_number, '-', 1) = 'OS'
    AND SPLIT_PART(os_number, '-', 2) = year_part
    AND SPLIT_PART(os_number, '-', 3) = month_part;

  RETURN 'OS-' || year_part || '-' || month_part || '-' || LPAD(next_seq::TEXT, 4, '0');
END;
$$;


ALTER FUNCTION "public"."generate_os_number"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."generate_quote_code"() RETURNS "text"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public'
    AS $$
DECLARE
  year_part TEXT;
  month_part TEXT;
  next_seq INTEGER;
BEGIN
  year_part := TO_CHAR(NOW(), 'YYYY');
  month_part := TO_CHAR(NOW(), 'MM');

  SELECT COALESCE(
    MAX(CAST(SPLIT_PART(quote_code, '-', 4) AS INTEGER)),
    0
  ) + 1
  INTO next_seq
  FROM public.quotes
  WHERE SPLIT_PART(quote_code, '-', 1) = 'COT'
    AND SPLIT_PART(quote_code, '-', 2) = year_part
    AND SPLIT_PART(quote_code, '-', 3) = month_part;

  RETURN 'COT-' || year_part || '-' || month_part || '-' || LPAD(next_seq::TEXT, 4, '0');
END;
$$;


ALTER FUNCTION "public"."generate_quote_code"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."generate_trip_number"() RETURNS "text"
    LANGUAGE "sql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  select 'VG-' || to_char(now(), 'YYYY-MM-') ||
    lpad((coalesce(max(substring(trip_number from 'VG-\d{4}-\d{2}-(\d+)')::int), 0) + 1)::text, 4, '0')
  from public.trips
  where trip_number like 'VG-' || to_char(now(), 'YYYY-MM-') || '%';
$$;


ALTER FUNCTION "public"."generate_trip_number"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_ai_daily_spend"() RETURNS numeric
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  SELECT COALESCE(SUM(estimated_cost_usd), 0)
  FROM ai_usage_tracking
  WHERE created_at >= date_trunc('day', now())
    AND status IN ('success', 'cached');
$$;


ALTER FUNCTION "public"."get_ai_daily_spend"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_ai_monthly_spend"() RETURNS numeric
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  SELECT COALESCE(SUM(estimated_cost_usd), 0)
  FROM ai_usage_tracking
  WHERE created_at >= date_trunc('month', now())
    AND status IN ('success', 'cached');
$$;


ALTER FUNCTION "public"."get_ai_monthly_spend"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_ai_usage_stats"() RETURNS json
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  SELECT json_build_object(
    'daily_spend', (
      SELECT COALESCE(SUM(estimated_cost_usd), 0)
      FROM ai_usage_tracking
      WHERE created_at >= date_trunc('day', now())
    ),
    'monthly_spend', (
      SELECT COALESCE(SUM(estimated_cost_usd), 0)
      FROM ai_usage_tracking
      WHERE created_at >= date_trunc('month', now())
    ),
    'daily_limit', 2,
    'monthly_limit', 30,
    'alert_threshold', 0.8,
    'today_calls', (
      SELECT COUNT(*)
      FROM ai_usage_tracking
      WHERE created_at >= date_trunc('day', now())
    ),
    'month_calls', (
      SELECT COUNT(*)
      FROM ai_usage_tracking
      WHERE created_at >= date_trunc('month', now())
    ),
    'today_by_model', (
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT model_used, COUNT(*) as calls,
               SUM(input_tokens) as total_input_tokens,
               SUM(output_tokens) as total_output_tokens,
               SUM(cache_read_tokens) as total_cache_read_tokens,
               SUM(estimated_cost_usd) as total_cost
        FROM ai_usage_tracking
        WHERE created_at >= date_trunc('day', now())
        GROUP BY model_used
      ) t
    ),
    'month_by_type', (
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT analysis_type, COUNT(*) as calls,
               SUM(estimated_cost_usd) as total_cost
        FROM ai_usage_tracking
        WHERE created_at >= date_trunc('month', now())
        GROUP BY analysis_type
      ) t
    ),
    'recent_errors', (
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT analysis_type, status, error_message, created_at
        FROM ai_usage_tracking
        WHERE status IN ('rate_limited', 'budget_exceeded', 'error')
          AND created_at >= now() - interval '24 hours'
        ORDER BY created_at DESC
        LIMIT 10
      ) t
    )
  );
$$;


ALTER FUNCTION "public"."get_ai_usage_stats"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_card_full_data"("p_quote_id" "uuid" DEFAULT NULL::"uuid", "p_order_id" "uuid" DEFAULT NULL::"uuid") RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_quote_id uuid;
  v_order_id uuid;
  v_quote public.quotes%rowtype;
  v_order public.orders%rowtype;
  v_fat public.financial_documents%rowtype;
  v_pag public.financial_documents%rowtype;
  out_quote jsonb;
  out_order jsonb;
  out_fat jsonb;
  out_pag jsonb;
BEGIN
  IF p_quote_id IS NULL AND p_order_id IS NULL THEN
    RETURN jsonb_build_object('quote', null, 'order', null, 'fat', null, 'pag', null);
  END IF;

  -- Resolve quote_id and order_id and load quote/order rows
  IF p_quote_id IS NOT NULL THEN
    v_quote_id := p_quote_id;
    SELECT q.* INTO v_quote FROM public.quotes q WHERE q.id = p_quote_id;
    SELECT o.* INTO v_order FROM public.orders o WHERE o.quote_id = p_quote_id LIMIT 1;
    v_order_id := v_order.id;
  ELSE
    SELECT o.* INTO v_order FROM public.orders o WHERE o.id = p_order_id;
    IF NOT FOUND THEN
      RETURN jsonb_build_object('quote', null, 'order', null, 'fat', null, 'pag', null);
    END IF;
    v_order_id := p_order_id;
    v_quote_id := v_order.quote_id;
    IF v_quote_id IS NOT NULL THEN
      SELECT q.* INTO v_quote FROM public.quotes q WHERE q.id = v_quote_id;
    END IF;
  END IF;

  -- Load quote if we have quote_id and not yet loaded
  IF v_quote_id IS NOT NULL AND v_quote.id IS NULL THEN
    SELECT q.* INTO v_quote FROM public.quotes q WHERE q.id = v_quote_id;
  END IF;

  -- FAT: by quote
  IF v_quote_id IS NOT NULL THEN
    SELECT fd.* INTO v_fat
    FROM public.financial_documents fd
    WHERE fd.source_type = 'quote' AND fd.source_id = v_quote_id AND fd.type = 'FAT'
    LIMIT 1;
  END IF;

  -- PAG: by order
  IF v_order_id IS NOT NULL THEN
    SELECT fd.* INTO v_pag
    FROM public.financial_documents fd
    WHERE fd.source_type = 'order' AND fd.source_id = v_order_id AND fd.type = 'PAG'
    LIMIT 1;
  END IF;

  out_quote := CASE WHEN v_quote.id IS NOT NULL THEN to_jsonb(v_quote) ELSE null END;
  out_order := CASE WHEN v_order.id IS NOT NULL THEN to_jsonb(v_order) ELSE null END;
  out_fat   := CASE WHEN v_fat.id IS NOT NULL THEN to_jsonb(v_fat) ELSE null END;
  out_pag   := CASE WHEN v_pag.id IS NOT NULL THEN to_jsonb(v_pag) ELSE null END;

  RETURN jsonb_build_object(
    'quote', out_quote,
    'order', out_order,
    'fat', out_fat,
    'pag', out_pag
  );
END;
$$;


ALTER FUNCTION "public"."get_card_full_data"("p_quote_id" "uuid", "p_order_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_diesel_cost_by_route"("p_from" "date" DEFAULT '2025-01-01'::"date", "p_to" "date" DEFAULT NULL::"date") RETURNS TABLE("rota" "text", "origin_uf" "text", "dest_uf" "text", "ctes" bigint, "km_medio" numeric, "diesel_orig" numeric, "diesel_dest" numeric, "media_rota" numeric, "custo_por_km" numeric, "diesel_total_medio" numeric, "diesel_total_soma" numeric, "receita_media" numeric, "pct_ticket" numeric)
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  WITH cte_with_diesel AS (
    SELECT
      (regexp_match(o.origin,      '-\s+([A-Z]{2})[,\s]'))[1]      AS o_uf,
      (regexp_match(o.destination, '-\s+([A-Z]{2})[,\s]'))[1]      AS d_uf,
      o.km_distance,
      o.value,
      o.created_at::date                                            AS cte_date,
      orig_p.preco_medio                                            AS diesel_orig,
      dest_p.preco_medio                                            AS diesel_dest,
      (orig_p.preco_medio + dest_p.preco_medio) / 2                AS media_rota,
      o.km_distance * ((orig_p.preco_medio + dest_p.preco_medio) / 2 * 0.3) AS diesel_total
    FROM orders o
    -- ANP price for origin UF on/before CT-e date (source='anp' only)
    LEFT JOIN LATERAL (
      SELECT pdp.preco_medio
      FROM petrobras_diesel_prices pdp
      WHERE pdp.uf      = (regexp_match(o.origin, '-\s+([A-Z]{2})[,\s]'))[1]
        AND pdp.source  = 'anp'
        AND pdp.periodo_coleta::date <= o.created_at::date
      ORDER BY pdp.periodo_coleta::date DESC
      LIMIT 1
    ) orig_p ON true
    -- ANP price for destination UF on/before CT-e date (source='anp' only)
    LEFT JOIN LATERAL (
      SELECT pdp.preco_medio
      FROM petrobras_diesel_prices pdp
      WHERE pdp.uf      = (regexp_match(o.destination, '-\s+([A-Z]{2})[,\s]'))[1]
        AND pdp.source  = 'anp'
        AND pdp.periodo_coleta::date <= o.created_at::date
      ORDER BY pdp.periodo_coleta::date DESC
      LIMIT 1
    ) dest_p ON true
    WHERE o.has_cte = true
      AND o.km_distance > 0
      AND o.value > 0
      AND orig_p.preco_medio IS NOT NULL
      AND dest_p.preco_medio IS NOT NULL
      AND o.created_at::date >= p_from
      AND (p_to IS NULL OR o.created_at::date <= p_to)
  )
  SELECT
    cd.o_uf || ' → ' || cd.d_uf                    AS rota,
    cd.o_uf                                         AS origin_uf,
    cd.d_uf                                         AS dest_uf,
    COUNT(*)                                        AS ctes,
    ROUND(AVG(cd.km_distance)::numeric, 0)          AS km_medio,
    ROUND(AVG(cd.diesel_orig)::numeric, 3)          AS diesel_orig,
    ROUND(AVG(cd.diesel_dest)::numeric, 3)          AS diesel_dest,
    ROUND(AVG(cd.media_rota)::numeric, 3)           AS media_rota,
    ROUND((AVG(cd.media_rota) * 0.3)::numeric, 4)  AS custo_por_km,
    ROUND(AVG(cd.diesel_total)::numeric, 2)         AS diesel_total_medio,
    ROUND(SUM(cd.diesel_total)::numeric, 2)         AS diesel_total_soma,
    ROUND(AVG(cd.value)::numeric, 2)                AS receita_media,
    ROUND((AVG(cd.diesel_total) / NULLIF(AVG(cd.value), 0) * 100)::numeric, 1) AS pct_ticket
  FROM cte_with_diesel cd
  GROUP BY cd.o_uf, cd.d_uf
  ORDER BY diesel_total_soma DESC;
$$;


ALTER FUNCTION "public"."get_diesel_cost_by_route"("p_from" "date", "p_to" "date") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_route_metrics"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_vehicle_type_id" "uuid" DEFAULT NULL::"uuid") RETURNS TABLE("route_key" "text", "origin_uf" "text", "destination_uf" "text", "vehicle_type_id" "uuid", "vehicle_type_name" "text", "orders_count" integer, "avg_rs_per_km" numeric, "p50_rs_per_km" numeric, "p90_rs_per_km" numeric, "avg_km" numeric, "avg_paid" numeric)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  with base as (
    select
      -- extração de UF robusta (ex.: "... - SC, 88371-880")
      (regexp_match(o.origin, '-\\s*([A-Z]{2})'))[1] as origin_uf,
      (regexp_match(o.destination, '-\\s*([A-Z]{2})'))[1] as destination_uf,
      o.vehicle_type_id,
      o.vehicle_type_name,
      o.km_distance,
      o.carreteiro_real,
      o.rs_per_km,
      o.order_date
    from public.orders_rs_per_km o
    where o.order_date >= p_from
      and o.order_date <= p_to
      and (p_vehicle_type_id is null or o.vehicle_type_id = p_vehicle_type_id)
  )
  select
    (b.origin_uf || '->' || b.destination_uf) as route_key,
    b.origin_uf,
    b.destination_uf,
    b.vehicle_type_id,
    max(b.vehicle_type_name) as vehicle_type_name,
    count(*)::int as orders_count,
    avg(b.rs_per_km)::numeric as avg_rs_per_km,
    percentile_cont(0.5) within group (order by b.rs_per_km) as p50_rs_per_km,
    percentile_cont(0.9) within group (order by b.rs_per_km) as p90_rs_per_km,
    avg(b.km_distance)::numeric as avg_km,
    avg(b.carreteiro_real)::numeric as avg_paid
  from base b
  where b.origin_uf is not null and b.destination_uf is not null
  group by b.origin_uf, b.destination_uf, b.vehicle_type_id
  order by avg_rs_per_km desc nulls last;
$$;


ALTER FUNCTION "public"."get_route_metrics"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_vehicle_type_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_user_role"("_user_id" "uuid") RETURNS "public"."app_role"
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT role
  FROM public.user_roles
  WHERE user_id = _user_id
  ORDER BY 
    CASE role
      WHEN 'admin' THEN 1
      WHEN 'operacao' THEN 2
      WHEN 'comercial' THEN 3
      WHEN 'fiscal' THEN 4
      WHEN 'leitura' THEN 5
    END
  LIMIT 1
$$;


ALTER FUNCTION "public"."get_user_role"("_user_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_valid_transitions"("p_entity_type" "text", "p_from_stage" "text") RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  RETURN COALESCE(
    (SELECT jsonb_agg(jsonb_build_object(
      'to_stage', wt.to_stage,
      'description', wt.description,
      'requires_approval', wt.requires_approval,
      'required_documents', wt.required_documents
    ) ORDER BY wt.to_stage)
    FROM workflow_transitions wt
    JOIN workflow_definitions wd ON wd.id = wt.workflow_id
    WHERE wd.entity_type = p_entity_type
      AND wd.active = true
      AND wt.from_stage = p_from_stage),
    '[]'::JSONB
  );
END;
$$;


ALTER FUNCTION "public"."get_valid_transitions"("p_entity_type" "text", "p_from_stage" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_valid_transitions"("p_entity_type" "text", "p_from_stage" "text") IS 'Returns all valid target stages from a given stage';



CREATE OR REPLACE FUNCTION "public"."get_vault_secret"("p_name" "text") RETURNS "text"
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT decrypted_secret
  FROM vault.decrypted_secrets
  WHERE name = p_name
  LIMIT 1;
$$;


ALTER FUNCTION "public"."get_vault_secret"("p_name" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_new_user"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  INSERT INTO public.profiles (user_id, full_name, email)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data ->> 'full_name', NEW.email),
    NEW.email
  );
  
  INSERT INTO public.user_roles (user_id, role)
  VALUES (NEW.id, 'leitura');
  
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_new_user"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_new_user_profile"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  INSERT INTO public.profiles (id, user_id, full_name, email, perfil)
  VALUES (
    NEW.id,
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', ''),
    NEW.email,
    'operacional'
  )
  ON CONFLICT (id) DO UPDATE SET
    user_id = COALESCE(profiles.user_id, NEW.id),
    email   = COALESCE(profiles.email, NEW.email);

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_new_user_profile"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."has_any_role"("_user_id" "uuid", "_roles" "public"."app_role"[]) RETURNS boolean
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_roles
    WHERE user_id = _user_id
      AND role = ANY(_roles)
  )
$$;


ALTER FUNCTION "public"."has_any_role"("_user_id" "uuid", "_roles" "public"."app_role"[]) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."has_profile"("allowed" "public"."user_profile"[]) RETURNS boolean
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT public.current_user_profile() = ANY(allowed);
$$;


ALTER FUNCTION "public"."has_profile"("allowed" "public"."user_profile"[]) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") RETURNS boolean
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_roles
    WHERE user_id = _user_id
      AND role = _role
  )
$$;


ALTER FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_admin"() RETURNS boolean
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.profiles p
    WHERE (p.id = auth.uid() OR p.user_id = auth.uid())
      AND p.perfil = 'admin'
  );
$$;


ALTER FUNCTION "public"."is_admin"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."link_order_to_target_trip"("p_order_id" "uuid", "p_trip_id" "uuid") RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
declare
  v_order record;
  v_old_trip_id uuid;
  v_total_value numeric;
  v_factor numeric;
  r record;
begin
  select id, trip_id into v_order
  from public.orders
  where id = p_order_id;

  if v_order.id is null then
    raise exception 'Ordem não encontrada: %', p_order_id;
  end if;

  if not exists (select 1 from public.trips where id = p_trip_id) then
    raise exception 'Trip não encontrada: %', p_trip_id;
  end if;

  -- Já vinculada à trip alvo
  if v_order.trip_id = p_trip_id then
    return p_trip_id;
  end if;

  v_old_trip_id := v_order.trip_id;

  -- Remover da trip atual (se houver)
  if v_old_trip_id is not null then
    delete from public.trip_orders
    where trip_id = v_old_trip_id
      and order_id = p_order_id;

    -- Recalcular apportion na trip de origem
    select coalesce(sum(o.value), 0) into v_total_value
    from public.trip_orders to2
    join public.orders o on o.id = to2.order_id
    where to2.trip_id = v_old_trip_id;

    if v_total_value > 0 then
      for r in
        select to2.id, o.value
        from public.trip_orders to2
        join public.orders o on o.id = to2.order_id
        where to2.trip_id = v_old_trip_id
      loop
        v_factor := coalesce(r.value, 0) / v_total_value;
        update public.trip_orders set apportion_factor = v_factor where id = r.id;
      end loop;
    end if;

    perform public.sync_cost_items_from_breakdown(v_old_trip_id);
  end if;

  -- Vincular à trip alvo
  insert into public.trip_orders (trip_id, order_id, apportion_key, apportion_factor)
  values (p_trip_id, p_order_id, 'revenue', 0)
  on conflict (trip_id, order_id) do update set apportion_factor = excluded.apportion_factor;

  update public.orders set trip_id = p_trip_id, updated_at = now() where id = p_order_id;

  -- Recalcular apportion na trip destino
  select coalesce(sum(o.value), 0) into v_total_value
  from public.trip_orders to2
  join public.orders o on o.id = to2.order_id
  where to2.trip_id = p_trip_id;

  if v_total_value > 0 then
    for r in
      select to2.id, o.value
      from public.trip_orders to2
      join public.orders o on o.id = to2.order_id
      where to2.trip_id = p_trip_id
    loop
      v_factor := coalesce(r.value, 0) / v_total_value;
      update public.trip_orders set apportion_factor = v_factor where id = r.id;
    end loop;
  end if;

  perform public.sync_cost_items_from_breakdown(p_trip_id);

  return p_trip_id;
end;
$$;


ALTER FUNCTION "public"."link_order_to_target_trip"("p_order_id" "uuid", "p_trip_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."link_order_to_trip"("p_order_id" "uuid") RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
declare
  v_order record;
  v_trip_id uuid;
  v_trip_number text;
  v_total_value numeric;
  v_factor numeric;
  v_sibling_id uuid;
  v_src_order_id uuid;
  v_src_has_cnh boolean;
  v_src_has_crlv boolean;
  v_src_has_comp_residencia boolean;
  v_src_has_antt_motorista boolean;
  v_dest_has_all boolean;
  r record;
begin
  select id, vehicle_plate, driver_id, value, trip_id into v_order
  from public.orders
  where id = p_order_id;

  if v_order.id is null then
    raise exception 'Ordem não encontrada: %', p_order_id;
  end if;

  if v_order.trip_id is not null then
    return v_order.trip_id;
  end if;

  if trim(coalesce(v_order.vehicle_plate, '')) = '' or v_order.driver_id is null then
    raise exception 'Informe placa e motorista na OS antes de vincular à viagem';
  end if;

  -- 1) Buscar trip existente
  select t.id into v_trip_id
  from public.trips t
  where t.vehicle_plate = trim(v_order.vehicle_plate)
    and t.driver_id = v_order.driver_id
    and t.status_operational in ('aberta', 'em_transito')
    and (t.departure_at::date = current_date
         or (t.departure_at is null and t.created_at::date = current_date))
  order by t.created_at desc
  limit 1;

  if v_trip_id is not null then
    -- Trip existe → vincular (2a+ OS)
    insert into public.trip_orders (trip_id, order_id, apportion_key, apportion_factor)
    values (v_trip_id, p_order_id, 'revenue', 0)
    on conflict (trip_id, order_id) do nothing;

    update public.orders set trip_id = v_trip_id, updated_at = now() where id = p_order_id;
  else
    -- 2) Verificar se existe OUTRA OS elegível
    select o.id into v_sibling_id
    from public.orders o
    where o.vehicle_plate = trim(v_order.vehicle_plate)
      and o.driver_id = v_order.driver_id
      and o.id != p_order_id
      and o.stage in ('documentacao', 'coleta_realizada', 'em_transito')
      and o.trip_id is null
    limit 1;

    if v_sibling_id is null then
      raise exception 'Viagem requer pelo menos 2 OS com mesmo motorista e placa. Nenhuma outra OS elegível encontrada.';
    end if;

    -- Criar trip e vincular ambas
    select public.generate_trip_number() into v_trip_number;
    insert into public.trips (trip_number, vehicle_plate, driver_id, departure_at, status_operational)
    values (v_trip_number, trim(v_order.vehicle_plate), v_order.driver_id, now(), 'aberta')
    returning id into v_trip_id;

    -- Vincular OS irmã
    insert into public.trip_orders (trip_id, order_id, apportion_key, apportion_factor)
    values (v_trip_id, v_sibling_id, 'revenue', 0)
    on conflict (trip_id, order_id) do nothing;
    update public.orders set trip_id = v_trip_id, updated_at = now() where id = v_sibling_id;

    -- Vincular OS atual
    insert into public.trip_orders (trip_id, order_id, apportion_key, apportion_factor)
    values (v_trip_id, p_order_id, 'revenue', 0)
    on conflict (trip_id, order_id) do nothing;
    update public.orders set trip_id = v_trip_id, updated_at = now() where id = p_order_id;
  end if;

  -- Herdar docs do motorista (se destino não tem todos)
  select coalesce(o.has_cnh, false) and coalesce(o.has_crlv, false)
     and coalesce(o.has_comp_residencia, false) and coalesce(o.has_antt_motorista, false)
  into v_dest_has_all
  from public.orders o where o.id = p_order_id;

  if not coalesce(v_dest_has_all, false) then
    select o2.id, o2.has_cnh, o2.has_crlv, o2.has_comp_residencia, o2.has_antt_motorista
      into v_src_order_id, v_src_has_cnh, v_src_has_crlv, v_src_has_comp_residencia, v_src_has_antt_motorista
    from public.trip_orders tro
    join public.orders o2 on o2.id = tro.order_id
    where tro.trip_id = v_trip_id
      and o2.id != p_order_id
      and o2.driver_id = v_order.driver_id
      and coalesce(o2.has_cnh, false)
      and coalesce(o2.has_crlv, false)
      and coalesce(o2.has_comp_residencia, false)
      and coalesce(o2.has_antt_motorista, false)
    limit 1;

    if v_src_order_id is not null then
      update public.orders set
        has_cnh = v_src_has_cnh,
        has_crlv = v_src_has_crlv,
        has_comp_residencia = v_src_has_comp_residencia,
        has_antt_motorista = v_src_has_antt_motorista,
        updated_at = now()
      where id = p_order_id;

      insert into public.documents (order_id, type, file_name, file_url, file_size, uploaded_by, source)
      select p_order_id, d.type, d.file_name, d.file_url, d.file_size, d.uploaded_by, 'inherited'
      from public.documents d
      where d.order_id = v_src_order_id
        and d.type in ('cnh', 'crlv', 'comp_residencia', 'antt_motorista');
    end if;
  end if;

  -- Recalcular apportion_factor
  select coalesce(sum(o.value), 0) into v_total_value
  from public.trip_orders to2
  join public.orders o on o.id = to2.order_id
  where to2.trip_id = v_trip_id;

  if v_total_value > 0 then
    for r in
      select to2.id, o.value
      from public.trip_orders to2
      join public.orders o on o.id = to2.order_id
      where to2.trip_id = v_trip_id
    loop
      v_factor := coalesce(r.value, 0) / v_total_value;
      update public.trip_orders set apportion_factor = v_factor where id = r.id;
    end loop;
  end if;

  perform public.sync_cost_items_from_breakdown(v_trip_id);

  return v_trip_id;
end;
$$;


ALTER FUNCTION "public"."link_order_to_trip"("p_order_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."mask_cep"("input" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  with d as (
    select lpad(only_digits(input), 8, '0') as v
  )
  select case when length(only_digits(input)) = 8
    then substr(d.v,1,5)||'-'||substr(d.v,6,3)
    else null end
  from d;
$$;


ALTER FUNCTION "public"."mask_cep"("input" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."mask_cnpj"("input" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  with d as (
    select lpad(only_digits(input), 14, '0') as v
  )
  select case when length(only_digits(input)) = 14
    then substr(d.v,1,2)||'.'||substr(d.v,3,3)||'.'||substr(d.v,6,3)||'/'||substr(d.v,9,4)||'-'||substr(d.v,13,2)
    else null end
  from d;
$$;


ALTER FUNCTION "public"."mask_cnpj"("input" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."mask_cpf"("input" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  with d as (
    select lpad(only_digits(input), 11, '0') as v
  )
  select case when length(only_digits(input)) = 11
    then substr(d.v,1,3)||'.'||substr(d.v,4,3)||'.'||substr(d.v,7,3)||'-'||substr(d.v,10,2)
    else null end
  from d;
$$;


ALTER FUNCTION "public"."mask_cpf"("input" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."mask_plate"("input" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $_$
  select case
    when input is null then null
    when length(input) = 7 and input ~ '^[A-Z]{3}[0-9]{4}$' then substr(input,1,3)||'-'||substr(input,4)
    else input
  end;
$_$;


ALTER FUNCTION "public"."mask_plate"("input" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."next_collection_order_seq"("p_year" integer, "p_month" integer) RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_lock_key bigint;
  v_next     int;
BEGIN
  IF p_month < 1 OR p_month > 12 THEN
    RAISE EXCEPTION 'invalid month: %', p_month;
  END IF;
  IF p_year  < 2026 OR p_year  > 2100 THEN
    RAISE EXCEPTION 'invalid year: %', p_year;
  END IF;

  v_lock_key := (p_year::bigint * 100) + p_month::bigint;
  PERFORM pg_advisory_xact_lock(v_lock_key);

  SELECT COALESCE(MAX(oc_seq), 0) + 1
    INTO v_next
    FROM public.collection_orders
   WHERE oc_year = p_year AND oc_month = p_month;

  RETURN v_next;
END;
$$;


ALTER FUNCTION "public"."next_collection_order_seq"("p_year" integer, "p_month" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."next_collection_order_seq"("p_year" integer, "p_month" integer) IS 'Retorna proximo seq mensal de OC. Gap permanente: cancelamentos consomem numero.';



CREATE OR REPLACE FUNCTION "public"."norm_plate"("input" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  select case when input is null then null else upper(regexp_replace(input, '[^A-Za-z0-9]', '', 'g')) end;
$$;


ALTER FUNCTION "public"."norm_plate"("input" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."normalize_clients"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
begin
  NEW.cnpj      := case when NEW.cnpj    is null then null else only_digits(NEW.cnpj) end;
  NEW.zip_code  := case when NEW.zip_code is null then null else only_digits(NEW.zip_code) end;

  NEW.cnpj_mask     := mask_cnpj(NEW.cnpj);
  NEW.zip_code_mask := mask_cep(NEW.zip_code);
  return NEW;
end;
$$;


ALTER FUNCTION "public"."normalize_clients"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."normalize_owners"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
begin
  -- normalize values (store raw normalized values)
  NEW.cpf_cnpj := case when NEW.cpf_cnpj is null then null else only_digits(NEW.cpf_cnpj) end;
  NEW.zip_code := case when NEW.zip_code is null then null else only_digits(NEW.zip_code) end;

  -- set masks
  NEW.cpf_cnpj_mask := coalesce(mask_cnpj(NEW.cpf_cnpj), mask_cpf(NEW.cpf_cnpj));
  NEW.zip_code_mask := mask_cep(NEW.zip_code);
  return NEW;
end;
$$;


ALTER FUNCTION "public"."normalize_owners"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."normalize_vehicles"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
begin
  NEW.plate   := case when NEW.plate   is null then null else norm_plate(NEW.plate) end;
  NEW.plate_2 := case when NEW.plate_2 is null then null else norm_plate(NEW.plate_2) end;

  NEW.plate_mask   := mask_plate(NEW.plate);
  NEW.plate_2_mask := mask_plate(NEW.plate_2);
  return NEW;
end;
$$;


ALTER FUNCTION "public"."normalize_vehicles"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."only_digits"("input" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  select regexp_replace(coalesce(input, ''), '[^0-9]', '', 'g');
$$;


ALTER FUNCTION "public"."only_digits"("input" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."price_table_rows_no_overlap"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM public.price_table_rows r
    WHERE r.price_table_id = NEW.price_table_id
      AND r.id IS DISTINCT FROM NEW.id
      AND r.km_from <= NEW.km_to
      AND r.km_to >= NEW.km_from
  ) THEN
    RAISE EXCEPTION 'Faixa sobreposta para esta tabela (%)', NEW.price_table_id;
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."price_table_rows_no_overlap"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rank_drivers_for_quote"("p_vehicle_type_id" "uuid", "p_origin_city" "text" DEFAULT NULL::"text", "p_origin_state" character varying DEFAULT NULL::character varying, "p_dest_city" "text" DEFAULT NULL::"text", "p_dest_state" character varying DEFAULT NULL::character varying, "p_min_quality_score" integer DEFAULT 50, "p_w_proximity" integer DEFAULT 35, "p_w_history" integer DEFAULT 25, "p_w_quality" integer DEFAULT 30, "p_w_price" integer DEFAULT 10, "p_max_results" integer DEFAULT 20, "p_exclude_driver_ids" "uuid"[] DEFAULT '{}'::"uuid"[]) RETURNS TABLE("driver_id" "uuid", "driver_name" "text", "driver_phone" "text", "driver_cpf" "text", "vehicle_id" "uuid", "vehicle_plate" "text", "vehicle_type_id" "uuid", "owner_id" "uuid", "owner_city" "text", "owner_state" character varying, "quality_score" integer, "route_count" bigint, "proximity_pts" numeric, "history_pts" numeric, "quality_pts" numeric, "total_score" numeric, "score_details" "jsonb")
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
  WITH eligible_drivers AS (
    SELECT
      d.id            AS driver_id,
      d.name          AS driver_name,
      d.phone         AS driver_phone,
      d.cpf           AS driver_cpf,
      v.id            AS vehicle_id,
      v.plate         AS vehicle_plate,
      v.vehicle_type_id,
      o.id            AS owner_id,
      o.city          AS owner_city,
      o.state         AS owner_state
    FROM drivers d
    JOIN vehicles v ON v.driver_id = d.id AND v.active = true
    JOIN owners o   ON o.id = v.owner_id
    WHERE d.active = true
      AND v.vehicle_type_id = p_vehicle_type_id
      AND (d.cnh_expiry IS NULL  OR d.cnh_expiry  > CURRENT_DATE)
      AND (d.antt_expiry IS NULL OR d.antt_expiry > CURRENT_DATE)
      AND d.id != ALL(p_exclude_driver_ids)
      AND NOT EXISTS (
        SELECT 1 FROM driver_offers dof
        JOIN driver_offer_sequences dos ON dos.id = dof.sequence_id
        WHERE dof.driver_id = d.id
          AND dof.status = 'sent'
          AND dos.status = 'in_progress'
      )
  ),
  with_quality AS (
    SELECT
      ed.*,
      COALESCE(
        (SELECT dq.risk_score
         FROM driver_qualifications dq
         WHERE dq.driver_cpf = ed.driver_cpf
           AND dq.status = 'aprovado'
         ORDER BY dq.created_at DESC
         LIMIT 1),
        70
      ) AS quality_score
    FROM eligible_drivers ed
  ),
  with_history AS (
    SELECT
      wq.*,
      (SELECT COUNT(*)
       FROM trips t
       JOIN trip_orders tord ON tord.trip_id = t.id
       JOIN orders ord ON ord.id = tord.order_id
       WHERE t.driver_id = wq.driver_id
         AND t.status_operational IN ('finalizada', 'em_transito')
         AND LOWER(COALESCE(ord.origin, '')) = LOWER(COALESCE(p_origin_city, ''))
         AND LOWER(COALESCE(ord.destination, '')) = LOWER(COALESCE(p_dest_city, ''))
      ) AS route_count
    FROM with_quality wq
  ),
  scored AS (
    SELECT
      wh.*,
      CASE
        WHEN p_origin_city IS NOT NULL AND LOWER(wh.owner_city) = LOWER(p_origin_city) THEN 100
        WHEN p_origin_state IS NOT NULL AND UPPER(wh.owner_state) = UPPER(p_origin_state) THEN 60
        ELSE 0
      END AS proximity_pts,
      LEAST(wh.route_count * 20, 100)::numeric AS history_pts,
      wh.quality_score::numeric AS quality_pts
    FROM with_history wh
    WHERE wh.quality_score >= p_min_quality_score
  )
  SELECT
    s.driver_id,
    s.driver_name,
    s.driver_phone,
    s.driver_cpf,
    s.vehicle_id,
    s.vehicle_plate,
    s.vehicle_type_id,
    s.owner_id,
    s.owner_city,
    s.owner_state,
    s.quality_score::integer,
    s.route_count,
    s.proximity_pts,
    s.history_pts,
    s.quality_pts,
    ROUND(
      (s.proximity_pts * p_w_proximity +
       s.history_pts  * p_w_history +
       s.quality_pts  * p_w_quality
      ) / NULLIF(p_w_proximity + p_w_history + p_w_quality, 0)
    , 2) AS total_score,
    jsonb_build_object(
      'proximity', s.proximity_pts,
      'route_history', s.history_pts,
      'quality', s.quality_pts,
      'route_count', s.route_count,
      'owner_city', s.owner_city,
      'owner_state', s.owner_state
    ) AS score_details
  FROM scored s
  ORDER BY
    (s.proximity_pts * p_w_proximity +
     s.history_pts  * p_w_history +
     s.quality_pts  * p_w_quality
    ) DESC
  LIMIT p_max_results;
$$;


ALTER FUNCTION "public"."rank_drivers_for_quote"("p_vehicle_type_id" "uuid", "p_origin_city" "text", "p_origin_state" character varying, "p_dest_city" "text", "p_dest_state" character varying, "p_min_quality_score" integer, "p_w_proximity" integer, "p_w_history" integer, "p_w_quality" integer, "p_w_price" integer, "p_max_results" integer, "p_exclude_driver_ids" "uuid"[]) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rls_auto_enable"() RETURNS "event_trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'pg_catalog'
    AS $$
DECLARE
  cmd record;
BEGIN
  FOR cmd IN
    SELECT *
    FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table','partitioned table')
  LOOP
     IF cmd.schema_name IS NOT NULL AND cmd.schema_name IN ('public') AND cmd.schema_name NOT IN ('pg_catalog','information_schema') AND cmd.schema_name NOT LIKE 'pg_toast%' AND cmd.schema_name NOT LIKE 'pg_temp%' THEN
      BEGIN
        EXECUTE format('alter table if exists %s enable row level security', cmd.object_identity);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION
        WHEN OTHERS THEN
          RAISE LOG 'rls_auto_enable: failed to enable RLS on %', cmd.object_identity;
      END;
     ELSE
        RAISE LOG 'rls_auto_enable: skip % (either system schema or not in enforced list: %.)', cmd.object_identity, cmd.schema_name;
     END IF;
  END LOOP;
END;
$$;


ALTER FUNCTION "public"."rls_auto_enable"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."send_queue_reject_blocked_contact"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF NEW.status = 'pending'::public.queue_status
     AND NEW.contact_id IS NOT NULL
     AND EXISTS (
       SELECT 1
       FROM public.contacts c
       WHERE c.id = NEW.contact_id
         AND c.is_blocked IS TRUE
     )
  THEN
    NEW.status := 'failed'::public.queue_status;
    NEW.error_message := 'blocked_contact';
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."send_queue_reject_blocked_contact"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."send_queue_reject_blocked_contact"() IS 'Falha na fila (failed + blocked_contact) se pending apontar para contacts.is_blocked.';



CREATE OR REPLACE FUNCTION "public"."set_os_number"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF NEW.os_number IS NULL OR NEW.os_number = '' THEN
    NEW.os_number := public.generate_os_number();
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."set_os_number"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_quote_code"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF NEW.quote_code IS NULL OR NEW.quote_code = '' THEN
    NEW.quote_code := public.generate_quote_code();
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."set_quote_code"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_user_profile"("target_user_id" "uuid", "new_profile" "public"."user_profile") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'not_allowed';
  END IF;

  UPDATE public.profiles
  SET perfil = new_profile, updated_at = now()
  WHERE id = target_user_id OR user_id = target_user_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'user_not_found';
  END IF;
END;
$$;


ALTER FUNCTION "public"."set_user_profile"("target_user_id" "uuid", "new_profile" "public"."user_profile") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."sync_cost_items_from_breakdown"("p_trip_id" "uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
declare
  r record;
  v_toll_total numeric := 0;
  v_carreteiro_total numeric := 0;
  v_idempotency text;
  v_descarga numeric;
  v_das numeric;
  v_gris numeric;
  v_tso numeric;
begin
  delete from public.trip_cost_items
  where trip_id = p_trip_id
    and source = 'breakdown';

  for r in
    select
      o.id as order_id,
      o.pricing_breakdown as pb,
      coalesce(q.pricing_breakdown, o.pricing_breakdown) as effective_pb
    from public.trip_orders to2
    join public.orders o on o.id = to2.order_id
    left join public.quotes q on q.id = o.quote_id
    where to2.trip_id = p_trip_id
  loop
    if r.effective_pb is not null then
      v_toll_total := v_toll_total + coalesce(
        (r.effective_pb->'components'->>'toll')::numeric, 0);
      v_carreteiro_total := v_carreteiro_total + coalesce(
        (r.effective_pb->'profitability'->>'custosCarreteiro')::numeric, 0);

      -- Descarga: inserir sempre (amount=0 quando não informada) para auditoria
      v_descarga := coalesce((r.effective_pb->'profitability'->>'custosDescarga')::numeric, 0);
      v_idempotency := p_trip_id::text || '_' || r.order_id::text || '_descarga_breakdown';
      insert into public.trip_cost_items (
        trip_id, order_id, scope, category, amount, source, idempotency_key
      ) values (
        p_trip_id, r.order_id, 'OS', 'descarga', v_descarga, 'breakdown', v_idempotency
      ) on conflict (idempotency_key) do update set amount = excluded.amount, updated_at = now();

      -- DAS
      v_das := coalesce((r.effective_pb->'totals'->>'das')::numeric, 0);
      if v_das > 0 then
        v_idempotency := p_trip_id::text || '_' || r.order_id::text || '_das_breakdown';
        insert into public.trip_cost_items (
          trip_id, order_id, scope, category, amount, source, idempotency_key
        ) values (
          p_trip_id, r.order_id, 'OS', 'das', v_das, 'breakdown', v_idempotency
        ) on conflict (idempotency_key) do update set amount = excluded.amount, updated_at = now();
      end if;

      -- GRIS
      v_gris := coalesce((r.effective_pb->'components'->>'gris')::numeric, 0);
      if v_gris > 0 then
        v_idempotency := p_trip_id::text || '_' || r.order_id::text || '_gris_breakdown';
        insert into public.trip_cost_items (
          trip_id, order_id, scope, category, amount, source, idempotency_key
        ) values (
          p_trip_id, r.order_id, 'OS', 'gris', v_gris, 'breakdown', v_idempotency
        ) on conflict (idempotency_key) do update set amount = excluded.amount, updated_at = now();
      end if;

      -- TSO
      v_tso := coalesce((r.effective_pb->'components'->>'tso')::numeric, 0);
      if v_tso > 0 then
        v_idempotency := p_trip_id::text || '_' || r.order_id::text || '_tso_breakdown';
        insert into public.trip_cost_items (
          trip_id, order_id, scope, category, amount, source, idempotency_key
        ) values (
          p_trip_id, r.order_id, 'OS', 'tso', v_tso, 'breakdown', v_idempotency
        ) on conflict (idempotency_key) do update set amount = excluded.amount, updated_at = now();
      end if;
    end if;
  end loop;

  if v_toll_total > 0 then
    v_idempotency := p_trip_id::text || '_pedagio_breakdown';
    insert into public.trip_cost_items (
      trip_id, order_id, scope, category, amount, source, idempotency_key
    ) values (
      p_trip_id, null, 'TRIP', 'pedagio', v_toll_total, 'breakdown', v_idempotency
    ) on conflict (idempotency_key) do update set amount = excluded.amount, updated_at = now();
  end if;

  if v_carreteiro_total > 0 then
    v_idempotency := p_trip_id::text || '_carreteiro_breakdown';
    insert into public.trip_cost_items (
      trip_id, order_id, scope, category, amount, source, idempotency_key
    ) values (
      p_trip_id, null, 'TRIP', 'carreteiro', v_carreteiro_total, 'breakdown', v_idempotency
    ) on conflict (idempotency_key) do update set amount = excluded.amount, updated_at = now();
  end if;
end;
$$;


ALTER FUNCTION "public"."sync_cost_items_from_breakdown"("p_trip_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."sync_financial_doc_amount_on_carreteiro_change"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
begin
  if new.carreteiro_real is distinct from old.carreteiro_real then
    update public.financial_documents
    set total_amount = new.carreteiro_real
    where source_type = 'order'
      and source_id = new.id
      and type = 'PAG';
  end if;
  return new;
end;
$$;


ALTER FUNCTION "public"."sync_financial_doc_amount_on_carreteiro_change"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tr_identify_consolidation_on_quote_insert"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
  v_url TEXT;
  v_key TEXT;
BEGIN
  SELECT value INTO v_url FROM public.settings WHERE key = 'supabase_url';
  SELECT value INTO v_key FROM public.settings WHERE key = 'supabase_service_role_key';

  IF v_url IS NULL OR v_key IS NULL THEN RETURN NEW; END IF;

  PERFORM net.http_post(
    url := v_url || '/functions/v1/matchmaker-proactive-v6-cfn',
    headers := jsonb_build_object('Content-Type', 'application/json', 'Authorization', 'Bearer ' || v_key),
    body := jsonb_build_object('type', 'INSERT', 'table', 'quotes', 'record', row_to_json(NEW))
  );

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tr_identify_consolidation_on_quote_insert"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tr_identify_consolidation_v7"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
  v_url TEXT;
  v_key TEXT;
  v_body JSONB;
  v_headers JSONB;
BEGIN
  -- Regra: Apenas quando entra no estágio de 'qualificacao'
  IF (TG_OP = 'INSERT' AND NEW.stage = 'qualificacao') OR 
     (TG_OP = 'UPDATE' AND NEW.stage = 'qualificacao' AND (OLD.stage IS NULL OR OLD.stage != 'qualificacao')) THEN
     
    SELECT value INTO v_url FROM public.settings WHERE key = 'supabase_url';
    SELECT value INTO v_key FROM public.settings WHERE key = 'supabase_service_role_key';

    IF v_url IS NULL OR v_key IS NULL THEN RETURN NEW; END IF;

    v_body := jsonb_build_object(
      'type', TG_OP,
      'table', TG_TABLE_NAME,
      'record', row_to_json(NEW)
    );

    v_headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer ' || v_key
    );

    -- Ajuste para a assinatura correta do pg_net 0.7+
    -- net.http_post(url, body, params, headers, timeout_ms)
    PERFORM net.http_post(
      v_url || '/functions/v1/matchmaker-proactive-v6-cfn',
      v_body,
      '{}'::jsonb,
      v_headers,
      5000
    );
  END IF;

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tr_identify_consolidation_v7"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."try_auto_group_order_to_trip"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
declare
  v_order_id uuid;
  v_vehicle_plate text;
  v_driver_id uuid;
  v_order_value numeric;
  v_trip_id uuid;
  v_trip_number text;
  v_total_value numeric;
  v_factor numeric;
  v_sibling_id uuid;
  r record;
begin
  -- Só executa quando stage muda para 'documentacao'
  if new.stage <> 'documentacao' or (old.stage = new.stage and tg_op = 'UPDATE') then
    return new;
  end if;

  v_order_id := new.id;
  v_vehicle_plate := trim(new.vehicle_plate);
  v_driver_id := new.driver_id;
  v_order_value := coalesce(new.value, 0);

  -- Exige vehicle_plate e driver_id
  if v_vehicle_plate is null or v_vehicle_plate = '' or v_driver_id is null then
    return new;
  end if;

  -- 1) Buscar trip existente: mesma placa, mesmo motorista, aberta, hoje
  select t.id into v_trip_id
  from public.trips t
  where t.vehicle_plate = v_vehicle_plate
    and t.driver_id = v_driver_id
    and t.status_operational in ('aberta', 'em_transito')
    and (t.departure_at::date = current_date
         or (t.departure_at is null and t.created_at::date = current_date))
  order by t.created_at desc
  limit 1;

  -- 2) Se já existe trip → vincular esta OS a ela (é a 2a+ OS)
  if v_trip_id is not null then
    -- Vincular
    insert into public.trip_orders (trip_id, order_id, apportion_key, apportion_factor)
    values (v_trip_id, v_order_id, 'revenue', 0)
    on conflict (trip_id, order_id) do nothing;

    update public.orders set trip_id = v_trip_id, updated_at = now() where id = v_order_id;

  else
    -- 3) Não existe trip → verificar se há OUTRA OS elegível (mesmo motorista+placa)
    select o.id into v_sibling_id
    from public.orders o
    where o.vehicle_plate = v_vehicle_plate
      and o.driver_id = v_driver_id
      and o.id != v_order_id
      and o.stage in ('documentacao', 'coleta_realizada', 'em_transito')
      and o.trip_id is null
    limit 1;

    -- Se não há outra OS → NÃO criar VG. OS segue avulsa.
    if v_sibling_id is null then
      return new;
    end if;

    -- Há outra OS → criar VG e vincular AMBAS
    select public.generate_trip_number() into v_trip_number;
    insert into public.trips (
      trip_number, vehicle_plate, driver_id, departure_at, status_operational
    ) values (
      v_trip_number, v_vehicle_plate, v_driver_id, now(), 'aberta'
    )
    returning id into v_trip_id;

    -- Vincular OS irmã
    insert into public.trip_orders (trip_id, order_id, apportion_key, apportion_factor)
    values (v_trip_id, v_sibling_id, 'revenue', 0)
    on conflict (trip_id, order_id) do nothing;

    update public.orders set trip_id = v_trip_id, updated_at = now() where id = v_sibling_id;

    -- Vincular OS atual
    insert into public.trip_orders (trip_id, order_id, apportion_key, apportion_factor)
    values (v_trip_id, v_order_id, 'revenue', 0)
    on conflict (trip_id, order_id) do nothing;

    update public.orders set trip_id = v_trip_id, updated_at = now() where id = v_order_id;
  end if;

  -- Recalcular apportion_factor (por receita)
  select coalesce(sum(o.value), 0) into v_total_value
  from public.trip_orders to2
  join public.orders o on o.id = to2.order_id
  where to2.trip_id = v_trip_id;

  if v_total_value > 0 then
    for r in
      select to2.id, o.value
      from public.trip_orders to2
      join public.orders o on o.id = to2.order_id
      where to2.trip_id = v_trip_id
    loop
      v_factor := coalesce(r.value, 0) / v_total_value;
      update public.trip_orders set apportion_factor = v_factor where id = r.id;
    end loop;
  end if;

  -- Sincronizar custos do breakdown
  perform public.sync_cost_items_from_breakdown(v_trip_id);

  return new;
end;
$$;


ALTER FUNCTION "public"."try_auto_group_order_to_trip"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_company_settings_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_company_settings_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_delivery_assessments_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;


ALTER FUNCTION "public"."update_delivery_assessments_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_driver_qualification_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_driver_qualification_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_load_composition_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_load_composition_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_pricing_route_overrides_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_pricing_route_overrides_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_quote_contracts_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_quote_contracts_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
    -- Try to update updated_at if it exists
    IF TG_TABLE_NAME = 'quotes' OR TG_TABLE_NAME = 'trips' OR TG_TABLE_NAME = 'orders' THEN
        NEW.updated_at = NOW();
    ELSE
        -- Fallback for tables that might use atualizado_em
        BEGIN
            NEW.atualizado_em = NOW();
        EXCEPTION WHEN others THEN
            -- If neither exists, just return
            NULL;
        END;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_updated_at_column"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validate_api_key"("p_key" "text", "p_scope" "text") RETURNS boolean
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.edge_function_api_keys
    WHERE key_hash = encode(sha256(p_key::bytea), 'hex')
      AND is_active = true
      AND (expires_at IS NULL OR expires_at > now())
      AND (
        p_scope = ANY(scopes)
        OR EXISTS (
          SELECT 1 FROM unnest(scopes) s
          WHERE p_scope LIKE replace(s, '*', '%')
        )
      )
  );
$$;


ALTER FUNCTION "public"."validate_api_key"("p_key" "text", "p_scope" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validate_quote_antt_floor"("p_quote_id" "uuid") RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_value             numeric;
  v_km_distance       numeric;
  v_modality          text;
  v_axes_count        integer;
  v_antt_rate_id      uuid;
  v_ccd               numeric;
  v_cc                numeric;
  v_valid_from        timestamptz;
  v_piso              numeric := 0;
  v_breakdown_ts      text;
  v_is_stale          boolean := false;
  v_km_band           integer;
BEGIN
  -- Resolve cotação + modalidade + eixos
  SELECT
    q.value,
    q.km_distance,
    COALESCE(
      pt.modality,
      CASE WHEN q.pricing_breakdown->>'version' IS NOT NULL THEN
        CASE WHEN (q.pricing_breakdown->'profitability'->>'custoMotoristaAntt')::numeric > 0 THEN 'lotacao' ELSE 'fracionado' END
      END,
      'fracionado'
    ),
    vt.axes_count,
    (q.pricing_breakdown->'meta'->>'anttCalculatedAt')
  INTO v_value, v_km_distance, v_modality, v_axes_count, v_breakdown_ts
  FROM quotes q
  LEFT JOIN price_tables pt ON pt.id = q.price_table_id
  LEFT JOIN vehicle_types vt ON vt.id = q.vehicle_type_id
  WHERE q.id = p_quote_id;

  IF NOT FOUND THEN
    RETURN jsonb_build_object(
      'is_below_antt_floor', false,
      'piso', 0,
      'current_value', 0,
      'modality', null,
      'gap', 0,
      'rate_id', null,
      'evaluated_at', now(),
      'is_stale', false,
      'error', 'quote_not_found'
    );
  END IF;

  -- Piso só se aplica à lotação com eixos e km definidos
  IF v_modality = 'lotacao' AND v_axes_count IS NOT NULL AND v_axes_count > 0
     AND v_km_distance IS NOT NULL AND v_km_distance > 0 THEN

    v_km_band := CEIL(v_km_distance);

    SELECT id, ccd, cc, valid_from
    INTO v_antt_rate_id, v_ccd, v_cc, v_valid_from
    FROM antt_floor_rates
    WHERE operation_table = 'A'
      AND cargo_type = 'carga_geral'
      AND axes_count = v_axes_count
    ORDER BY valid_from DESC NULLS LAST
    LIMIT 1;

    IF v_ccd IS NOT NULL AND v_cc IS NOT NULL THEN
      v_piso := ROUND((v_km_band * v_ccd + v_cc)::numeric, 2);
    END IF;

    -- Staleness: breakdown calculado antes da vigência da taxa atual
    IF v_breakdown_ts IS NOT NULL AND v_valid_from IS NOT NULL THEN
      v_is_stale := (v_breakdown_ts::timestamptz < v_valid_from);
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'is_below_antt_floor', (v_modality = 'lotacao' AND v_piso > 0 AND v_value < v_piso),
    'piso', v_piso,
    'current_value', v_value,
    'modality', v_modality,
    'gap', GREATEST(v_piso - COALESCE(v_value, 0), 0),
    'rate_id', v_antt_rate_id,
    'evaluated_at', now(),
    'is_stale', v_is_stale
  );
END;
$$;


ALTER FUNCTION "public"."validate_quote_antt_floor"("p_quote_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validate_transition"("p_entity_type" "text", "p_entity_id" "uuid", "p_from_stage" "text", "p_to_stage" "text") RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_transition RECORD;
  v_errors JSONB := '[]'::JSONB;
  v_risk_status TEXT;
  v_trip_id UUID;
  v_trip_risk_status TEXT;
BEGIN
  -- Find matching transition rule
  SELECT wt.*
  INTO v_transition
  FROM workflow_transitions wt
  JOIN workflow_definitions wd ON wd.id = wt.workflow_id
  WHERE wd.entity_type = p_entity_type
    AND wd.active = true
    AND wt.from_stage = p_from_stage
    AND wt.to_stage = p_to_stage;

  IF NOT FOUND THEN
    RETURN jsonb_build_object(
      'valid', false,
      'errors', jsonb_build_array(
        format('Transição não permitida: %s → %s para %s', p_from_stage, p_to_stage, p_entity_type)
      ),
      'requires_approval', false,
      'approval_type', NULL,
      'post_actions', '[]'::JSONB,
      'required_fields', '[]'::JSONB,
      'required_documents', '[]'::JSONB
    );
  END IF;

  -- Check required documents for orders
  IF p_entity_type = 'order' AND jsonb_array_length(v_transition.required_documents) > 0 THEN
    DECLARE
      v_doc TEXT;
      v_order RECORD;
    BEGIN
      SELECT has_nfe, has_cte, has_pod, has_cnh, has_crlv, has_antt
      INTO v_order
      FROM orders WHERE id = p_entity_id;

      IF FOUND THEN
        FOR v_doc IN SELECT jsonb_array_elements_text(v_transition.required_documents)
        LOOP
          CASE v_doc
            WHEN 'nfe' THEN
              IF NOT COALESCE(v_order.has_nfe, false) THEN
                v_errors := v_errors || to_jsonb(format('Documento obrigatório ausente: NF-e'));
              END IF;
            WHEN 'cte' THEN
              IF NOT COALESCE(v_order.has_cte, false) THEN
                v_errors := v_errors || to_jsonb(format('Documento obrigatório ausente: CT-e'));
              END IF;
            WHEN 'pod' THEN
              IF NOT COALESCE(v_order.has_pod, false) THEN
                v_errors := v_errors || to_jsonb(format('Documento obrigatório ausente: POD (Comprovante de entrega)'));
              END IF;
            ELSE
              NULL;
          END CASE;
        END LOOP;
      END IF;
    END;
  END IF;

  -- ═══════════════════════════════════════════
  -- RISK GATE: documentacao -> coleta_realizada
  -- ═══════════════════════════════════════════
  IF p_entity_type = 'order' AND p_to_stage = 'coleta_realizada' THEN

    -- 1. Check if risk evaluation exists and is approved
    SELECT status INTO v_risk_status
    FROM risk_evaluations
    WHERE entity_type = 'order'
      AND entity_id = p_entity_id
      AND status NOT IN ('expired', 'rejected')
    ORDER BY created_at DESC
    LIMIT 1;

    IF v_risk_status IS NULL THEN
      v_errors := v_errors || to_jsonb('Avaliação de risco não iniciada. Acesse a aba Risco.');
    ELSIF v_risk_status != 'approved' THEN
      v_errors := v_errors || to_jsonb('Avaliação de risco pendente de aprovação.');
    END IF;

    -- 2. If order is in a trip, check trip risk too
    SELECT trip_id INTO v_trip_id FROM orders WHERE id = p_entity_id;

    IF v_trip_id IS NOT NULL THEN
      SELECT status INTO v_trip_risk_status
      FROM risk_evaluations
      WHERE entity_type = 'trip'
        AND entity_id = v_trip_id
        AND status NOT IN ('expired', 'rejected')
      ORDER BY created_at DESC
      LIMIT 1;

      IF v_trip_risk_status IS NULL OR v_trip_risk_status != 'approved' THEN
        v_errors := v_errors || to_jsonb('Avaliação de risco da viagem (VG) pendente.');
      END IF;
    END IF;

    -- 3. Check Buonny validity
    IF NOT EXISTS (
      SELECT 1 FROM risk_evidence rev
      JOIN risk_evaluations re ON re.id = rev.evaluation_id
      WHERE re.entity_type = 'order'
        AND re.entity_id = p_entity_id
        AND rev.evidence_type = 'buonny_check'
        AND rev.status = 'valid'
        AND rev.expires_at > now()
    ) THEN
      v_errors := v_errors || to_jsonb('Consulta Buonny expirada ou inexistente.');
    END IF;
  END IF;

  -- If there are validation errors, return invalid
  IF jsonb_array_length(v_errors) > 0 THEN
    RETURN jsonb_build_object(
      'valid', false,
      'errors', v_errors,
      'requires_approval', v_transition.requires_approval,
      'approval_type', v_transition.approval_type,
      'post_actions', v_transition.post_actions,
      'required_fields', v_transition.required_fields,
      'required_documents', v_transition.required_documents
    );
  END IF;

  -- Valid transition
  RETURN jsonb_build_object(
    'valid', true,
    'errors', '[]'::JSONB,
    'requires_approval', v_transition.requires_approval,
    'approval_type', v_transition.approval_type,
    'post_actions', v_transition.post_actions,
    'required_fields', v_transition.required_fields,
    'required_documents', v_transition.required_documents,
    'description', v_transition.description
  );
END;
$$;


ALTER FUNCTION "public"."validate_transition"("p_entity_type" "text", "p_entity_id" "uuid", "p_from_stage" "text", "p_to_stage" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."validate_transition"("p_entity_type" "text", "p_entity_id" "uuid", "p_from_stage" "text", "p_to_stage" "text") IS 'Validates if a stage transition is allowed and returns requirements';



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


CREATE OR REPLACE FUNCTION "vectraclip"."get_company_secret_value"("p_company_id" "uuid", "p_name" "text") RETURNS "text"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vectraclip', 'vault', 'public'
    AS $$
DECLARE
  v_vault_id UUID;
  v_value    TEXT;
BEGIN
  SELECT vault_secret_id INTO v_vault_id
  FROM vectraclip.company_secrets
  WHERE company_id = p_company_id AND name = p_name;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  SELECT decrypted_secret INTO v_value
  FROM vault.decrypted_secrets
  WHERE id = v_vault_id;

  RETURN v_value;
END;
$$;


ALTER FUNCTION "vectraclip"."get_company_secret_value"("p_company_id" "uuid", "p_name" "text") OWNER TO "postgres";


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


CREATE OR REPLACE FUNCTION "vectraclip"."read_company_secret"("p_company_id" "uuid", "p_name" "text") RETURNS "text"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vectraclip', 'vault', 'public'
    AS $$
DECLARE
  v_vault_id uuid;
  v_value    text;
BEGIN
  SELECT vault_secret_id INTO v_vault_id
  FROM vectraclip.company_secrets
  WHERE company_id = p_company_id
    AND name = p_name
  LIMIT 1;

  IF v_vault_id IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT decrypted_secret INTO v_value
  FROM vault.decrypted_secrets
  WHERE id = v_vault_id
  LIMIT 1;

  RETURN v_value;
END;
$$;


ALTER FUNCTION "vectraclip"."read_company_secret"("p_company_id" "uuid", "p_name" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."set_kronos_rules_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "vectraclip"."set_kronos_rules_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."sipoc_company_id"() RETURNS "uuid"
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'vectraclip', 'public', 'pg_temp'
    AS $$
    SELECT ((auth.jwt() -> 'app_metadata' -> 'vectraclip') ->> 'company_id')::UUID;
$$;


ALTER FUNCTION "vectraclip"."sipoc_company_id"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."tasks_prevent_parent_cycle"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
declare
  cid uuid;
  hops integer := 0;
begin
  if tg_op = 'UPDATE'
     and coalesce(new.parent_task_id::text, '') = coalesce(old.parent_task_id::text, '') then
    return new;
  end if;

  if new.parent_task_id is null then
    return new;
  end if;

  if new.parent_task_id = new.id then
    raise exception 'tasks: parent_task_id cannot equal id';
  end if;

  cid := new.parent_task_id;
  while cid is not null and hops < 10000 loop
    if cid = new.id then
      raise exception 'tasks: parent_task_id introduces a cycle';
    end if;
    select t.parent_task_id into cid
    from vectraclip.tasks t
    where t.id = cid;
    hops := hops + 1;
  end loop;

  return new;
end;
$$;


ALTER FUNCTION "vectraclip"."tasks_prevent_parent_cycle"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "vectraclip"."upsert_company_secret"("p_company_id" "uuid", "p_name" "text", "p_value" "text", "p_description" "text" DEFAULT NULL::"text") RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vectraclip', 'vault', 'public'
    AS $$
DECLARE
  v_vault_id   UUID;
  v_secret_row vectraclip.company_secrets%ROWTYPE;
  v_full_name  TEXT;
  v_desc       TEXT;
BEGIN
  v_full_name := 'co:' || p_company_id::TEXT || ':' || p_name;
  v_desc      := COALESCE(p_description, '');   -- vault.secrets.description is NOT NULL

  SELECT * INTO v_secret_row
  FROM vectraclip.company_secrets
  WHERE company_id = p_company_id AND name = p_name;

  IF FOUND THEN
    PERFORM vault.update_secret(v_secret_row.vault_secret_id, p_value, v_full_name,
      COALESCE(p_description, v_secret_row.description, ''));
    UPDATE vectraclip.company_secrets
    SET description = COALESCE(p_description, description),
        updated_at  = now()
    WHERE id = v_secret_row.id;
    RETURN v_secret_row.vault_secret_id;
  ELSE
    v_vault_id := vault.create_secret(p_value, v_full_name, v_desc);
    INSERT INTO vectraclip.company_secrets (company_id, name, description, vault_secret_id)
    VALUES (p_company_id, p_name, p_description, v_vault_id);
    RETURN v_vault_id;
  END IF;
END;
$$;


ALTER FUNCTION "vectraclip"."upsert_company_secret"("p_company_id" "uuid", "p_name" "text", "p_value" "text", "p_description" "text") OWNER TO "postgres";


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


CREATE TABLE IF NOT EXISTS "public"."agent_jobs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "collected_data_id" "uuid",
    "status" "text" DEFAULT 'pending'::"text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "picked_at" timestamp with time zone,
    "result" "jsonb"
);


ALTER TABLE "public"."agent_jobs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ai_budget_config" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "key" "text" NOT NULL,
    "value" numeric NOT NULL,
    "description" "text",
    "updated_by" "uuid",
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."ai_budget_config" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ai_insights" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "insight_type" "text" NOT NULL,
    "entity_type" "text",
    "entity_id" "uuid",
    "analysis" "jsonb" NOT NULL,
    "summary_text" "text" NOT NULL,
    "expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_rating" smallint,
    "user_feedback" "text",
    CONSTRAINT "ai_insights_user_rating_check" CHECK ((("user_rating" IS NULL) OR (("user_rating" >= 1) AND ("user_rating" <= 5))))
);


ALTER TABLE "public"."ai_insights" OWNER TO "postgres";


COMMENT ON COLUMN "public"."ai_insights"."user_rating" IS 'User feedback: 1=not useful, 5=very useful';



COMMENT ON COLUMN "public"."ai_insights"."user_feedback" IS 'Optional free-text feedback from user';



CREATE TABLE IF NOT EXISTS "public"."ai_usage_tracking" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "analysis_type" "text" NOT NULL,
    "model_used" "text" NOT NULL,
    "input_tokens" integer DEFAULT 0 NOT NULL,
    "output_tokens" integer DEFAULT 0 NOT NULL,
    "cache_read_tokens" integer DEFAULT 0 NOT NULL,
    "cache_creation_tokens" integer DEFAULT 0 NOT NULL,
    "estimated_cost_usd" numeric(10,6) DEFAULT 0 NOT NULL,
    "status" "text" DEFAULT 'success'::"text" NOT NULL,
    "entity_type" "text",
    "entity_id" "uuid",
    "duration_ms" integer,
    "error_message" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."ai_usage_tracking" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."antt_floor_rates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "operation_table" "text" NOT NULL,
    "cargo_type" "text" NOT NULL,
    "axes_count" integer NOT NULL,
    "ccd" numeric NOT NULL,
    "cc" numeric NOT NULL,
    "valid_from" "date",
    "valid_until" "date",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "antt_floor_rates_axes_count_check" CHECK (("axes_count" > 0)),
    CONSTRAINT "antt_floor_rates_cc_check" CHECK (("cc" >= (0)::numeric)),
    CONSTRAINT "antt_floor_rates_ccd_check" CHECK (("ccd" >= (0)::numeric)),
    CONSTRAINT "antt_floor_rates_operation_table_check" CHECK (("operation_table" = ANY (ARRAY['A'::"text", 'B'::"text", 'C'::"text", 'D'::"text"])))
);


ALTER TABLE "public"."antt_floor_rates" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."antt_violation_alerts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "current_value" numeric NOT NULL,
    "piso" numeric NOT NULL,
    "gap" numeric GENERATED ALWAYS AS (("piso" - "current_value")) STORED,
    "stage" "text" NOT NULL,
    "detected_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolved_at" timestamp with time zone,
    "resolved_by" "uuid",
    "resolution_note" "text"
);


ALTER TABLE "public"."antt_violation_alerts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_requests" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "entity_type" "text" NOT NULL,
    "entity_id" "uuid" NOT NULL,
    "approval_type" "text" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "requested_by" "uuid",
    "assigned_to" "uuid",
    "assigned_to_role" "text" DEFAULT 'admin'::"text",
    "title" "text" NOT NULL,
    "description" "text",
    "ai_analysis" "jsonb",
    "decision_notes" "text",
    "decided_by" "uuid",
    "decided_at" timestamp with time zone,
    "expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolved_at" timestamp with time zone,
    "triggered_by" "text" DEFAULT 'manual'::"text"
);


ALTER TABLE "public"."approval_requests" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."approval_rules" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "entity_type" "text" NOT NULL,
    "trigger_condition" "jsonb" NOT NULL,
    "approval_type" "text" NOT NULL,
    "approver_role" "text" DEFAULT 'admin'::"text" NOT NULL,
    "auto_approve_after_hours" integer,
    "active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."approval_rules" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."audit_logs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "table_name" "text" NOT NULL,
    "record_id" "uuid" NOT NULL,
    "action" "text" NOT NULL,
    "old_values" "jsonb",
    "new_values" "jsonb",
    "user_id" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."audit_logs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."clients" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "email" "text",
    "phone" "text",
    "cnpj" "text",
    "address" "text",
    "city" "text",
    "state" "text",
    "notes" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"() NOT NULL,
    "zip_code" "text",
    "cpf" numeric,
    "cnpj_mask" "text",
    "zip_code_mask" "text",
    "contact_name" "text",
    "state_registration" "text",
    "legal_representative_name" "text",
    "legal_representative_cpf" "text",
    "legal_representative_role" "text",
    "address_number" "text",
    "address_complement" "text",
    "address_neighborhood" "text",
    "trade_name" "text",
    "legal_nature" "text",
    "legal_nature_code" "text",
    "company_size" "text",
    "cnae_main_code" "text",
    "cnae_main_description" "text",
    "cnaes_secondary" "jsonb" DEFAULT '[]'::"jsonb",
    "opening_date" "date",
    "registration_status" "text",
    "registration_status_date" "date",
    "registration_status_reason" "text",
    "efr" "text",
    "share_capital" numeric(15,2),
    "partners" "jsonb" DEFAULT '[]'::"jsonb",
    "cnpj_lookup_at" timestamp with time zone
);


ALTER TABLE "public"."clients" OWNER TO "postgres";


COMMENT ON COLUMN "public"."clients"."contact_name" IS 'Nome do Cliente';



COMMENT ON COLUMN "public"."clients"."state_registration" IS 'InscriÃ§Ã£o Estadual do cliente';



COMMENT ON COLUMN "public"."clients"."legal_representative_name" IS 'Nome do representante legal (para assinatura do contrato)';



COMMENT ON COLUMN "public"."clients"."legal_representative_cpf" IS 'CPF do representante legal';



COMMENT ON COLUMN "public"."clients"."legal_representative_role" IS 'Cargo/funÃ§Ã£o do representante legal (ex: SÃ³cio-Gerente)';



COMMENT ON COLUMN "public"."clients"."address_number" IS 'NÃºmero do endereÃ§o (complementa campo address existente)';



COMMENT ON COLUMN "public"."clients"."address_complement" IS 'Complemento do endereÃ§o';



COMMENT ON COLUMN "public"."clients"."address_neighborhood" IS 'Bairro';



COMMENT ON COLUMN "public"."clients"."trade_name" IS 'Nome Fantasia (titulo do estabelecimento) — Receita';



COMMENT ON COLUMN "public"."clients"."legal_nature" IS 'Natureza Juridica — Receita';



COMMENT ON COLUMN "public"."clients"."company_size" IS 'Porte da empresa: ME, EPP, DEMAIS';



COMMENT ON COLUMN "public"."clients"."cnae_main_code" IS 'CNAE principal (codigo) — Receita';



COMMENT ON COLUMN "public"."clients"."cnaes_secondary" IS 'Lista CNAEs secundarios: [{codigo, descricao}]';



COMMENT ON COLUMN "public"."clients"."registration_status" IS 'Situacao cadastral: ATIVA, BAIXADA, SUSPENSA, INAPTA, NULA';



COMMENT ON COLUMN "public"."clients"."efr" IS 'Ente Federativo Responsavel (so para orgaos publicos)';



COMMENT ON COLUMN "public"."clients"."share_capital" IS 'Capital social — QSA';



COMMENT ON COLUMN "public"."clients"."partners" IS 'Quadro societario QSA: [{name, role, role_code, document, entry_date, country, age_range}]';



COMMENT ON COLUMN "public"."clients"."cnpj_lookup_at" IS 'Timestamp da ultima consulta CNPJ na Receita';



CREATE TABLE IF NOT EXISTS "public"."cnh_categories" (
    "id" integer NOT NULL,
    "code" "text" NOT NULL,
    "description" "text" NOT NULL,
    "active" boolean DEFAULT true NOT NULL
);


ALTER TABLE "public"."cnh_categories" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."cnh_categories_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."cnh_categories_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."cnh_categories_id_seq" OWNED BY "public"."cnh_categories"."id";



CREATE TABLE IF NOT EXISTS "public"."collected_data" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "task_id" "uuid",
    "source_type" "text" NOT NULL,
    "source_ref" "text" NOT NULL,
    "markdown" "text" NOT NULL,
    "raw" "jsonb",
    "collected_at" timestamp with time zone DEFAULT "now"(),
    "processed" boolean DEFAULT false
);


ALTER TABLE "public"."collected_data" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."collection_orders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "oc_number" "text" NOT NULL,
    "oc_year" integer NOT NULL,
    "oc_month" integer NOT NULL,
    "oc_seq" integer NOT NULL,
    "order_id" "uuid" NOT NULL,
    "status" "public"."collection_order_status" DEFAULT 'emitida'::"public"."collection_order_status" NOT NULL,
    "sender_data" "jsonb" NOT NULL,
    "recipient_data" "jsonb" NOT NULL,
    "driver_data" "jsonb" NOT NULL,
    "vehicle_data" "jsonb" NOT NULL,
    "cargo_data" "jsonb" NOT NULL,
    "pickup_date" "date",
    "delivery_date" "date",
    "additional_info" "text",
    "pdf_storage_path" "text",
    "issued_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "issued_by" "uuid",
    "cancelled_at" timestamp with time zone,
    "cancelled_by" "uuid",
    "cancellation_reason" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "antt_data" "jsonb",
    CONSTRAINT "collection_orders_cancelled_consistency" CHECK (((("status" = 'cancelada'::"public"."collection_order_status") AND ("cancelled_at" IS NOT NULL)) OR (("status" = 'emitida'::"public"."collection_order_status") AND ("cancelled_at" IS NULL))))
);


ALTER TABLE "public"."collection_orders" OWNER TO "postgres";


COMMENT ON TABLE "public"."collection_orders" IS 'Ordens de coleta (OC) emitidas para OS na fase busca_motorista';



COMMENT ON COLUMN "public"."collection_orders"."oc_number" IS 'Identificador OC-YYYY-MM-NNNN com gap permanente em cancelamentos';



COMMENT ON COLUMN "public"."collection_orders"."sender_data" IS 'Snapshot do remetente (shipper) no momento da emissao';



COMMENT ON COLUMN "public"."collection_orders"."recipient_data" IS 'Snapshot do destinatario (client) no momento da emissao';



COMMENT ON COLUMN "public"."collection_orders"."driver_data" IS 'Snapshot do motorista (nome, cpf, cnh, antt, telefone)';



COMMENT ON COLUMN "public"."collection_orders"."vehicle_data" IS 'Snapshot do veiculo (placa cavalo, placa carreta, tipo, marca, modelo)';



COMMENT ON COLUMN "public"."collection_orders"."cargo_data" IS 'Snapshot da carga (peso_kg, volume_m3, cargo_value, cargo_type)';



COMMENT ON COLUMN "public"."collection_orders"."antt_data" IS 'Snapshot do resultado da consulta ANTT/RNTRC no momento da emissao da OC. Inclui situacao, rntrc, transportador, comprovante_url, etc.';



CREATE TABLE IF NOT EXISTS "public"."commercial_closeout_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "message_event_id" "uuid",
    "closeout_type" "text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "commercial_closeout_events_closeout_type_check" CHECK (("closeout_type" = ANY (ARRAY['accepted'::"text", 'accepted_with_condition'::"text", 'manual_gain'::"text", 'stage_changed'::"text", 'handoff_generated'::"text"])))
);


ALTER TABLE "public"."commercial_closeout_events" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."commercial_followup_rules" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "quote_stage" "text" NOT NULL,
    "trigger_after_minutes" integer DEFAULT 0 NOT NULL,
    "channel" "text" NOT NULL,
    "template_key" "text" NOT NULL,
    "stop_on_reply" boolean DEFAULT true NOT NULL,
    "stop_on_stage_change" boolean DEFAULT true NOT NULL,
    "max_attempts" integer DEFAULT 3 NOT NULL,
    "priority" integer DEFAULT 100 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "trigger_anchor" "text" DEFAULT 'proposal_sent_at'::"text" NOT NULL,
    "offset_minutes" integer DEFAULT 0 NOT NULL,
    "requires_estimated_loading_date" boolean DEFAULT false NOT NULL,
    "strategy_key" "text" DEFAULT 'consultive'::"text" NOT NULL,
    CONSTRAINT "commercial_followup_rules_channel_check" CHECK (("channel" = ANY (ARRAY['openclaw'::"text", 'email'::"text", 'meta'::"text"]))),
    CONSTRAINT "commercial_followup_rules_strategy_key_check" CHECK (("strategy_key" = ANY (ARRAY['consultive'::"text", 'value_reinforcement'::"text", 'closing'::"text", 'reactivation'::"text"]))),
    CONSTRAINT "commercial_followup_rules_trigger_anchor_check" CHECK (("trigger_anchor" = ANY (ARRAY['proposal_sent_at'::"text", 'estimated_loading_date'::"text"])))
);


ALTER TABLE "public"."commercial_followup_rules" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."commercial_followup_runs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "rule_id" "uuid" NOT NULL,
    "attempt_no" integer NOT NULL,
    "channel" "text" NOT NULL,
    "template_key" "text" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "notification_log_id" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "sent_at" timestamp with time zone,
    "replied_at" timestamp with time zone,
    "stopped_reason" "text",
    "target_type" "text",
    "recipient_phone" "text",
    "recipient_email" "text",
    CONSTRAINT "commercial_followup_runs_channel_check" CHECK (("channel" = ANY (ARRAY['openclaw'::"text", 'email'::"text", 'meta'::"text"]))),
    CONSTRAINT "commercial_followup_runs_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'sent'::"text", 'delivered'::"text", 'replied'::"text", 'failed'::"text", 'cancelled'::"text", 'skipped'::"text"]))),
    CONSTRAINT "commercial_followup_runs_target_type_check" CHECK (("target_type" = ANY (ARRAY['shipper'::"text", 'client'::"text"])))
);


ALTER TABLE "public"."commercial_followup_runs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."commercial_message_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid",
    "shipper_id" "uuid",
    "client_id" "uuid",
    "phone" "text",
    "channel" "text" NOT NULL,
    "direction" "text" NOT NULL,
    "external_message_id" "text",
    "template_key" "text",
    "message_text" "text",
    "classification" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "target_type" "text",
    "target_name" "text",
    "target_email" "text",
    CONSTRAINT "commercial_message_events_channel_check" CHECK (("channel" = ANY (ARRAY['openclaw'::"text", 'email'::"text", 'meta'::"text"]))),
    CONSTRAINT "commercial_message_events_classification_check" CHECK ((("classification" IS NULL) OR ("classification" = ANY (ARRAY['accepted'::"text", 'negotiation'::"text", 'revision_request'::"text", 'question'::"text", 'not_interested'::"text", 'deferred'::"text", 'other'::"text"])))),
    CONSTRAINT "commercial_message_events_direction_check" CHECK (("direction" = ANY (ARRAY['outbound'::"text", 'inbound'::"text"]))),
    CONSTRAINT "commercial_message_events_target_type_check" CHECK (("target_type" = ANY (ARRAY['shipper'::"text", 'client'::"text"])))
);


ALTER TABLE "public"."commercial_message_events" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."commercial_operational_handoffs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "order_id" "uuid",
    "handoff_status" "text" DEFAULT 'pending_review'::"text" NOT NULL,
    "operational_owner_name" "text",
    "handoff_summary" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "missing_fields" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "blockers" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "source" "text" DEFAULT 'commercial_phase3'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "commercial_operational_handoffs_handoff_status_check" CHECK (("handoff_status" = ANY (ARRAY['pending_review'::"text", 'ready_for_order'::"text", 'missing_data'::"text", 'blocked'::"text", 'order_created'::"text", 'cancelled'::"text"])))
);


ALTER TABLE "public"."commercial_operational_handoffs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."company_settings" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "legal_name" "text" DEFAULT ''::"text" NOT NULL,
    "trade_name" "text" DEFAULT ''::"text" NOT NULL,
    "cnpj" "text" DEFAULT ''::"text" NOT NULL,
    "state_registration" "text" DEFAULT ''::"text" NOT NULL,
    "municipal_registration" "text" DEFAULT ''::"text",
    "address_street" "text" DEFAULT ''::"text" NOT NULL,
    "address_number" "text" DEFAULT ''::"text" NOT NULL,
    "address_complement" "text" DEFAULT ''::"text",
    "address_neighborhood" "text" DEFAULT ''::"text" NOT NULL,
    "address_city" "text" DEFAULT ''::"text" NOT NULL,
    "address_state" "text" DEFAULT ''::"text" NOT NULL,
    "address_zip" "text" DEFAULT ''::"text" NOT NULL,
    "legal_representative_name" "text" DEFAULT ''::"text",
    "legal_representative_cpf" "text" DEFAULT ''::"text",
    "legal_representative_role" "text" DEFAULT ''::"text",
    "bank_name" "text" DEFAULT ''::"text",
    "bank_agency" "text" DEFAULT ''::"text",
    "bank_account" "text" DEFAULT ''::"text",
    "bank_pix_key" "text" DEFAULT ''::"text",
    "default_jurisdiction" "text" DEFAULT 'Navegantes/SC'::"text" NOT NULL,
    "signature_city" "text" DEFAULT 'Navegantes'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."company_settings" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."compliance_checks" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid",
    "check_type" "public"."compliance_check_type" NOT NULL,
    "rules_evaluated" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "violations" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "status" "public"."compliance_check_status" DEFAULT 'ok'::"public"."compliance_check_status" NOT NULL,
    "ai_analysis" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "result" "jsonb",
    "violation_type" "text",
    "entity_type" "text"
);


ALTER TABLE "public"."compliance_checks" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."conditional_fees" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "code" "text" NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "fee_type" "text" NOT NULL,
    "fee_value" numeric NOT NULL,
    "min_value" numeric,
    "max_value" numeric,
    "applies_to" "text" DEFAULT 'freight'::"text" NOT NULL,
    "conditions" "jsonb",
    "active" boolean DEFAULT true NOT NULL,
    "valid_from" "date",
    "valid_until" "date",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"(),
    CONSTRAINT "conditional_fees_applies_to_check" CHECK (("applies_to" = ANY (ARRAY['freight'::"text", 'cargo_value'::"text", 'total'::"text"]))),
    CONSTRAINT "conditional_fees_fee_type_check" CHECK (("fee_type" = ANY (ARRAY['percentage'::"text", 'fixed'::"text", 'per_kg'::"text"])))
);


ALTER TABLE "public"."conditional_fees" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."delivery_assessments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid",
    "order_id" "uuid",
    "endereco" "text" NOT NULL,
    "endereco_formatado" "text",
    "cidade" "text",
    "estado" "text",
    "lat" numeric,
    "lng" numeric,
    "peso_kg" numeric,
    "volume_m3" numeric,
    "volumes" integer,
    "cargo_type" "text",
    "nivel_dificuldade" "text",
    "score_total" integer,
    "chapas_recomendados" integer,
    "chapas_solicitados" integer,
    "custo_chapas_rs" numeric,
    "veiculo_recomendado" "text",
    "carroceria_recomendada" "text",
    "equipamento_apoio" "text",
    "restricao_aet" "jsonb",
    "alertas" "jsonb",
    "street_view_url" "text",
    "maps_url" "text",
    "street_view_disponivel" boolean,
    "score_detalhado" "jsonb",
    "perguntas_pendentes" "jsonb",
    "respostas_qualificacao" "jsonb",
    "status" "text" DEFAULT 'pendente'::"text",
    "notas" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."delivery_assessments" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."delivery_conditions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "label" "text" NOT NULL,
    "description" "text",
    "sort_order" integer DEFAULT 0 NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."delivery_conditions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."discharge_checklist_items" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "label" "text" NOT NULL,
    "description" "text",
    "sort_order" integer DEFAULT 0 NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."discharge_checklist_items" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."documents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid",
    "quote_id" "uuid",
    "type" "public"."document_type" NOT NULL,
    "file_name" "text" NOT NULL,
    "file_url" "text" NOT NULL,
    "file_size" integer,
    "nfe_key" "text",
    "validation_status" "text" DEFAULT 'pending'::"text",
    "uploaded_by" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "fat_id" "uuid",
    "trip_id" "uuid",
    "source" "text" DEFAULT 'upload'::"text" NOT NULL,
    CONSTRAINT "documents_source_check" CHECK (("source" = ANY (ARRAY['upload'::"text", 'inherited'::"text"])))
);


ALTER TABLE "public"."documents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."driver_offer_ranking_config" (
    "id" integer DEFAULT 1 NOT NULL,
    "weight_proximity" integer DEFAULT 35 NOT NULL,
    "weight_route_history" integer DEFAULT 25 NOT NULL,
    "weight_quality_score" integer DEFAULT 30 NOT NULL,
    "weight_price" integer DEFAULT 10 NOT NULL,
    "buonny_cargo_value_threshold" numeric(12,2) DEFAULT 100000.00 NOT NULL,
    "min_quality_score" integer DEFAULT 50 NOT NULL,
    "max_offers_default" integer DEFAULT 10 NOT NULL,
    "timeout_hours_default" numeric(4,1) DEFAULT 4.0 NOT NULL,
    "max_timeouts_before_escalation" integer DEFAULT 3 NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "driver_offer_ranking_config_id_check" CHECK (("id" = 1))
);


ALTER TABLE "public"."driver_offer_ranking_config" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."driver_offer_sequences" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "order_id" "uuid",
    "status" "public"."offer_sequence_status" DEFAULT 'ranking'::"public"."offer_sequence_status" NOT NULL,
    "current_position" integer DEFAULT 0 NOT NULL,
    "max_offers" integer DEFAULT 10 NOT NULL,
    "timeout_hours" numeric(4,1) DEFAULT 4.0 NOT NULL,
    "origin" "text",
    "destination" "text",
    "origin_city" "text",
    "origin_state" character varying(2),
    "destination_city" "text",
    "destination_state" character varying(2),
    "vehicle_type_id" "uuid",
    "cargo_type" "text",
    "cargo_value" numeric(12,2),
    "weight" numeric(10,2),
    "estimated_loading_date" "date",
    "accepted_driver_id" "uuid",
    "accepted_at" timestamp with time zone,
    "trip_id" "uuid",
    "escalated_at" timestamp with time zone,
    "escalation_reason" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."driver_offer_sequences" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."driver_offers" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sequence_id" "uuid" NOT NULL,
    "driver_id" "uuid" NOT NULL,
    "position" integer NOT NULL,
    "status" "public"."driver_offer_status" DEFAULT 'pending'::"public"."driver_offer_status" NOT NULL,
    "skip_reason" "text",
    "ranking_score" numeric(6,2),
    "ranking_details" "jsonb" DEFAULT '{}'::"jsonb",
    "freight_value_offered" numeric(12,2),
    "offered_at" timestamp with time zone,
    "timeout_at" timestamp with time zone,
    "responded_at" timestamp with time zone,
    "response_channel" "text",
    "response_text" "text",
    "buonny_check_id" "text",
    "buonny_status" "text",
    "whatsapp_message_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."driver_offers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."driver_qualifications" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid" NOT NULL,
    "driver_cpf" "text",
    "driver_name" "text",
    "status" "public"."driver_qualification_status" DEFAULT 'pendente'::"public"."driver_qualification_status" NOT NULL,
    "checklist" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "risk_flags" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "risk_score" integer,
    "ai_analysis" "jsonb",
    "decided_by" "uuid",
    "decided_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "driver_id" "uuid",
    "qualification_type" "text",
    "expires_at" timestamp with time zone,
    "whatsapp_sent_at" timestamp with time zone,
    "whatsapp_reminded_at" timestamp with time zone,
    CONSTRAINT "driver_qualifications_risk_score_check" CHECK ((("risk_score" >= 0) AND ("risk_score" <= 100)))
);


ALTER TABLE "public"."driver_qualifications" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."drivers" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "phone" "text",
    "cnh" "text",
    "cnh_category" "text",
    "active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "antt" "text",
    "cpf" "text",
    "last_refusal_at" timestamp with time zone,
    "refusal_count" integer DEFAULT 0,
    "cooldown_days" integer DEFAULT 3,
    "phone_normalized" "text",
    "cnh_expiry" "date",
    "antt_expiry" "date",
    "contract_type" "public"."driver_contract_type" DEFAULT 'proprio'::"public"."driver_contract_type" NOT NULL,
    "rntrc_registry_type" "public"."rntrc_registry_type"
);


ALTER TABLE "public"."drivers" OWNER TO "postgres";


COMMENT ON COLUMN "public"."drivers"."antt" IS 'Registro ANTT (RNTRC) do motorista';



COMMENT ON COLUMN "public"."drivers"."cpf" IS 'CPF do motorista (11 dígitos, sem pontuação)';



CREATE TABLE IF NOT EXISTS "public"."edge_function_api_keys" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "key_hash" "text" NOT NULL,
    "scopes" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "last_used" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "expires_at" timestamp with time zone
);


ALTER TABLE "public"."edge_function_api_keys" OWNER TO "postgres";


COMMENT ON TABLE "public"."edge_function_api_keys" IS 'API Keys para autenticação híbrida nas Edge Functions. key_hash = sha256(key). A key plain é gerada uma vez e armazenada no Cloudflare Workers secrets.';



CREATE TABLE IF NOT EXISTS "public"."equipment_rental_rates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "code" "text" NOT NULL,
    "unit" "text" DEFAULT 'dia'::"text" NOT NULL,
    "value" numeric(12,2) DEFAULT 0 NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "valid_from" "date",
    "valid_until" "date",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."equipment_rental_rates" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."financial_documents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "owner_id" "uuid",
    "type" "public"."financial_doc_type" NOT NULL,
    "code" "text",
    "status" "text" DEFAULT 'INCLUIR'::"text" NOT NULL,
    "source_type" "public"."financial_source_type" NOT NULL,
    "source_id" "uuid" NOT NULL,
    "erp_status" "text",
    "erp_reference" "text",
    "total_amount" numeric(14,2),
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."financial_documents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."financial_installments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "financial_document_id" "uuid" NOT NULL,
    "status" "public"."financial_installment_status" DEFAULT 'pendente'::"public"."financial_installment_status" NOT NULL,
    "due_date" "date" NOT NULL,
    "amount" numeric(14,2),
    "payment_method" "text",
    "settled_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."financial_installments" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."financial_documents_kanban" WITH ("security_invoker"='true') AS
 SELECT "id",
    "owner_id",
    "type",
    "code",
    "status",
    "source_type",
    "source_id",
    "erp_status",
    "erp_reference",
    "total_amount",
    "notes",
    "created_at",
    "updated_at",
    (EXISTS ( SELECT 1
           FROM "public"."financial_installments" "i"
          WHERE (("i"."financial_document_id" = "d"."id") AND ("i"."status" = 'pendente'::"public"."financial_installment_status") AND ("i"."due_date" < CURRENT_DATE)))) AS "is_overdue",
    ( SELECT "count"(*) AS "count"
           FROM "public"."financial_installments" "i"
          WHERE ("i"."financial_document_id" = "d"."id")) AS "installments_total",
    ( SELECT "count"(*) AS "count"
           FROM "public"."financial_installments" "i"
          WHERE (("i"."financial_document_id" = "d"."id") AND ("i"."status" = 'pendente'::"public"."financial_installment_status"))) AS "installments_pending",
    ( SELECT "count"(*) AS "count"
           FROM "public"."financial_installments" "i"
          WHERE (("i"."financial_document_id" = "d"."id") AND ("i"."status" = 'baixado'::"public"."financial_installment_status"))) AS "installments_settled",
    ( SELECT "min"("i"."due_date") AS "min"
           FROM "public"."financial_installments" "i"
          WHERE (("i"."financial_document_id" = "d"."id") AND ("i"."status" = 'pendente'::"public"."financial_installment_status"))) AS "next_due_date"
   FROM "public"."financial_documents" "d";


ALTER VIEW "public"."financial_documents_kanban" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."orders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "os_number" "text" NOT NULL,
    "quote_id" "uuid",
    "client_id" "uuid",
    "client_name" "text" NOT NULL,
    "origin" "text" NOT NULL,
    "destination" "text" NOT NULL,
    "value" numeric(12,2) DEFAULT 0 NOT NULL,
    "stage" "public"."order_stage" DEFAULT 'ordem_criada'::"public"."order_stage" NOT NULL,
    "driver_name" "text",
    "driver_phone" "text",
    "vehicle_plate" "text",
    "eta" timestamp with time zone,
    "has_nfe" boolean DEFAULT false NOT NULL,
    "has_cte" boolean DEFAULT false NOT NULL,
    "has_pod" boolean DEFAULT false NOT NULL,
    "notes" "text",
    "assigned_to" "uuid",
    "created_by" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "waiting_time_hours" numeric,
    "waiting_time_cost" numeric,
    "has_crlv" boolean DEFAULT false,
    "has_cnh" boolean DEFAULT false,
    "has_comp_residencia" boolean DEFAULT false,
    "has_antt" boolean DEFAULT false,
    "has_mdf" boolean DEFAULT false,
    "has_gr" boolean DEFAULT false,
    "has_antt_motorista" boolean DEFAULT false,
    "has_mdfe" boolean DEFAULT false,
    "carreteiro_antt" numeric,
    "carreteiro_real" numeric,
    "owner_name" "text",
    "owner_phone" "text",
    "driver_cnh" "text",
    "driver_antt" "text",
    "vehicle_brand" "text",
    "vehicle_model" "text",
    "vehicle_type_name" "text",
    "has_analise_gr" boolean DEFAULT false,
    "has_doc_rota" boolean DEFAULT false,
    "has_vpo" boolean DEFAULT false,
    "cargo_type" "text",
    "weight" numeric,
    "volume" numeric,
    "price_table_id" "uuid",
    "vehicle_type_id" "uuid",
    "payment_term_id" "uuid",
    "km_distance" numeric,
    "toll_value" numeric,
    "pricing_breakdown" "jsonb",
    "freight_type" "text",
    "freight_modality" "text",
    "shipper_id" "uuid",
    "shipper_name" "text",
    "origin_cep" "text",
    "destination_cep" "text",
    "carrier_payment_term_id" "uuid",
    "carrier_advance_date" "date",
    "carrier_balance_date" "date",
    "driver_id" "uuid",
    "trip_id" "uuid",
    "pedagio_real" numeric,
    "descarga_real" numeric,
    "has_comprovante_descarga" boolean DEFAULT false,
    "cargo_value" numeric(15,2),
    "risk_evaluation_id" "uuid",
    "pedagio_charge_type" "public"."pedagio_charge_type",
    "pedagio_debitado_no_cte" boolean DEFAULT false,
    "payment_method" "text",
    "carrier_payment_method" "text",
    "pickup_date" "date",
    CONSTRAINT "orders_carrier_payment_method_check" CHECK ((("carrier_payment_method" IS NULL) OR ("carrier_payment_method" = ANY (ARRAY['pix'::"text", 'boleto'::"text", 'cartao'::"text", 'transferencia'::"text", 'outro'::"text"])))),
    CONSTRAINT "orders_payment_method_check" CHECK ((("payment_method" IS NULL) OR ("payment_method" = ANY (ARRAY['pix'::"text", 'boleto'::"text", 'cartao'::"text", 'transferencia'::"text", 'outro'::"text"]))))
);


ALTER TABLE "public"."orders" OWNER TO "postgres";


COMMENT ON COLUMN "public"."orders"."driver_cnh" IS 'Snapshot: CNH do motorista no momento da atribuição';



COMMENT ON COLUMN "public"."orders"."driver_antt" IS 'Snapshot: ANTT/RNTRC do motorista no momento da atribuição';



COMMENT ON COLUMN "public"."orders"."vehicle_brand" IS 'Snapshot: Marca do veículo no momento da atribuição';



COMMENT ON COLUMN "public"."orders"."vehicle_model" IS 'Snapshot: Modelo do veículo no momento da atribuição';



COMMENT ON COLUMN "public"."orders"."vehicle_type_name" IS 'Snapshot: Tipo de veículo no momento da atribuição';



COMMENT ON COLUMN "public"."orders"."pedagio_real" IS 'Valor real de pedágio informado manualmente (para comparar com previsto do breakdown)';



COMMENT ON COLUMN "public"."orders"."descarga_real" IS 'Valor real de carga/descarga informado manualmente (para comparar com previsto do breakdown)';



COMMENT ON COLUMN "public"."orders"."pedagio_charge_type" IS 'Tipo de cobrança do pedágio para cálculo da base ICMS do CT-e. NULL = comportamento padrão (A).';



COMMENT ON COLUMN "public"."orders"."pedagio_debitado_no_cte" IS 'Se true, pedágio foi debitado ao tomador no CT-e e entra na base tributável.';



COMMENT ON COLUMN "public"."orders"."payment_method" IS 'Método de pagamento do cliente (pix/boleto/cartao/transferencia/outro)';



COMMENT ON COLUMN "public"."orders"."carrier_payment_method" IS 'Método de pagamento do transportador (pix/boleto/cartao/transferencia/outro)';



COMMENT ON COLUMN "public"."orders"."pickup_date" IS 'Data prevista de coleta da carga. Editavel pelo operador na OS. Usado na Ordem de Coleta (PDF).';



CREATE TABLE IF NOT EXISTS "public"."payment_proofs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid" NOT NULL,
    "trip_id" "uuid",
    "document_id" "uuid" NOT NULL,
    "proof_type" "text" NOT NULL,
    "method" "text",
    "amount" numeric,
    "paid_at" timestamp with time zone,
    "transaction_id" "text",
    "payee_name" "text",
    "payee_document" "text",
    "extracted_fields" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "extraction_confidence" numeric,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expected_amount" numeric,
    CONSTRAINT "payment_proofs_method_check" CHECK (("method" = ANY (ARRAY['pix'::"text", 'boleto'::"text", 'outro'::"text"]))),
    CONSTRAINT "payment_proofs_proof_type_check" CHECK (("proof_type" = ANY (ARRAY['adiantamento'::"text", 'saldo'::"text", 'outros'::"text"]))),
    CONSTRAINT "payment_proofs_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'matched'::"text", 'mismatch'::"text"])))
);


ALTER TABLE "public"."payment_proofs" OWNER TO "postgres";


COMMENT ON COLUMN "public"."payment_proofs"."expected_amount" IS 'Valor esperado para este proof (adiantamento ou saldo) calculado a partir de carreteiro_real e advance_percent da condição de pagamento';



CREATE TABLE IF NOT EXISTS "public"."payment_terms" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "code" "text" NOT NULL,
    "name" "text" NOT NULL,
    "days" integer NOT NULL,
    "adjustment_percent" numeric DEFAULT 0 NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"(),
    "advance_percent" numeric DEFAULT 0
);


ALTER TABLE "public"."payment_terms" OWNER TO "postgres";


COMMENT ON COLUMN "public"."payment_terms"."advance_percent" IS 'Percentual de adiantamento: 0 = à vista ou prazo normal, 50 = 50/50, 70 = 70/30';



CREATE OR REPLACE VIEW "public"."v_order_payment_reconciliation" WITH ("security_invoker"='true') AS
 SELECT "o"."id" AS "order_id",
    "o"."os_number",
    "o"."trip_id",
    COALESCE(NULLIF(COALESCE("sum"("p"."expected_amount") FILTER (WHERE ("p"."expected_amount" IS NOT NULL)), (0)::numeric), (0)::numeric), COALESCE("o"."carreteiro_real", (0)::numeric)) AS "expected_amount",
    (COALESCE("o"."carreteiro_real", (0)::numeric) > (0)::numeric) AS "has_expected_value",
    COALESCE("sum"("p"."amount") FILTER (WHERE ("p"."amount" IS NOT NULL)), (0)::numeric) AS "paid_amount",
    (COALESCE("sum"("p"."amount") FILTER (WHERE ("p"."amount" IS NOT NULL)), (0)::numeric) - COALESCE(NULLIF(COALESCE("sum"("p"."expected_amount") FILTER (WHERE ("p"."expected_amount" IS NOT NULL)), (0)::numeric), (0)::numeric), COALESCE("o"."carreteiro_real", (0)::numeric))) AS "delta_amount",
    ("abs"((COALESCE("sum"("p"."amount") FILTER (WHERE ("p"."amount" IS NOT NULL)), (0)::numeric) - COALESCE(NULLIF(COALESCE("sum"("p"."expected_amount") FILTER (WHERE ("p"."expected_amount" IS NOT NULL)), (0)::numeric), (0)::numeric), COALESCE("o"."carreteiro_real", (0)::numeric)))) <= (1)::numeric) AS "is_reconciled",
    "count"("p"."id") AS "proofs_count",
    "max"("p"."paid_at") AS "last_paid_at"
   FROM ("public"."orders" "o"
     LEFT JOIN "public"."payment_proofs" "p" ON (("p"."order_id" = "o"."id")))
  GROUP BY "o"."id", "o"."os_number", "o"."trip_id", "o"."carreteiro_real";


ALTER VIEW "public"."v_order_payment_reconciliation" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."vehicle_types" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "code" "text" NOT NULL,
    "name" "text" NOT NULL,
    "axes_count" integer NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"(),
    "ailog_category" "text",
    "rolling_type" "text" DEFAULT 'dupla'::"text",
    "vehicle_profile" "text" DEFAULT 'CAMINHAO'::"text"
);


ALTER TABLE "public"."vehicle_types" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."financial_payable_kanban" WITH ("security_invoker"='true') AS
 SELECT "k"."id",
    "k"."owner_id",
    "k"."type",
    "k"."code",
    "k"."status",
    "k"."source_type",
    "k"."source_id",
    "k"."erp_status",
    "k"."erp_reference",
    "k"."total_amount",
    "k"."notes",
    "k"."created_at",
    "k"."updated_at",
    "k"."is_overdue",
    "k"."installments_total",
    "k"."installments_pending",
    "k"."installments_settled",
    "k"."next_due_date",
    "o"."client_name",
    "o"."origin",
    "o"."destination",
    "o"."origin_cep",
    "o"."destination_cep",
    "o"."value" AS "order_value",
    "o"."carreteiro_real",
    "o"."carreteiro_antt",
    "o"."cargo_type",
    "o"."weight",
    "o"."volume",
    "o"."km_distance",
    "o"."freight_type",
    "o"."freight_modality",
    "o"."toll_value",
    "o"."pricing_breakdown",
    "o"."shipper_name",
    "o"."trip_id",
    "t"."trip_number",
    COALESCE("r"."expected_amount", (0)::numeric) AS "expected_amount",
    COALESCE("r"."paid_amount", (0)::numeric) AS "paid_amount",
    COALESCE("r"."delta_amount", (0)::numeric) AS "delta_amount",
    COALESCE("r"."is_reconciled", false) AS "is_reconciled",
    (COALESCE("r"."proofs_count", (0)::bigint))::integer AS "proofs_count",
    "vt"."name" AS "vehicle_type_name",
    "vt"."code" AS "vehicle_type_code",
    "vt"."axes_count",
    "pt"."name" AS "payment_term_name",
    "pt"."code" AS "payment_term_code",
    "pt"."days" AS "payment_term_days",
    "pt"."adjustment_percent" AS "payment_term_adjustment",
    "pt"."advance_percent" AS "payment_term_advance"
   FROM ((((("public"."financial_documents_kanban" "k"
     JOIN "public"."orders" "o" ON (("o"."id" = "k"."source_id")))
     LEFT JOIN "public"."trips" "t" ON (("t"."id" = "o"."trip_id")))
     LEFT JOIN "public"."v_order_payment_reconciliation" "r" ON (("r"."order_id" = "o"."id")))
     LEFT JOIN "public"."vehicle_types" "vt" ON (("vt"."id" = "o"."vehicle_type_id")))
     LEFT JOIN "public"."payment_terms" "pt" ON (("pt"."id" = "o"."payment_term_id")))
  WHERE ("k"."type" = 'PAG'::"public"."financial_doc_type");


ALTER VIEW "public"."financial_payable_kanban" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."quote_payment_proofs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "document_id" "uuid" NOT NULL,
    "proof_type" "text" NOT NULL,
    "amount" numeric,
    "expected_amount" numeric,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "extracted_fields" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "delta_reason" "text",
    CONSTRAINT "quote_payment_proofs_proof_type_check" CHECK (("proof_type" = ANY (ARRAY['a_vista'::"text", 'adiantamento'::"text", 'saldo'::"text", 'a_prazo'::"text"]))),
    CONSTRAINT "quote_payment_proofs_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'matched'::"text", 'mismatch'::"text"])))
);


ALTER TABLE "public"."quote_payment_proofs" OWNER TO "postgres";


COMMENT ON COLUMN "public"."quote_payment_proofs"."delta_reason" IS 'Reason for amount divergence: mao_de_obra, avaria, atraso, negociacao, taxa_banco, arredondamento, outro';



CREATE TABLE IF NOT EXISTS "public"."quotes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "client_id" "uuid",
    "client_name" "text" NOT NULL,
    "client_email" "text",
    "origin" "text" NOT NULL,
    "destination" "text" NOT NULL,
    "value" numeric(12,2) DEFAULT 0 NOT NULL,
    "stage" "public"."quote_stage" DEFAULT 'novo_pedido'::"public"."quote_stage" NOT NULL,
    "tags" "text"[] DEFAULT '{}'::"text"[],
    "weight" numeric(10,2),
    "volume" numeric(10,2),
    "cargo_type" "text",
    "validity_date" "date",
    "notes" "text",
    "assigned_to" "uuid",
    "created_by" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "price_table_id" "uuid",
    "freight_modality" "text",
    "cargo_value" numeric,
    "km_distance" numeric,
    "pricing_breakdown" "jsonb",
    "vehicle_type_id" "uuid",
    "payment_term_id" "uuid",
    "cubage_weight" numeric,
    "billable_weight" numeric,
    "toll_value" numeric,
    "tac_percent" numeric,
    "waiting_time_cost" numeric,
    "conditional_fees_breakdown" "jsonb",
    "delivery_conditions_selected" "jsonb" DEFAULT '[]'::"jsonb",
    "discharge_checklist_selected" "jsonb" DEFAULT '[]'::"jsonb",
    "delivery_notes" "text",
    "shipper_name" "text",
    "shipper_email" "text",
    "origin_cep" "text",
    "destination_cep" "text",
    "freight_type" "text",
    "shipper_id" "uuid",
    "quote_code" "text",
    "advance_due_date" "date",
    "balance_due_date" "date",
    "email_sent" boolean DEFAULT false NOT NULL,
    "email_sent_at" timestamp with time zone,
    "payment_method" "text",
    "estimated_loading_date" "date",
    "is_legacy" boolean DEFAULT false NOT NULL,
    "additional_shippers" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "discount_value" numeric(12,2) DEFAULT 0,
    "approval_status" "text",
    "approval_metadata" "jsonb",
    "proposal_sent_at" timestamp with time zone,
    "last_commercial_reply_at" timestamp with time zone,
    "commercial_owner_name" "text",
    "handoff_required" boolean DEFAULT false NOT NULL,
    "followup_target_type" "text" DEFAULT 'shipper'::"text",
    "followup_target_locked_at" timestamp with time zone,
    "resend_email_id" "text",
    "sent_at" timestamp with time zone,
    "delivered_at" timestamp with time zone,
    "opened_at" timestamp with time zone,
    CONSTRAINT "quotes_approval_status_check" CHECK (("approval_status" = ANY (ARRAY['auto_approved'::"text", 'flagged_for_review'::"text"]))),
    CONSTRAINT "quotes_followup_target_type_check" CHECK (("followup_target_type" = ANY (ARRAY['shipper'::"text", 'client'::"text"]))),
    CONSTRAINT "quotes_freight_modality_check" CHECK (("freight_modality" = ANY (ARRAY['lotacao'::"text", 'fracionado'::"text"]))),
    CONSTRAINT "quotes_payment_method_check" CHECK ((("payment_method" IS NULL) OR ("payment_method" = ANY (ARRAY['pix'::"text", 'boleto'::"text", 'cartao'::"text", 'transferencia'::"text", 'outro'::"text"]))))
);


ALTER TABLE "public"."quotes" OWNER TO "postgres";


COMMENT ON COLUMN "public"."quotes"."price_table_id" IS 'FK para tabela de preço usada no cálculo';



COMMENT ON COLUMN "public"."quotes"."freight_modality" IS 'Modalidade: lotacao ou fracionado';



COMMENT ON COLUMN "public"."quotes"."cargo_value" IS 'Valor da mercadoria (para cálculo de ad valorem)';



COMMENT ON COLUMN "public"."quotes"."km_distance" IS 'Distância em KM usada no cálculo';



COMMENT ON COLUMN "public"."quotes"."pricing_breakdown" IS 'Snapshot JSONB do cálculo para auditoria';



COMMENT ON COLUMN "public"."quotes"."advance_due_date" IS 'Data do adiantamento (50% ou 70%) ou data à vista';



COMMENT ON COLUMN "public"."quotes"."balance_due_date" IS 'Data do saldo (50% ou 30%), null para à vista';



COMMENT ON COLUMN "public"."quotes"."email_sent" IS 'Whether a quote email has been sent to the client';



COMMENT ON COLUMN "public"."quotes"."email_sent_at" IS 'Timestamp when the quote email was sent';



COMMENT ON COLUMN "public"."quotes"."payment_method" IS 'Método de pagamento do cliente (pix/boleto/cartao/transferencia/outro)';



COMMENT ON COLUMN "public"."quotes"."estimated_loading_date" IS 'Previsão de carregamento — usada para follow-up com embarcador';



COMMENT ON COLUMN "public"."quotes"."is_legacy" IS 'Cotação antiga (pré-MVP): sem motor de cálculo, FAT+PAG editáveis manualmente';



COMMENT ON COLUMN "public"."quotes"."additional_shippers" IS 'Embarcadores adicionais: [{shipper_id, name, email?}]. Principal continua em shipper_id/shipper_name.';



COMMENT ON COLUMN "public"."quotes"."discount_value" IS 'Desconto comercial aplicado sobre o total cliente. value = totalCliente - discount_value.';



COMMENT ON COLUMN "public"."quotes"."approval_status" IS 'Decisão do auto-approval-worker: auto_approved ou flagged_for_review';



COMMENT ON COLUMN "public"."quotes"."approval_metadata" IS 'Metadados da avaliação: critérios, motivos, timestamp, versão do worker';



CREATE OR REPLACE VIEW "public"."v_quote_payment_reconciliation" WITH ("security_invoker"='true') AS
 WITH "proof_sums" AS (
         SELECT "q_1"."id" AS "quote_id",
            COALESCE(NULLIF(COALESCE("sum"("qpp"."expected_amount") FILTER (WHERE ("qpp"."expected_amount" IS NOT NULL)), (0)::numeric), (0)::numeric), "max"(COALESCE("q_1"."value", (0)::numeric))) AS "expected_amount",
            COALESCE("sum"("qpp"."amount") FILTER (WHERE ("qpp"."amount" IS NOT NULL)), (0)::numeric) AS "paid_amount",
            "count"("qpp"."id") AS "proofs_count",
            ("count"("qpp"."id") = "count"("qpp"."amount")) AS "all_amounts_filled",
            "count"(*) FILTER (WHERE (("qpp"."amount" IS NOT NULL) AND ("abs"((COALESCE("qpp"."amount", (0)::numeric) - COALESCE("qpp"."expected_amount", (0)::numeric))) > (1)::numeric) AND ("qpp"."delta_reason" IS NULL))) AS "unjustified_count"
           FROM ("public"."quotes" "q_1"
             LEFT JOIN "public"."quote_payment_proofs" "qpp" ON (("qpp"."quote_id" = "q_1"."id")))
          GROUP BY "q_1"."id"
        )
 SELECT "q"."id" AS "quote_id",
    "q"."quote_code",
    "ps"."expected_amount",
    "ps"."paid_amount",
    ("ps"."paid_amount" - "ps"."expected_amount") AS "delta_amount",
    (("abs"(("ps"."paid_amount" - "ps"."expected_amount")) <= (1)::numeric) OR (("ps"."proofs_count" > 0) AND "ps"."all_amounts_filled" AND ("ps"."unjustified_count" = 0))) AS "is_reconciled",
    "ps"."proofs_count"
   FROM ("public"."quotes" "q"
     JOIN "proof_sums" "ps" ON (("ps"."quote_id" = "q"."id")));


ALTER VIEW "public"."v_quote_payment_reconciliation" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."financial_receivable_kanban" WITH ("security_invoker"='true') AS
 SELECT "k"."id",
    "k"."owner_id",
    "k"."type",
    "k"."code",
    "k"."status",
    "k"."source_type",
    "k"."source_id",
    "k"."erp_status",
    "k"."erp_reference",
    "k"."total_amount",
    "k"."notes",
    "k"."created_at",
    "k"."updated_at",
    "k"."is_overdue",
    "k"."installments_total",
    "k"."installments_pending",
    "k"."installments_settled",
    "k"."next_due_date",
    "q"."client_name",
    "q"."origin",
    "q"."destination",
    "q"."origin_cep",
    "q"."destination_cep",
    "q"."value" AS "quote_value",
    "q"."cargo_type",
    "q"."weight",
    "q"."volume",
    "q"."km_distance",
    "q"."freight_type",
    "q"."freight_modality",
    "q"."toll_value",
    "q"."pricing_breakdown",
    "q"."shipper_name",
    COALESCE("r"."expected_amount", (0)::numeric) AS "expected_amount",
    COALESCE("r"."paid_amount", (0)::numeric) AS "paid_amount",
    COALESCE("r"."delta_amount", (0)::numeric) AS "delta_amount",
    COALESCE("r"."is_reconciled", false) AS "is_reconciled",
    (COALESCE("r"."proofs_count", (0)::bigint))::integer AS "proofs_count",
    "vt"."name" AS "vehicle_type_name",
    "vt"."code" AS "vehicle_type_code",
    "vt"."axes_count",
    "pt"."name" AS "payment_term_name",
    "pt"."code" AS "payment_term_code",
    "pt"."days" AS "payment_term_days",
    "pt"."adjustment_percent" AS "payment_term_adjustment",
    "pt"."advance_percent" AS "payment_term_advance"
   FROM (((("public"."financial_documents_kanban" "k"
     JOIN "public"."quotes" "q" ON (("q"."id" = "k"."source_id")))
     LEFT JOIN "public"."v_quote_payment_reconciliation" "r" ON (("r"."quote_id" = "q"."id")))
     LEFT JOIN "public"."vehicle_types" "vt" ON (("vt"."id" = "q"."vehicle_type_id")))
     LEFT JOIN "public"."payment_terms" "pt" ON (("pt"."id" = "q"."payment_term_id")))
  WHERE ("k"."type" = 'FAT'::"public"."financial_doc_type");


ALTER VIEW "public"."financial_receivable_kanban" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."order_gris_services" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid" NOT NULL,
    "gris_service_id" "uuid" NOT NULL,
    "amount_previsto" numeric,
    "amount_real" numeric,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."order_gris_services" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."gris_service_items" WITH ("security_invoker"='true') AS
 SELECT "order_id",
    COALESCE("amount_real", "amount_previsto") AS "amount"
   FROM "public"."order_gris_services";


ALTER VIEW "public"."gris_service_items" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."gris_services" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "code" "text" NOT NULL,
    "name" "text" NOT NULL,
    "default_percent" numeric DEFAULT 0.30,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."gris_services" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."icms_rates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "origin_state" character(2) NOT NULL,
    "destination_state" character(2) NOT NULL,
    "rate_percent" numeric NOT NULL,
    "valid_from" "date",
    "valid_until" "date",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"(),
    CONSTRAINT "icms_rates_destination_state_format" CHECK (("destination_state" ~ '^[A-Z]{2}$'::"text")),
    CONSTRAINT "icms_rates_origin_state_format" CHECK (("origin_state" ~ '^[A-Z]{2}$'::"text")),
    CONSTRAINT "icms_rates_rate_percent_check" CHECK ((("rate_percent" >= (0)::numeric) AND ("rate_percent" <= (100)::numeric)))
);


ALTER TABLE "public"."icms_rates" OWNER TO "postgres";


COMMENT ON TABLE "public"."icms_rates" IS 'Alíquotas de ICMS por UF origem x UF destino';



COMMENT ON COLUMN "public"."icms_rates"."rate_percent" IS 'Alíquota em percentual (0-100)';



CREATE TABLE IF NOT EXISTS "public"."insurance_logs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "environment" "text" DEFAULT 'prod'::"text" NOT NULL,
    "source" "text" DEFAULT 'edge_function'::"text" NOT NULL,
    "function_name" "text" DEFAULT 'buonny-check-worker'::"text" NOT NULL,
    "request_id" "uuid",
    "trace_id" "text",
    "status" "text" NOT NULL,
    "error_code" "text",
    "error_message" "text",
    "duration_ms" integer,
    "fallback_used" boolean DEFAULT false NOT NULL,
    "origin_uf" "text",
    "destination_uf" "text",
    "weight" numeric,
    "product_type" "text",
    "premium_estimate_cents" bigint,
    "raw" "jsonb",
    CONSTRAINT "insurance_logs_status_check" CHECK (("status" = ANY (ARRAY['success'::"text", 'error'::"text", 'timeout'::"text", 'rate_limit'::"text", 'fallback'::"text"])))
);


ALTER TABLE "public"."insurance_logs" OWNER TO "postgres";


COMMENT ON TABLE "public"."insurance_logs" IS 'Structured logs for insurance (Buonny) calls: used for metrics, dashboards and alerting.';



CREATE OR REPLACE VIEW "public"."insurance_metrics_error_breakdown" WITH ("security_invoker"='true') AS
 SELECT "date_trunc"('1 hour'::"text", "created_at") AS "bucket_1h",
    "environment",
    "status",
    "error_code",
    "count"(*) AS "count"
   FROM "public"."insurance_logs"
  WHERE ("status" = ANY (ARRAY['error'::"text", 'timeout'::"text", 'rate_limit'::"text", 'fallback'::"text"]))
  GROUP BY ("date_trunc"('1 hour'::"text", "created_at")), "environment", "status", "error_code";


ALTER VIEW "public"."insurance_metrics_error_breakdown" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."insurance_metrics_latency" WITH ("security_invoker"='true') AS
 SELECT "date_trunc"('5 minutes'::"text", "created_at") AS "bucket_5m",
    "environment",
    "percentile_cont"((0.5)::double precision) WITHIN GROUP (ORDER BY (("duration_ms")::double precision)) AS "p50_ms",
    "percentile_cont"((0.95)::double precision) WITHIN GROUP (ORDER BY (("duration_ms")::double precision)) AS "p95_ms",
    "percentile_cont"((0.99)::double precision) WITHIN GROUP (ORDER BY (("duration_ms")::double precision)) AS "p99_ms"
   FROM "public"."insurance_logs"
  WHERE (("duration_ms" IS NOT NULL) AND ("status" = ANY (ARRAY['success'::"text", 'fallback'::"text"])))
  GROUP BY ("date_trunc"('5 minutes'::"text", "created_at")), "environment";


ALTER VIEW "public"."insurance_metrics_latency" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."insurance_metrics_volume" WITH ("security_invoker"='true') AS
 SELECT "date_trunc"('5 minutes'::"text", "created_at") AS "bucket_5m",
    "environment",
    "count"(*) AS "requests_total",
    "count"(*) FILTER (WHERE ("status" = 'success'::"text")) AS "success_count",
    "count"(*) FILTER (WHERE ("status" = 'error'::"text")) AS "error_count",
    "count"(*) FILTER (WHERE ("status" = 'timeout'::"text")) AS "timeout_count",
    "count"(*) FILTER (WHERE ("status" = 'rate_limit'::"text")) AS "rate_limit_count",
    "count"(*) FILTER (WHERE ("status" = 'fallback'::"text")) AS "fallback_count",
        CASE
            WHEN ("count"(*) = 0) THEN (0)::double precision
            ELSE (("count"(*) FILTER (WHERE ("status" <> 'success'::"text")))::double precision / ("count"(*))::double precision)
        END AS "error_rate",
        CASE
            WHEN ("count"(*) = 0) THEN (0)::double precision
            ELSE (("count"(*) FILTER (WHERE ("status" = 'fallback'::"text")))::double precision / ("count"(*))::double precision)
        END AS "fallback_ratio"
   FROM "public"."insurance_logs"
  GROUP BY ("date_trunc"('5 minutes'::"text", "created_at")), "environment";


ALTER VIEW "public"."insurance_metrics_volume" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."load_composition_discount_breakdown" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "composition_id" "uuid" NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "shipper_id" "uuid" NOT NULL,
    "original_quote_price_brl" integer NOT NULL,
    "original_freight_cost_brl" integer NOT NULL,
    "original_margin_brl" integer NOT NULL,
    "original_margin_percent" double precision NOT NULL,
    "max_discount_allowed_brl" integer NOT NULL,
    "discount_offered_brl" integer DEFAULT 0 NOT NULL,
    "discount_percent" double precision DEFAULT 0 NOT NULL,
    "final_quote_price_brl" integer NOT NULL,
    "final_margin_brl" integer NOT NULL,
    "final_margin_percent" double precision NOT NULL,
    "margin_rule_source" "text",
    "minimum_margin_percent_applied" double precision NOT NULL,
    "discount_strategy" "text",
    "is_feasible" boolean DEFAULT true,
    "validation_warnings" "text"[] DEFAULT '{}'::"text"[],
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."load_composition_discount_breakdown" OWNER TO "postgres";


COMMENT ON TABLE "public"."load_composition_discount_breakdown" IS 'Stores calculated discount proposals for each quote in a load composition.
   Respects minimum margin rules while maximizing competitiveness.
   Can be used to generate discount notifications to shippers.';



COMMENT ON COLUMN "public"."load_composition_discount_breakdown"."discount_strategy" IS 'Strategy used to allocate discount:
   - equal_share: divide economy equally
   - proportional_to_original: higher original price = higher discount
   - weighted_by_weight: higher weight = higher discount';



CREATE OR REPLACE VIEW "public"."load_composition_discount_summary" WITH ("security_invoker"='true') AS
 SELECT "composition_id",
    "count"(*) AS "shipper_count",
    "sum"("original_quote_price_brl") AS "total_original_price",
    "sum"("discount_offered_brl") AS "total_discount_offered",
    "sum"("final_quote_price_brl") AS "total_final_price",
    "avg"("final_margin_percent") AS "avg_final_margin_percent",
    "min"("final_margin_percent") AS "min_final_margin_percent",
    "array_agg"(DISTINCT "margin_rule_source") AS "margin_rules_applied"
   FROM "public"."load_composition_discount_breakdown"
  GROUP BY "composition_id";


ALTER VIEW "public"."load_composition_discount_summary" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."load_composition_metrics" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "composition_id" "uuid" NOT NULL,
    "original_total_cost" integer,
    "composed_total_cost" integer,
    "savings_brl" integer,
    "savings_percent" double precision,
    "original_km_total" double precision,
    "composed_km_total" double precision,
    "km_efficiency_percent" double precision,
    "co2_reduction_kg" double precision,
    "created_at" timestamp without time zone DEFAULT "now"()
);


ALTER TABLE "public"."load_composition_metrics" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."load_composition_routings" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "composition_id" "uuid" NOT NULL,
    "route_sequence" integer NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "leg_distance_km" double precision,
    "leg_duration_min" integer,
    "leg_polyline" "text",
    "pickup_window_start" time without time zone,
    "pickup_window_end" time without time zone,
    "estimated_arrival" time without time zone,
    "is_feasible" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT "now"(),
    "toll_centavos" integer DEFAULT 0
);


ALTER TABLE "public"."load_composition_routings" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."load_composition_suggestions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "shipper_id" "uuid" NOT NULL,
    "quote_ids" "uuid"[] NOT NULL,
    "consolidation_score" double precision DEFAULT 0 NOT NULL,
    "estimated_savings_brl" integer DEFAULT 0,
    "distance_increase_percent" double precision DEFAULT 0,
    "is_feasible" boolean DEFAULT true,
    "validation_warnings" "text"[] DEFAULT ARRAY[]::"text"[],
    "status" "text" DEFAULT 'pending'::"text",
    "created_order_id" "uuid",
    "created_by" "uuid" NOT NULL,
    "approved_by" "uuid",
    "approved_at" timestamp without time zone,
    "created_at" timestamp without time zone DEFAULT "now"(),
    "updated_at" timestamp without time zone DEFAULT "now"(),
    "trigger_source" "text" DEFAULT 'batch'::"text" NOT NULL,
    "anchor_quote_id" "uuid",
    "technical_explanation" "text",
    "delta_km_abs" numeric(10,2),
    "delta_km_percent" numeric(5,2),
    "base_km_total" numeric(10,2),
    "composed_km_total" numeric(10,2),
    "route_evaluation_model" "text" DEFAULT 'mock_v1'::"text",
    "suggested_vehicle_type_id" "uuid",
    "suggested_vehicle_type_name" "text",
    "suggested_axes_count" smallint,
    "total_combined_weight_kg" numeric,
    "total_combined_volume_m3" numeric,
    "total_toll_centavos" integer,
    "total_toll_tag_centavos" integer,
    "encoded_polyline" "text",
    "url_mapa_view" "text",
    "webrouter_id_rota" integer,
    CONSTRAINT "load_composition_suggestions_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'approved'::"text", 'rejected'::"text", 'executed'::"text"]))),
    CONSTRAINT "load_composition_suggestions_trigger_source_check" CHECK (("trigger_source" = ANY (ARRAY['batch'::"text", 'on_save'::"text", 'manual'::"text", 'realtime'::"text"])))
);


ALTER TABLE "public"."load_composition_suggestions" OWNER TO "postgres";


COMMENT ON COLUMN "public"."load_composition_suggestions"."trigger_source" IS 'batch | on_save | manual — origin of the analysis';



COMMENT ON COLUMN "public"."load_composition_suggestions"."anchor_quote_id" IS 'The quote that triggered on_save analysis (NULL for batch/manual)';



COMMENT ON COLUMN "public"."load_composition_suggestions"."technical_explanation" IS 'Human-readable explanation of viability for commercial team';



COMMENT ON COLUMN "public"."load_composition_suggestions"."delta_km_abs" IS 'Absolute difference in km between separate and composed routes';



COMMENT ON COLUMN "public"."load_composition_suggestions"."delta_km_percent" IS 'Percentage increase in km for composed vs longest individual route';



COMMENT ON COLUMN "public"."load_composition_suggestions"."base_km_total" IS 'Sum of individual route km (separate trips)';



COMMENT ON COLUMN "public"."load_composition_suggestions"."composed_km_total" IS 'Total km of composed route (single trip with waypoints)';



COMMENT ON COLUMN "public"."load_composition_suggestions"."route_evaluation_model" IS 'mock_v1 | webrouter_v1 — method used for route evaluation';



COMMENT ON COLUMN "public"."load_composition_suggestions"."suggested_vehicle_type_id" IS 'Menor veiculo que comporta o peso total combinado';



COMMENT ON COLUMN "public"."load_composition_suggestions"."suggested_axes_count" IS 'Eixos do veiculo sugerido - impacta pedagio';



COMMENT ON COLUMN "public"."load_composition_suggestions"."total_combined_weight_kg" IS 'Soma peso real (kg) das cotacoes, sem peso cubado';



COMMENT ON COLUMN "public"."load_composition_suggestions"."total_combined_volume_m3" IS 'Soma volume real (m3) das cotacoes';



CREATE OR REPLACE VIEW "public"."load_composition_summary" WITH ("security_invoker"='true') AS
 SELECT "id",
    "shipper_id",
    "quote_ids",
    "consolidation_score",
    "estimated_savings_brl",
    "status",
    "trigger_source",
    "technical_explanation",
    "delta_km_abs",
    "delta_km_percent",
    "base_km_total",
    "composed_km_total",
    "route_evaluation_model",
    ( SELECT "count"(*) AS "count"
           FROM "public"."load_composition_routings"
          WHERE ("load_composition_routings"."composition_id" = "s"."id")) AS "num_stops",
    "created_at",
    "approved_at"
   FROM "public"."load_composition_suggestions" "s"
  ORDER BY "created_at" DESC;


ALTER VIEW "public"."load_composition_summary" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."logistics_traffic_rules" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "city" "text" NOT NULL,
    "state" character(2) NOT NULL,
    "organ_name" "text" NOT NULL,
    "full_name" "text",
    "restriction_type" "text",
    "rules_summary" "text",
    "permit_info" "text",
    "source" "text" DEFAULT 'manual'::"text",
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "logistics_traffic_rules_source_check" CHECK (("source" = ANY (ARRAY['manual'::"text", 'ai'::"text", 'notebooklm'::"text"])))
);


ALTER TABLE "public"."logistics_traffic_rules" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ltl_parameters" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "reference_month" "text" NOT NULL,
    "min_freight" numeric DEFAULT 9.28 NOT NULL,
    "min_freight_cargo_limit" numeric DEFAULT 3093.81 NOT NULL,
    "min_tso" numeric DEFAULT 4.64 NOT NULL,
    "gris_percent" numeric DEFAULT 0.30 NOT NULL,
    "gris_high_risk_percent" numeric DEFAULT 0.50 NOT NULL,
    "gris_min" numeric DEFAULT 9.28 NOT NULL,
    "gris_min_cargo_limit" numeric DEFAULT 3093.81 NOT NULL,
    "dispatch_fee" numeric DEFAULT 102.90 NOT NULL,
    "cubage_factor" numeric DEFAULT 300 NOT NULL,
    "correction_factor" numeric DEFAULT 0.7202 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."ltl_parameters" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."market_indices" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "periodo_referencia" "text" NOT NULL,
    "gerado_em" "date" NOT NULL,
    "fonte_url" "text" NOT NULL,
    "inctf_mensal" numeric(8,4),
    "inctf_12meses" numeric(8,4),
    "inctf_ano" numeric(8,4),
    "inctl_mensal" numeric(8,4),
    "inctl_12meses" numeric(8,4),
    "inctl_ano" numeric(8,4),
    "diesel_s10_preco" numeric(6,2),
    "diesel_s10_mensal" numeric(8,4),
    "diesel_s10_12meses" numeric(8,4),
    "diesel_comum_preco" numeric(6,2),
    "diesel_comum_mensal" numeric(8,4),
    "diesel_comum_12meses" numeric(8,4),
    "desp_adm_mensal" numeric(8,4),
    "desp_adm_12meses" numeric(8,4),
    "lotacao_cavalo_12m" numeric(8,4),
    "lotacao_semirreboque_12m" numeric(8,4),
    "lotacao_pneu_12m" numeric(8,4),
    "lotacao_salario_12m" numeric(8,4),
    "reajuste_sugerido_pct" numeric(6,2),
    "alerta_nivel" "text" DEFAULT 'estavel'::"text" NOT NULL,
    "resumo_whatsapp" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "market_indices_alerta_nivel_check" CHECK (("alerta_nivel" = ANY (ARRAY['estavel'::"text", 'atencao'::"text", 'urgente'::"text"])))
);


ALTER TABLE "public"."market_indices" OWNER TO "postgres";


COMMENT ON TABLE "public"."market_indices" IS 'Índices NTC de custo de transporte. Fonte: portalntc.org.br. Atualizado mensalmente.';



CREATE TABLE IF NOT EXISTS "public"."mirofish_monthly_revenue" (
    "id" integer NOT NULL,
    "mes" "text" NOT NULL,
    "ano_mes" "date" NOT NULL,
    "valor" numeric(12,2) NOT NULL,
    "ctes" integer NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."mirofish_monthly_revenue" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."mirofish_monthly_revenue_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."mirofish_monthly_revenue_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."mirofish_monthly_revenue_id_seq" OWNED BY "public"."mirofish_monthly_revenue"."id";



CREATE TABLE IF NOT EXISTS "public"."mirofish_recommendations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "report_id" "uuid" NOT NULL,
    "action" "text" NOT NULL,
    "priority" "text" DEFAULT 'medium'::"text",
    "target_routes" "text"[],
    "status" "text" DEFAULT 'pending'::"text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "mirofish_recommendations_priority_check" CHECK (("priority" = ANY (ARRAY['low'::"text", 'medium'::"text", 'high'::"text"]))),
    CONSTRAINT "mirofish_recommendations_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'in_progress'::"text", 'done'::"text", 'dismissed'::"text"])))
);


ALTER TABLE "public"."mirofish_recommendations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."mirofish_reports" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "mirofish_report_id" "text" NOT NULL,
    "simulation_id" "text" NOT NULL,
    "title" "text",
    "generated_at" timestamp with time zone,
    "synced_at" timestamp with time zone DEFAULT "now"(),
    "raw_insights" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "period_type" "text",
    "period_start" "date",
    "period_end" "date",
    "status" "text" DEFAULT 'completed'::"text",
    "summary" "text",
    "sections" "jsonb",
    "simulation_requirement" "text",
    "agents_count" integer,
    "completed_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "error" "text",
    CONSTRAINT "mirofish_reports_period_type_check" CHECK (("period_type" = ANY (ARRAY['historical'::"text", 'forecast'::"text"])))
);


ALTER TABLE "public"."mirofish_reports" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."mirofish_route_insights" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "report_id" "uuid" NOT NULL,
    "route" "text" NOT NULL,
    "avg_ticket" numeric,
    "volume_ctes" integer,
    "revenue" numeric,
    "avg_weight_kg" numeric,
    "ntc_impact" numeric,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."mirofish_route_insights" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."mirofish_shipper_insights" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "report_id" "uuid" NOT NULL,
    "shipper_name" "text" NOT NULL,
    "shipper_id" "uuid",
    "ctes" integer,
    "revenue" numeric,
    "avg_ticket" numeric,
    "routes_count" integer,
    "churn_risk" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "mirofish_shipper_insights_churn_risk_check" CHECK (("churn_risk" = ANY (ARRAY['low'::"text", 'medium'::"text", 'high'::"text"])))
);


ALTER TABLE "public"."mirofish_shipper_insights" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."news_items" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "title" "text" NOT NULL,
    "summary" "text",
    "source_type" "text" DEFAULT 'manual'::"text" NOT NULL,
    "source_name" "text",
    "source_url" "text",
    "relevance_score" numeric(3,1) DEFAULT 5.0,
    "tags" "text"[] DEFAULT '{}'::"text"[],
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."news_items" OWNER TO "postgres";


COMMENT ON TABLE "public"."news_items" IS 'Noticias e atualizações do setor de logística e transporte com impacto em precificação.';



CREATE TABLE IF NOT EXISTS "public"."notification_logs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "template_key" "text" NOT NULL,
    "channel" "text" NOT NULL,
    "recipient_email" "text",
    "recipient_phone" "text",
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "external_id" "text",
    "error_message" "text",
    "entity_type" "text",
    "entity_id" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "sent_at" timestamp with time zone
);


ALTER TABLE "public"."notification_logs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."notification_queue" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "template" "text" NOT NULL,
    "channel" "text" DEFAULT 'both'::"text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "external_id" "text",
    "error_message" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "sent_at" timestamp with time zone
);


ALTER TABLE "public"."notification_queue" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."notification_templates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "key" "text" NOT NULL,
    "channel" "text" DEFAULT 'email'::"text" NOT NULL,
    "subject_template" "text",
    "body_template" "text" NOT NULL,
    "html_template" "text",
    "active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "meta_template_name" "text",
    "meta_language_code" "text" DEFAULT 'pt_BR'::"text",
    "meta_category" "text" DEFAULT 'UTILITY'::"text",
    "meta_variables" "jsonb" DEFAULT '[]'::"jsonb",
    "is_meta_approved" boolean DEFAULT false
);


ALTER TABLE "public"."notification_templates" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ntc_articles_seen" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "url" "text" NOT NULL,
    "titulo" "text" NOT NULL,
    "data_pub" "text",
    "categoria" "text",
    "motivo_relevancia" "text",
    "tipo_indice" "text",
    "periodo_referencia" "text",
    "resumo_inferido" "text",
    "precisa_insercao_manual" boolean DEFAULT true,
    "inserido_em" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."ntc_articles_seen" OWNER TO "postgres";


COMMENT ON TABLE "public"."ntc_articles_seen" IS 'Log de artigos NTC detectados pelo monitor. precisa_insercao_manual=true indica que aguarda PDF do usuário.';



CREATE TABLE IF NOT EXISTS "public"."ntc_cost_indices" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "index_type" "text" NOT NULL,
    "period" "date" NOT NULL,
    "distance_km" integer,
    "pickup_km" integer,
    "index_value" numeric NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "ntc_cost_indices_index_type_check" CHECK (("index_type" = ANY (ARRAY['INCTL'::"text", 'INCTL_INDEX'::"text", 'INCTF'::"text", 'INCTF_DETAIL'::"text"])))
);


ALTER TABLE "public"."ntc_cost_indices" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ntc_fuel_reference" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "reference_month" "date" NOT NULL,
    "diesel_price_liter" numeric NOT NULL,
    "diesel_price_sp" numeric,
    "diesel_price_rj" numeric,
    "diesel_price_mg" numeric,
    "diesel_price_pr" numeric,
    "monthly_variation_pct" numeric,
    "annual_variation_pct" numeric,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."ntc_fuel_reference" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ntc_scrape_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "scraped_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "status" "text" NOT NULL,
    "periodo_referencia" "text",
    "gerado_em" "date",
    "is_new_period" boolean DEFAULT false,
    "dia_semana" integer,
    "hora_utc" integer,
    "hora_brt" integer,
    "http_status" integer,
    "error_message" "text",
    "response_preview" "text",
    "duration_ms" integer,
    CONSTRAINT "ntc_scrape_log_status_check" CHECK (("status" = ANY (ARRAY['success'::"text", 'no_new_data'::"text", 'parse_error'::"text", 'network_error'::"text", 'timeout'::"text"])))
);


ALTER TABLE "public"."ntc_scrape_log" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."occurrences" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid" NOT NULL,
    "description" "text" NOT NULL,
    "severity" "public"."occurrence_severity" DEFAULT 'baixa'::"public"."occurrence_severity" NOT NULL,
    "resolved_at" timestamp with time zone,
    "resolved_by" "uuid",
    "created_by" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."occurrences" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."operational_reports" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "report_date" "date" NOT NULL,
    "report_type" "text" DEFAULT 'daily'::"text" NOT NULL,
    "data" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "analysis" "jsonb",
    "summary_text" "text",
    "sent_via" "text",
    "sent_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."operational_reports" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."order_documents" WITH ("security_invoker"='true') AS
 SELECT "id",
    "order_id",
    COALESCE(NULLIF("validation_status", ''::"text"), 'pending'::"text") AS "status",
    "type",
    "file_name",
    "created_at"
   FROM "public"."documents" "d"
  WHERE ("order_id" IS NOT NULL);


ALTER VIEW "public"."order_documents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."trip_orders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "trip_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "apportion_key" "text" DEFAULT 'revenue'::"text" NOT NULL,
    "apportion_factor" numeric DEFAULT 0 NOT NULL,
    "manual_percent" numeric,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "trip_orders_apportion_key_check" CHECK (("apportion_key" = ANY (ARRAY['revenue'::"text", 'weight'::"text", 'volume'::"text", 'km'::"text", 'equal'::"text", 'manual'::"text"])))
);


ALTER TABLE "public"."trip_orders" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."orders_rs_per_km" WITH ("security_invoker"='true') AS
 SELECT "o"."id" AS "order_id",
    "o"."os_number",
    "o"."client_name",
    "o"."origin",
    "o"."destination",
    "o"."km_distance",
    "o"."carreteiro_real",
    ("o"."carreteiro_real" / NULLIF("o"."km_distance", (0)::numeric)) AS "rs_per_km",
    "o"."vehicle_type_id",
    "vt"."name" AS "vehicle_type_name",
    "o"."created_at" AS "order_date",
        CASE
            WHEN (("o"."trip_id" IS NOT NULL) OR (EXISTS ( SELECT 1
               FROM "public"."trip_orders" "to2"
              WHERE ("to2"."order_id" = "o"."id")))) THEN 'VG'::"text"
            ELSE 'OS'::"text"
        END AS "tipo",
    COALESCE("o"."trip_id", ( SELECT "to2"."trip_id"
           FROM "public"."trip_orders" "to2"
          WHERE ("to2"."order_id" = "o"."id")
         LIMIT 1)) AS "trip_id"
   FROM ("public"."orders" "o"
     LEFT JOIN "public"."vehicle_types" "vt" ON (("vt"."id" = "o"."vehicle_type_id")))
  WHERE (("o"."km_distance" IS NOT NULL) AND ("o"."km_distance" > (0)::numeric) AND ("o"."carreteiro_real" IS NOT NULL) AND ("o"."carreteiro_real" > (0)::numeric));


ALTER VIEW "public"."orders_rs_per_km" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."owners" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "cpf_cnpj" "text",
    "rg" "text",
    "rg_emitter" "text",
    "phone" "text",
    "email" "text",
    "address" "text",
    "city" "text",
    "state" character varying(2),
    "zip_code" character varying(10),
    "notes" "text",
    "active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "cpf_cnpj_mask" "text",
    "zip_code_mask" "text"
);


ALTER TABLE "public"."owners" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."partner_quotes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "shipper_id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "origin_cep" "text" NOT NULL,
    "origin_city" "text" NOT NULL,
    "destination_cep" "text" NOT NULL,
    "destination_city" "text" NOT NULL,
    "destination_state" "text",
    "weight_kg" numeric NOT NULL,
    "cargo_value" numeric NOT NULL,
    "modality" "text" NOT NULL,
    "vehicle_type" "text",
    "freight_value" numeric,
    "km_distance" numeric,
    "toll_value" numeric,
    "client_name" "text",
    "client_cnpj" "text",
    "client_email" "text",
    "client_phone" "text",
    "status" "text" DEFAULT 'quoted'::"text",
    "notes" "text",
    "pricing_breakdown" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."partner_quotes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."partner_shippers" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "slug" "text" NOT NULL,
    "origin_cep" "text" NOT NULL,
    "origin_city" "text" NOT NULL,
    "logo_url" "text",
    "primary_color" "text" DEFAULT '#FF6B35'::"text",
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."partner_shippers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."partner_tokens" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "partner_slug" "text" NOT NULL,
    "partner_name" "text" NOT NULL,
    "token" "text" NOT NULL,
    "origin_cep" "text" NOT NULL,
    "origin_city" "text" NOT NULL,
    "logo_url" "text",
    "primary_color" "text" DEFAULT '#ff6b35'::"text",
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."partner_tokens" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."partner_users" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "shipper_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "email" "text" NOT NULL,
    "password_hash" "text" NOT NULL,
    "is_active" boolean DEFAULT true,
    "last_login" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."partner_users" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."petrobras_diesel_prices" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "uf" "text" NOT NULL,
    "preco_medio" numeric(6,3) NOT NULL,
    "parcela_petrobras" numeric(6,3),
    "parcela_impostos_federais" numeric(6,3),
    "parcela_icms" numeric(6,3),
    "parcela_biodiesel" numeric(6,3),
    "parcela_distribuicao" numeric(6,3),
    "periodo_coleta" "text",
    "fetched_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "source" "text" DEFAULT 'api'::"text" NOT NULL
);


ALTER TABLE "public"."petrobras_diesel_prices" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."price_table_rows" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "price_table_id" "uuid" NOT NULL,
    "km_from" numeric NOT NULL,
    "km_to" numeric NOT NULL,
    "cost_per_ton" numeric,
    "cost_per_kg" numeric,
    "cost_value_percent" numeric,
    "gris_percent" numeric,
    "tso_percent" numeric,
    "toll_percent" numeric,
    "ad_valorem_percent" numeric,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"(),
    "weight_rate_10" numeric,
    "weight_rate_20" numeric,
    "weight_rate_30" numeric,
    "weight_rate_50" numeric,
    "weight_rate_70" numeric,
    "weight_rate_100" numeric,
    "weight_rate_150" numeric,
    "weight_rate_200" numeric,
    "weight_rate_above_200" numeric,
    CONSTRAINT "price_table_rows_km_from_check" CHECK (("km_from" >= (0)::numeric)),
    CONSTRAINT "price_table_rows_km_range_check" CHECK (("km_to" >= "km_from"))
);


ALTER TABLE "public"."price_table_rows" OWNER TO "postgres";


COMMENT ON TABLE "public"."price_table_rows" IS 'Linhas de preço por faixa de KM';



COMMENT ON COLUMN "public"."price_table_rows"."km_from" IS 'KM inicial da faixa (inclusive)';



COMMENT ON COLUMN "public"."price_table_rows"."km_to" IS 'KM final da faixa (inclusive)';



CREATE TABLE IF NOT EXISTS "public"."price_tables" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "modality" "text" NOT NULL,
    "active" boolean DEFAULT false NOT NULL,
    "valid_from" "date",
    "valid_until" "date",
    "version" integer DEFAULT 1 NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"(),
    "ad_valorem_lotacao_percent" numeric(6,4),
    CONSTRAINT "price_tables_check" CHECK ((("valid_until" IS NULL) OR ("valid_from" IS NULL) OR ("valid_until" >= "valid_from"))),
    CONSTRAINT "price_tables_modality_check" CHECK (("modality" = ANY (ARRAY['lotacao'::"text", 'fracionado'::"text"])))
);


ALTER TABLE "public"."price_tables" OWNER TO "postgres";


COMMENT ON TABLE "public"."price_tables" IS 'Tabelas de preço de frete (Lotação/Fracionado)';



COMMENT ON COLUMN "public"."price_tables"."modality" IS 'Modalidade: lotacao ou fracionado';



COMMENT ON COLUMN "public"."price_tables"."active" IS 'Se true, é a tabela vigente para a modalidade';



COMMENT ON COLUMN "public"."price_tables"."ad_valorem_lotacao_percent" IS 'Percentual ad valorem (%) para lotação nesta tabela. Substitui GRIS+TSO. NULL = herdar de pricing_rules_config.';



CREATE TABLE IF NOT EXISTS "public"."pricing_parameters" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "key" "text" NOT NULL,
    "value" numeric NOT NULL,
    "unit" "text",
    "description" "text",
    "valid_from" "date",
    "valid_until" "date",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"()
);


ALTER TABLE "public"."pricing_parameters" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."pricing_route_overrides" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "origin_uf" character(2) NOT NULL,
    "destination_uf" character(2) NOT NULL,
    "profit_margin_percent" numeric(5,2),
    "is_active" boolean DEFAULT true NOT NULL,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "origin_city" "text",
    "destination_city" "text",
    "modality" "text" DEFAULT 'lotacao'::"text",
    "override_type" "text" DEFAULT 'fixed_cost'::"text",
    "override_value" numeric(12,2),
    "description" "text",
    "cargo_type" "text" DEFAULT 'geral'::"text",
    CONSTRAINT "pricing_route_overrides_modality_check" CHECK (("modality" = ANY (ARRAY['fracionado'::"text", 'lotacao'::"text", 'ambos'::"text"]))),
    CONSTRAINT "pricing_route_overrides_override_type_check" CHECK (("override_type" = ANY (ARRAY['fixed_cost'::"text", 'over_percent'::"text"])))
);


ALTER TABLE "public"."pricing_route_overrides" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."pricing_rules_config" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "key" "text" NOT NULL,
    "label" "text" NOT NULL,
    "category" "public"."pricing_rule_category" NOT NULL,
    "value_type" "public"."pricing_rule_value_type" NOT NULL,
    "value" numeric(15,4) NOT NULL,
    "min_value" numeric(15,4),
    "max_value" numeric(15,4),
    "vehicle_type_id" "uuid",
    "is_active" boolean DEFAULT true,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."pricing_rules_config" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."processes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "nome" character varying(255) NOT NULL,
    "descricao" "text",
    "dominio" character varying(100),
    "owner" character varying(255),
    "status" character varying(20) DEFAULT 'ativo'::character varying,
    "criado_em" timestamp with time zone DEFAULT "now"(),
    "atualizado_em" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."processes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."product_dimensions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "supplier" "text" DEFAULT 'BUCKLER'::"text" NOT NULL,
    "codigo_base" "text" NOT NULL,
    "box" "text",
    "descricao" "text",
    "comprimento_m" numeric(10,4) NOT NULL,
    "largura_m" numeric(10,4) NOT NULL,
    "altura_m" numeric(10,4) NOT NULL,
    "volume_m3" numeric(10,6) GENERATED ALWAYS AS ((("comprimento_m" * "largura_m") * "altura_m")) STORED,
    "peso_kg" numeric(10,4) NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."product_dimensions" OWNER TO "postgres";


COMMENT ON TABLE "public"."product_dimensions" IS 'Base de medidas de produtos por fornecedor. Codigos com multiplas caixas (-A, -B, etc) devem ser somados para obter volume e peso total do produto.';



CREATE TABLE IF NOT EXISTS "public"."profiles" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid",
    "full_name" "text" NOT NULL,
    "email" "text",
    "phone" "text",
    "avatar_url" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "perfil" "public"."user_profile" DEFAULT 'operacional'::"public"."user_profile"
);


ALTER TABLE "public"."profiles" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."quote_contracts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "version" integer DEFAULT 1 NOT NULL,
    "pdf_storage_path" "text" NOT NULL,
    "pdf_file_name" "text",
    "pdf_size_bytes" bigint,
    "generated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "generated_by" "uuid",
    "signature_status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "signature_provider" "text",
    "signature_envelope_id" "text",
    "signature_metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "signed_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "quote_contracts_signature_status_check" CHECK (("signature_status" = ANY (ARRAY['pending'::"text", 'sent'::"text", 'signed'::"text", 'rejected'::"text", 'expired'::"text"])))
);


ALTER TABLE "public"."quote_contracts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."quote_route_stops" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "quote_id" "uuid" NOT NULL,
    "sequence" integer DEFAULT 0 NOT NULL,
    "stop_type" "public"."route_stop_type" DEFAULT 'stop'::"public"."route_stop_type" NOT NULL,
    "cnpj" "text",
    "name" "text",
    "cep" "text",
    "city_uf" "text",
    "label" "text",
    "planned_km_from_prev" numeric(10,2),
    "metadata" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."quote_route_stops" OWNER TO "postgres";


COMMENT ON TABLE "public"."quote_route_stops" IS 'Paradas do roteiro da cotação: origem (0), paradas intermediárias (1..n-1), destino (n). Permite múltiplos destinatários no mesmo frete.';



CREATE TABLE IF NOT EXISTS "public"."regulatory_updates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "source" "text" NOT NULL,
    "title" "text" NOT NULL,
    "url" "text",
    "summary" "text",
    "relevance_score" integer,
    "ai_analysis" "jsonb",
    "action_required" boolean DEFAULT false NOT NULL,
    "notified" boolean DEFAULT false NOT NULL,
    "published_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "source_url" "text",
    "source_name" "text",
    "impact_areas" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "recommendation" "text",
    "analysis" "jsonb",
    CONSTRAINT "regulatory_updates_relevance_score_check" CHECK ((("relevance_score" >= 0) AND ("relevance_score" <= 10)))
);


ALTER TABLE "public"."regulatory_updates" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."risk_costs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid",
    "trip_id" "uuid",
    "service_id" "uuid" NOT NULL,
    "service_code" "text" NOT NULL,
    "unit_cost" numeric(10,2) NOT NULL,
    "quantity" integer DEFAULT 1,
    "total_cost" numeric(10,2) NOT NULL,
    "scope" "text" NOT NULL,
    "apportioned" boolean DEFAULT false,
    "evaluation_id" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."risk_costs" OWNER TO "postgres";


COMMENT ON TABLE "public"."risk_costs" IS 'Custos reais de risco por OS/trip (Buonny, seguro efetivo)';



CREATE TABLE IF NOT EXISTS "public"."risk_evaluations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "entity_type" "text" NOT NULL,
    "entity_id" "uuid" NOT NULL,
    "policy_id" "uuid",
    "criticality" "public"."risk_criticality" DEFAULT 'LOW'::"public"."risk_criticality" NOT NULL,
    "status" "public"."risk_evaluation_status" DEFAULT 'pending'::"public"."risk_evaluation_status" NOT NULL,
    "cargo_value_evaluated" numeric(15,2),
    "requirements" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "requirements_met" "jsonb" DEFAULT '{}'::"jsonb",
    "route_municipalities" "text"[],
    "policy_rules_applied" "uuid"[],
    "evaluation_notes" "text",
    "evaluated_by" "uuid",
    "evaluated_at" timestamp with time zone,
    "approval_request_id" "uuid",
    "expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."risk_evaluations" OWNER TO "postgres";


COMMENT ON TABLE "public"."risk_evaluations" IS 'Avaliacao de risco por OS ou trip, com criticidade e exigencias';



CREATE TABLE IF NOT EXISTS "public"."risk_evidence" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "evaluation_id" "uuid" NOT NULL,
    "evidence_type" "text" NOT NULL,
    "document_id" "uuid",
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "status" "text" DEFAULT 'valid'::"text",
    "expires_at" timestamp with time zone,
    "notes" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."risk_evidence" OWNER TO "postgres";


COMMENT ON TABLE "public"."risk_evidence" IS 'Evidencias vinculadas a uma avaliacao de risco';



CREATE TABLE IF NOT EXISTS "public"."risk_policies" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "code" "text" NOT NULL,
    "name" "text" NOT NULL,
    "policy_type" "text" NOT NULL,
    "insurer" "text",
    "endorsement" "text",
    "risk_manager" "text",
    "valid_from" "date" NOT NULL,
    "valid_until" "date",
    "coverage_limit" numeric(15,2),
    "deductible" numeric(15,2),
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "document_url" "text",
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "created_by" "uuid"
);


ALTER TABLE "public"."risk_policies" OWNER TO "postgres";


COMMENT ON TABLE "public"."risk_policies" IS 'Apolices de seguro e suas regras-mestre';



CREATE TABLE IF NOT EXISTS "public"."risk_policy_rules" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "policy_id" "uuid" NOT NULL,
    "trigger_type" "text" NOT NULL,
    "trigger_config" "jsonb" NOT NULL,
    "criticality" "public"."risk_criticality" NOT NULL,
    "criticality_boost" integer DEFAULT 0,
    "requirements" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "description" "text",
    "sort_order" integer DEFAULT 0,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."risk_policy_rules" OWNER TO "postgres";


COMMENT ON TABLE "public"."risk_policy_rules" IS 'Regras de criticidade vinculadas a uma apolice';



CREATE TABLE IF NOT EXISTS "public"."risk_services_catalog" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "code" "text" NOT NULL,
    "name" "text" NOT NULL,
    "provider" "text" NOT NULL,
    "unit_cost" numeric(10,2) NOT NULL,
    "cost_type" "text" DEFAULT 'fixed'::"text" NOT NULL,
    "scope" "text" DEFAULT 'per_trip'::"text" NOT NULL,
    "required_when" "text",
    "validity_days" integer,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "is_active" boolean DEFAULT true,
    "valid_from" "date" DEFAULT CURRENT_DATE,
    "valid_until" "date",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."risk_services_catalog" OWNER TO "postgres";


COMMENT ON TABLE "public"."risk_services_catalog" IS 'Catalogo de servicos de gerenciamento de risco com custos';



CREATE TABLE IF NOT EXISTS "public"."route_metrics_config" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "origin_uf" "text" NOT NULL,
    "destination_uf" "text" NOT NULL,
    "vehicle_type_id" "uuid",
    "is_active" boolean DEFAULT true NOT NULL,
    "target_rs_per_km" numeric,
    "min_rs_per_km" numeric,
    "max_rs_per_km" numeric,
    "notes" "text",
    CONSTRAINT "route_metrics_config_destination_uf_check" CHECK (("destination_uf" ~ '^[A-Z]{2}$'::"text")),
    CONSTRAINT "route_metrics_config_origin_uf_check" CHECK (("origin_uf" ~ '^[A-Z]{2}$'::"text"))
);


ALTER TABLE "public"."route_metrics_config" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."settings" (
    "key" "text" NOT NULL,
    "value" "text" NOT NULL,
    "description" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."settings" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."shippers" (
    "name" "text" NOT NULL,
    "cnpj" character varying(18),
    "email" "text",
    "phone" "text",
    "address" "text",
    "city" "text",
    "state" "text",
    "notes" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "zip_code" "text",
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "cpf" "text",
    "contact_name" "text",
    "contact_context" "text",
    "cep_origem_override" "text",
    "address_number" "text",
    "address_complement" "text",
    "address_neighborhood" "text",
    "trade_name" "text",
    "legal_nature" "text",
    "legal_nature_code" "text",
    "company_size" "text",
    "cnae_main_code" "text",
    "cnae_main_description" "text",
    "cnaes_secondary" "jsonb" DEFAULT '[]'::"jsonb",
    "opening_date" "date",
    "registration_status" "text",
    "registration_status_date" "date",
    "registration_status_reason" "text",
    "efr" "text",
    "share_capital" numeric(15,2),
    "partners" "jsonb" DEFAULT '[]'::"jsonb",
    "cnpj_lookup_at" timestamp with time zone,
    "state_registration" "text",
    "legal_representative_name" "text",
    "legal_representative_cpf" "text",
    "legal_representative_role" "text"
);


ALTER TABLE "public"."shippers" OWNER TO "postgres";


COMMENT ON COLUMN "public"."shippers"."cpf" IS 'CPF do responsável/representante (formato 000.000.000-00)';



COMMENT ON COLUMN "public"."shippers"."cep_origem_override" IS 'CEP do depósito/CD de onde a mercadoria é despachada. Quando preenchido, sobrescreve o zip_code para cálculo de frete de origem.';



COMMENT ON COLUMN "public"."shippers"."address_number" IS 'Numero do endereco (complementa o campo address)';



COMMENT ON COLUMN "public"."shippers"."address_complement" IS 'Complemento do endereco';



COMMENT ON COLUMN "public"."shippers"."address_neighborhood" IS 'Bairro';



COMMENT ON COLUMN "public"."shippers"."partners" IS 'Quadro societario QSA: [{name, role, role_code, document, entry_date, country, age_range}]';



CREATE TABLE IF NOT EXISTS "public"."sipoc_customers" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sipoc_map_id" "uuid" NOT NULL,
    "nome" character varying(255) NOT NULL,
    "tipo" character varying(30) NOT NULL,
    "referencia" character varying(255),
    "descricao" "text",
    "ordem" integer DEFAULT 0,
    CONSTRAINT "sipoc_customers_tipo_check" CHECK ((("tipo")::"text" = ANY ((ARRAY['etapa_seguinte'::character varying, 'humano'::character varying, 'sistema_externo'::character varying, 'cliente_final'::character varying])::"text"[])))
);


ALTER TABLE "public"."sipoc_customers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."sipoc_decisions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sipoc_map_id" "uuid" NOT NULL,
    "condicao" "text" NOT NULL,
    "acao" "text" NOT NULL,
    "proximo_step_id" character varying(50),
    "prioridade" integer DEFAULT 1
);


ALTER TABLE "public"."sipoc_decisions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."sipoc_inputs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sipoc_map_id" "uuid" NOT NULL,
    "supplier_id" "uuid",
    "nome" character varying(255) NOT NULL,
    "tipo" character varying(30) NOT NULL,
    "formato" character varying(100),
    "obrigatorio" boolean DEFAULT true,
    "validacao" "text",
    "ordem" integer DEFAULT 0,
    CONSTRAINT "sipoc_inputs_tipo_check" CHECK ((("tipo")::"text" = ANY ((ARRAY['arquivo'::character varying, 'dado_estruturado'::character varying, 'evento'::character varying, 'confirmacao_humana'::character varying])::"text"[])))
);


ALTER TABLE "public"."sipoc_inputs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."sipoc_maps" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "process_id" "uuid" NOT NULL,
    "step_id" character varying(50) NOT NULL,
    "step_nome" character varying(255) NOT NULL,
    "step_descricao" "text",
    "version" integer DEFAULT 1,
    "status" character varying(20) DEFAULT 'rascunho'::character varying,
    "responsavel" character varying(20) NOT NULL,
    "ferramentas" "jsonb" DEFAULT '[]'::"jsonb",
    "sla_horas" numeric,
    "alertas" "jsonb" DEFAULT '[]'::"jsonb",
    "proximo_steps" "jsonb" DEFAULT '[]'::"jsonb",
    "criado_por" character varying(255),
    "criado_em" timestamp with time zone DEFAULT "now"(),
    "atualizado_em" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "sipoc_maps_responsavel_check" CHECK ((("responsavel")::"text" = ANY ((ARRAY['agente'::character varying, 'humano'::character varying, 'sistema'::character varying])::"text"[]))),
    CONSTRAINT "sipoc_maps_status_check" CHECK ((("status")::"text" = ANY ((ARRAY['rascunho'::character varying, 'validado'::character varying, 'ativo'::character varying, 'obsoleto'::character varying])::"text"[])))
);


ALTER TABLE "public"."sipoc_maps" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."sipoc_outputs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sipoc_map_id" "uuid" NOT NULL,
    "nome" character varying(255) NOT NULL,
    "tipo" character varying(30) NOT NULL,
    "formato" character varying(100),
    "destino" character varying(255),
    "condicao" "text",
    "ordem" integer DEFAULT 0,
    CONSTRAINT "sipoc_outputs_tipo_check" CHECK ((("tipo")::"text" = ANY ((ARRAY['arquivo'::character varying, 'dado_estruturado'::character varying, 'notificacao'::character varying, 'confirmacao'::character varying])::"text"[])))
);


ALTER TABLE "public"."sipoc_outputs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."sipoc_suppliers" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "sipoc_map_id" "uuid" NOT NULL,
    "nome" character varying(255) NOT NULL,
    "tipo" character varying(30) NOT NULL,
    "referencia" character varying(255),
    "descricao" "text",
    "ordem" integer DEFAULT 0,
    CONSTRAINT "sipoc_suppliers_tipo_check" CHECK ((("tipo")::"text" = ANY ((ARRAY['agente'::character varying, 'humano'::character varying, 'sistema_externo'::character varying, 'etapa_anterior'::character varying])::"text"[])))
);


ALTER TABLE "public"."sipoc_suppliers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."skill_executions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "skill_id" character varying(100) DEFAULT 'sipoc_analyzer'::character varying NOT NULL,
    "skill_version" character varying(20),
    "agent_id" character varying(255),
    "sipoc_map_id" "uuid",
    "payload_entrada" "jsonb",
    "resultado" "jsonb",
    "sucesso" boolean,
    "erros" "jsonb" DEFAULT '[]'::"jsonb",
    "avisos" "jsonb" DEFAULT '[]'::"jsonb",
    "duracao_ms" integer,
    "executado_em" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."skill_executions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tac_rates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "reference_date" "date" NOT NULL,
    "diesel_price_base" numeric NOT NULL,
    "diesel_price_current" numeric NOT NULL,
    "variation_percent" numeric GENERATED ALWAYS AS (
CASE
    WHEN ("diesel_price_base" > (0)::numeric) THEN "round"(((("diesel_price_current" - "diesel_price_base") / "diesel_price_base") * (100)::numeric), 2)
    ELSE (0)::numeric
END) STORED,
    "adjustment_percent" numeric DEFAULT 0 NOT NULL,
    "source_description" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"()
);


ALTER TABLE "public"."tac_rates" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tasks" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "meta" "jsonb" NOT NULL,
    "cron_expr" "text",
    "active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "last_run_at" timestamp with time zone
);


ALTER TABLE "public"."tasks" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."toll_routes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "origin_state" character(2) NOT NULL,
    "origin_city" "text",
    "destination_state" character(2) NOT NULL,
    "destination_city" "text",
    "vehicle_type_id" "uuid",
    "toll_value" numeric NOT NULL,
    "distance_km" integer,
    "via_description" "text",
    "valid_from" "date",
    "valid_until" "date",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"()
);


ALTER TABLE "public"."toll_routes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."trip_cost_items" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "trip_id" "uuid" NOT NULL,
    "order_id" "uuid",
    "scope" "text" NOT NULL,
    "category" "text" NOT NULL,
    "description" "text",
    "amount" numeric DEFAULT 0 NOT NULL,
    "currency" "text" DEFAULT 'BRL'::"text" NOT NULL,
    "source" "text" DEFAULT 'manual'::"text" NOT NULL,
    "reference_key" "text",
    "reference_id" "uuid",
    "idempotency_key" "text",
    "is_frozen" boolean DEFAULT false NOT NULL,
    "manually_edited_at" timestamp with time zone,
    "manually_edited_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "ck_scope_order_consistency" CHECK (((("scope" = 'TRIP'::"text") AND ("order_id" IS NULL)) OR (("scope" = 'OS'::"text") AND ("order_id" IS NOT NULL)))),
    CONSTRAINT "trip_cost_items_category_check" CHECK (("category" = ANY (ARRAY['pedagio'::"text", 'carreteiro'::"text", 'descarga'::"text", 'carga'::"text", 'das'::"text", 'icms'::"text", 'gris'::"text", 'tso'::"text", 'seguro'::"text", 'overhead'::"text", 'combustivel'::"text", 'diaria'::"text", 'manutencao'::"text", 'outros'::"text", 'vpo_pedagio'::"text"]))),
    CONSTRAINT "trip_cost_items_scope_check" CHECK (("scope" = ANY (ARRAY['TRIP'::"text", 'OS'::"text"]))),
    CONSTRAINT "trip_cost_items_source_check" CHECK (("source" = ANY (ARRAY['breakdown'::"text", 'manual'::"text", 'api'::"text", 'xml'::"text"])))
);


ALTER TABLE "public"."trip_cost_items" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."trip_financial_summary" WITH ("security_invoker"='true') AS
 SELECT "id" AS "trip_id",
    "trip_number",
    "vehicle_plate",
    "driver_id",
    "status_operational",
    "financial_status",
    (( SELECT "count"(*) AS "count"
           FROM "public"."trip_orders" "to2"
          WHERE ("to2"."trip_id" = "t"."id")))::integer AS "orders_count",
    COALESCE(( SELECT "sum"("o"."value") AS "sum"
           FROM ("public"."trip_orders" "to2"
             JOIN "public"."orders" "o" ON (("o"."id" = "to2"."order_id")))
          WHERE ("to2"."trip_id" = "t"."id")), (0)::numeric) AS "receita_bruta",
    COALESCE(( SELECT "sum"("trip_cost_items"."amount") AS "sum"
           FROM "public"."trip_cost_items"
          WHERE (("trip_cost_items"."trip_id" = "t"."id") AND ("trip_cost_items"."scope" = 'TRIP'::"text"))), (0)::numeric) AS "custos_trip",
    COALESCE(( SELECT "sum"("trip_cost_items"."amount") AS "sum"
           FROM "public"."trip_cost_items"
          WHERE (("trip_cost_items"."trip_id" = "t"."id") AND ("trip_cost_items"."scope" = 'OS'::"text"))), (0)::numeric) AS "custos_os",
    COALESCE(( SELECT "sum"("trip_cost_items"."amount") AS "sum"
           FROM "public"."trip_cost_items"
          WHERE ("trip_cost_items"."trip_id" = "t"."id")), (0)::numeric) AS "custos_diretos",
    (COALESCE(( SELECT "sum"("o"."value") AS "sum"
           FROM ("public"."trip_orders" "to2"
             JOIN "public"."orders" "o" ON (("o"."id" = "to2"."order_id")))
          WHERE ("to2"."trip_id" = "t"."id")), (0)::numeric) - COALESCE(( SELECT "sum"("trip_cost_items"."amount") AS "sum"
           FROM "public"."trip_cost_items"
          WHERE ("trip_cost_items"."trip_id" = "t"."id")), (0)::numeric)) AS "margem_bruta",
        CASE
            WHEN (( SELECT COALESCE("sum"("o"."value"), (0)::numeric) AS "coalesce"
               FROM ("public"."trip_orders" "to2"
                 JOIN "public"."orders" "o" ON (("o"."id" = "to2"."order_id")))
              WHERE ("to2"."trip_id" = "t"."id")) > (0)::numeric) THEN "round"((((COALESCE(( SELECT "sum"("o"."value") AS "sum"
               FROM ("public"."trip_orders" "to2"
                 JOIN "public"."orders" "o" ON (("o"."id" = "to2"."order_id")))
              WHERE ("to2"."trip_id" = "t"."id")), (0)::numeric) - COALESCE(( SELECT "sum"("trip_cost_items"."amount") AS "sum"
               FROM "public"."trip_cost_items"
              WHERE ("trip_cost_items"."trip_id" = "t"."id")), (0)::numeric)) / ( SELECT "sum"("o"."value") AS "sum"
               FROM ("public"."trip_orders" "to2"
                 JOIN "public"."orders" "o" ON (("o"."id" = "to2"."order_id")))
              WHERE ("to2"."trip_id" = "t"."id"))) * (100)::numeric), 2)
            ELSE NULL::numeric
        END AS "margem_percent"
   FROM "public"."trips" "t";


ALTER VIEW "public"."trip_financial_summary" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."unloading_cost_rates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "code" "text" NOT NULL,
    "unit" "text" DEFAULT 'unidade'::"text" NOT NULL,
    "value" numeric(12,2) DEFAULT 0 NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "valid_from" "date",
    "valid_until" "date",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."unloading_cost_rates" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."user_roles" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "role" "public"."app_role" DEFAULT 'leitura'::"public"."app_role" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."user_roles" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."v_cash_flow_summary" WITH ("security_invoker"='true') AS
 WITH "doc_periods" AS (
         SELECT "fd"."id",
            "fd"."type",
            "fd"."status",
            "fd"."total_amount",
            ("date_trunc"('month'::"text", COALESCE((( SELECT "min"("i"."due_date") AS "min"
                   FROM "public"."financial_installments" "i"
                  WHERE ("i"."financial_document_id" = "fd"."id")))::timestamp with time zone, "fd"."created_at")))::"date" AS "period"
           FROM "public"."financial_documents" "fd"
        ), "installment_sums" AS (
         SELECT "fd"."id",
            "sum"("fi"."amount") FILTER (WHERE ("fi"."status" = 'baixado'::"public"."financial_installment_status")) AS "settled",
            "sum"("fi"."amount") FILTER (WHERE ("fi"."status" = 'pendente'::"public"."financial_installment_status")) AS "pending"
           FROM ("public"."financial_documents" "fd"
             LEFT JOIN "public"."financial_installments" "fi" ON (("fi"."financial_document_id" = "fd"."id")))
          GROUP BY "fd"."id"
        )
 SELECT "dp"."period",
    "dp"."type",
    "dp"."status",
    ("count"(*))::integer AS "doc_count",
    COALESCE("sum"("dp"."total_amount"), (0)::numeric) AS "total_amount",
    COALESCE("sum"("isum"."settled"), (0)::numeric) AS "settled_amount",
    COALESCE("sum"("isum"."pending"), (0)::numeric) AS "pending_amount"
   FROM ("doc_periods" "dp"
     LEFT JOIN "installment_sums" "isum" ON (("isum"."id" = "dp"."id")))
  GROUP BY "dp"."period", "dp"."type", "dp"."status";


ALTER VIEW "public"."v_cash_flow_summary" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."v_quote_order_divergence" WITH ("security_invoker"='true') AS
 SELECT "o"."id" AS "order_id",
    "q"."id" AS "quote_id",
    "o"."os_number",
    "q"."quote_code",
    "o"."client_name",
    "o"."origin",
    "o"."destination",
    COALESCE("q"."value", (0)::numeric) AS "quote_value",
    COALESCE("o"."value", (0)::numeric) AS "order_value",
    (COALESCE("o"."value", (0)::numeric) - COALESCE("q"."value", (0)::numeric)) AS "delta_value",
    "q"."toll_value" AS "quote_toll_value",
    "o"."toll_value" AS "order_toll_value",
    (COALESCE("o"."toll_value", (0)::numeric) - COALESCE("q"."toll_value", (0)::numeric)) AS "delta_toll",
    "q"."km_distance" AS "quote_km",
    "o"."km_distance" AS "order_km",
    (COALESCE("o"."km_distance", (0)::numeric) - COALESCE("q"."km_distance", (0)::numeric)) AS "delta_km",
    "vt_q"."axes_count" AS "quote_axes_count",
    "vt_o"."axes_count" AS "order_axes_count",
    (("vt_q"."axes_count" IS NOT NULL) AND ("vt_o"."axes_count" IS NOT NULL) AND ("vt_q"."axes_count" <> "vt_o"."axes_count")) AS "axes_divergence",
    COALESCE(((("q"."pricing_breakdown" -> 'profitability'::"text") ->> 'margemPercent'::"text"))::numeric, ((("q"."pricing_breakdown" -> 'profitability'::"text") ->> 'margem_percent'::"text"))::numeric, ((("o"."pricing_breakdown" -> 'profitability'::"text") ->> 'margemPercent'::"text"))::numeric, ((("o"."pricing_breakdown" -> 'profitability'::"text") ->> 'margem_percent'::"text"))::numeric) AS "margem_percent_prevista",
    "o"."stage" AS "order_stage",
    "o"."created_at" AS "order_created_at"
   FROM ((("public"."orders" "o"
     JOIN "public"."quotes" "q" ON (("q"."id" = "o"."quote_id")))
     LEFT JOIN "public"."vehicle_types" "vt_q" ON (("vt_q"."id" = "q"."vehicle_type_id")))
     LEFT JOIN "public"."vehicle_types" "vt_o" ON (("vt_o"."id" = "o"."vehicle_type_id")))
  WHERE ("o"."quote_id" IS NOT NULL);


ALTER VIEW "public"."v_quote_order_divergence" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."v_trip_financial_details" WITH ("security_invoker"='true') AS
 SELECT "o"."id" AS "order_id",
    "o"."os_number",
    "o"."trip_id",
    "t"."trip_number",
    "t"."vehicle_plate",
    "t"."status_operational" AS "trip_status",
    "o"."value" AS "receita_prevista",
    "o"."value" AS "receita_real",
    COALESCE(((("o"."pricing_breakdown" -> 'components'::"text") ->> 'toll'::"text"))::numeric, (0)::numeric) AS "pedagio_previsto",
    COALESCE("o"."pedagio_real", (0)::numeric) AS "pedagio_real",
    COALESCE(((("o"."pricing_breakdown" -> 'profitability'::"text") ->> 'custosDescarga'::"text"))::numeric, (0)::numeric) AS "descarga_previsto",
    COALESCE("o"."descarga_real", (0)::numeric) AS "descarga_real",
    COALESCE(((("o"."pricing_breakdown" -> 'profitability'::"text") ->> 'custosCarreteiro'::"text"))::numeric, (0)::numeric) AS "carreteiro_previsto",
    COALESCE("o"."carreteiro_real", (0)::numeric) AS "carreteiro_real",
    COALESCE(((("o"."pricing_breakdown" -> 'components'::"text") ->> 'gris'::"text"))::numeric, (0)::numeric) AS "gris_previsto",
    COALESCE(((("o"."pricing_breakdown" -> 'components'::"text") ->> 'tso'::"text"))::numeric, (0)::numeric) AS "tso_previsto",
        CASE
            WHEN ("o"."trip_id" IS NULL) THEN true
            ELSE false
        END AS "is_avulsa"
   FROM ("public"."orders" "o"
     LEFT JOIN "public"."trips" "t" ON (("t"."id" = "o"."trip_id")))
  WHERE (("o"."value" IS NOT NULL) AND ("o"."value" > (0)::numeric));


ALTER VIEW "public"."v_trip_financial_details" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."v_trip_payment_reconciliation" WITH ("security_invoker"='true') AS
 SELECT "t"."id" AS "trip_id",
    "t"."trip_number",
    "t"."status_operational",
    "t"."financial_status",
    "count"("o"."id") AS "orders_count",
    COALESCE("sum"("v"."expected_amount"), (0)::numeric) AS "expected_amount",
    COALESCE("sum"("v"."paid_amount"), (0)::numeric) AS "paid_amount",
    (COALESCE("sum"("v"."paid_amount"), (0)::numeric) - COALESCE("sum"("v"."expected_amount"), (0)::numeric)) AS "delta_amount",
    "bool_and"("v"."is_reconciled") AS "all_orders_reconciled",
    ("abs"((COALESCE("sum"("v"."paid_amount"), (0)::numeric) - COALESCE("sum"("v"."expected_amount"), (0)::numeric))) <= (1)::numeric) AS "total_reconciled",
    ("bool_and"("v"."is_reconciled") AND ("abs"((COALESCE("sum"("v"."paid_amount"), (0)::numeric) - COALESCE("sum"("v"."expected_amount"), (0)::numeric))) <= (1)::numeric)) AS "trip_reconciled",
    "max"("v"."last_paid_at") AS "last_paid_at"
   FROM (("public"."trips" "t"
     JOIN "public"."orders" "o" ON (("o"."trip_id" = "t"."id")))
     JOIN "public"."v_order_payment_reconciliation" "v" ON (("v"."order_id" = "o"."id")))
  GROUP BY "t"."id", "t"."trip_number", "t"."status_operational", "t"."financial_status";


ALTER VIEW "public"."v_trip_payment_reconciliation" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."valid_users" WITH ("security_invoker"='on') AS
 SELECT "id" AS "user_id",
    "email"
   FROM "auth"."users" "u"
  WHERE ("lower"("split_part"(("email")::"text", '@'::"text", 2)) = 'vectracargo.com.br'::"text");


ALTER VIEW "public"."valid_users" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."vectra_manifestos" (
    "id" integer NOT NULL,
    "manifesto" "text" NOT NULL,
    "motorista" "text",
    "veiculo" "text",
    "emissao" "date",
    "origem" "text",
    "destino" "text",
    "rota" "text",
    "proprietario" "text",
    "tipo" "text",
    "frete" numeric(14,2),
    "pedagio" numeric(10,2),
    "combustivel" numeric(10,2),
    "peso" numeric(12,2),
    "ciot" "text",
    "has_ciot" boolean DEFAULT false,
    "status" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "vectra_manifestos_tipo_check" CHECK (("tipo" = ANY (ARRAY['TAC'::"text", 'ETC'::"text"])))
);


ALTER TABLE "public"."vectra_manifestos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."vectra_manifestos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."vectra_manifestos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."vectra_manifestos_id_seq" OWNED BY "public"."vectra_manifestos"."id";



CREATE TABLE IF NOT EXISTS "public"."vectra_motoristas_margem" (
    "id" integer NOT NULL,
    "motorista" "text" NOT NULL,
    "viagens" integer,
    "receita_total" numeric(14,2),
    "custo_total" numeric(14,2),
    "margem_rs" numeric(14,2),
    "margem_pct" numeric(6,1),
    "pedagio_total" numeric(10,2),
    "peso_total" numeric(14,2),
    "km_total" numeric(12,2),
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."vectra_motoristas_margem" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."vectra_motoristas_margem_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."vectra_motoristas_margem_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."vectra_motoristas_margem_id_seq" OWNED BY "public"."vectra_motoristas_margem"."id";



CREATE TABLE IF NOT EXISTS "public"."vectra_rentabilidade_rotas" (
    "id" integer NOT NULL,
    "rota" "text" NOT NULL,
    "viagens" integer,
    "ctes" integer,
    "receita_total" numeric(14,2),
    "custo_total" numeric(14,2),
    "margem_rs" numeric(14,2),
    "margem_pct" numeric(6,1),
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."vectra_rentabilidade_rotas" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."vectra_rentabilidade_rotas_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."vectra_rentabilidade_rotas_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."vectra_rentabilidade_rotas_id_seq" OWNED BY "public"."vectra_rentabilidade_rotas"."id";



CREATE TABLE IF NOT EXISTS "public"."vehicles" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "plate" "text" NOT NULL,
    "brand" "text",
    "model" "text",
    "year" smallint,
    "color" "text",
    "renavam" "text",
    "driver_id" "uuid",
    "owner_id" "uuid",
    "active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "plate_2" "text",
    "plate_mask" "text",
    "plate_2_mask" "text",
    "vehicle_type_id" "uuid",
    "capacity_kg" numeric,
    "capacity_m3" numeric,
    "qtd_pallets" integer,
    CONSTRAINT "vehicles_year_check" CHECK ((("year" IS NULL) OR (("year" >= 1950) AND ("year" <= 2100))))
);


ALTER TABLE "public"."vehicles" OWNER TO "postgres";


COMMENT ON COLUMN "public"."vehicles"."capacity_kg" IS 'Capacidade de carga em kg do veiculo individual';



COMMENT ON COLUMN "public"."vehicles"."capacity_m3" IS 'Volume util em m3 do veiculo individual (depende da configuracao real do bau)';



COMMENT ON COLUMN "public"."vehicles"."qtd_pallets" IS 'Override manual da quantidade de pallets PBR (1m x 1,20m). NULL = usar calculo automatico floor(capacity_m3 / 3.0).';



CREATE OR REPLACE VIEW "public"."vw_ntc_publish_pattern" WITH ("security_invoker"='true') AS
 SELECT "dia_semana",
        CASE "dia_semana"
            WHEN 0 THEN 'Dom'::"text"
            WHEN 1 THEN 'Seg'::"text"
            WHEN 2 THEN 'Ter'::"text"
            WHEN 3 THEN 'Qua'::"text"
            WHEN 4 THEN 'Qui'::"text"
            WHEN 5 THEN 'Sex'::"text"
            WHEN 6 THEN 'Sab'::"text"
            ELSE NULL::"text"
        END AS "dia_nome",
    "hora_brt",
    "count"(*) FILTER (WHERE "is_new_period") AS "publicacoes_novas",
    "count"(*) FILTER (WHERE ("status" = 'success'::"text")) AS "scrapes_com_dados",
    "count"(*) AS "total_tentativas",
    "round"(((("count"(*) FILTER (WHERE "is_new_period"))::numeric / (NULLIF("count"(*), 0))::numeric) * (100)::numeric), 1) AS "hit_rate_pct"
   FROM "public"."ntc_scrape_log"
  GROUP BY "dia_semana",
        CASE "dia_semana"
            WHEN 0 THEN 'Dom'::"text"
            WHEN 1 THEN 'Seg'::"text"
            WHEN 2 THEN 'Ter'::"text"
            WHEN 3 THEN 'Qua'::"text"
            WHEN 4 THEN 'Qui'::"text"
            WHEN 5 THEN 'Sex'::"text"
            WHEN 6 THEN 'Sab'::"text"
            ELSE NULL::"text"
        END, "hora_brt"
  ORDER BY ("count"(*) FILTER (WHERE "is_new_period")) DESC, "hora_brt";


ALTER VIEW "public"."vw_ntc_publish_pattern" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."vw_ntc_scrape_history" WITH ("security_invoker"='true') AS
 SELECT ("scraped_at" AT TIME ZONE 'America/Sao_Paulo'::"text") AS "scraped_at_brt",
    "status",
    "periodo_referencia",
    "is_new_period",
    "duration_ms",
    "error_message"
   FROM "public"."ntc_scrape_log"
  ORDER BY "scraped_at" DESC
 LIMIT 100;


ALTER VIEW "public"."vw_ntc_scrape_history" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."vw_order_risk_status" WITH ("security_invoker"='true') AS
 SELECT "o"."id" AS "order_id",
    "o"."os_number",
    "o"."stage",
    "o"."cargo_value",
    "o"."trip_id",
    "re"."id" AS "evaluation_id",
    "re"."criticality",
    "re"."status" AS "risk_status",
    "re"."requirements",
    "re"."requirements_met",
    "re"."approval_request_id",
    COALESCE("sum"("rc"."total_cost"), (0)::numeric) AS "total_risk_cost",
    (EXISTS ( SELECT 1
           FROM "public"."risk_evidence" "rev"
          WHERE (("rev"."evaluation_id" = "re"."id") AND ("rev"."evidence_type" = 'buonny_check'::"text") AND ("rev"."status" = 'valid'::"text") AND ("rev"."expires_at" > "now"())))) AS "buonny_valid"
   FROM (("public"."orders" "o"
     LEFT JOIN "public"."risk_evaluations" "re" ON ((("re"."entity_type" = 'order'::"text") AND ("re"."entity_id" = "o"."id") AND ("re"."status" <> ALL (ARRAY['expired'::"public"."risk_evaluation_status", 'rejected'::"public"."risk_evaluation_status"])))))
     LEFT JOIN "public"."risk_costs" "rc" ON (("rc"."order_id" = "o"."id")))
  GROUP BY "o"."id", "o"."os_number", "o"."stage", "o"."cargo_value", "o"."trip_id", "re"."id", "re"."criticality", "re"."status", "re"."requirements", "re"."requirements_met", "re"."approval_request_id";


ALTER VIEW "public"."vw_order_risk_status" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."vw_trip_risk_summary" WITH ("security_invoker"='true') AS
 SELECT "t"."id" AS "trip_id",
    "t"."trip_number",
    "t"."status_operational",
    "count"(DISTINCT "o"."id") AS "order_count",
    "sum"(COALESCE("o"."cargo_value", (0)::numeric)) AS "total_cargo_value",
    "max"(("re"."criticality")::"text") AS "max_criticality",
    "bool_and"(("re"."status" = 'approved'::"public"."risk_evaluation_status")) AS "all_orders_approved",
    "re_trip"."status" AS "trip_risk_status",
    "re_trip"."criticality" AS "trip_criticality",
    COALESCE("sum"("rc"."total_cost"), (0)::numeric) AS "total_risk_cost"
   FROM (((("public"."trips" "t"
     JOIN "public"."orders" "o" ON (("o"."trip_id" = "t"."id")))
     LEFT JOIN "public"."risk_evaluations" "re" ON ((("re"."entity_type" = 'order'::"text") AND ("re"."entity_id" = "o"."id") AND ("re"."status" <> ALL (ARRAY['expired'::"public"."risk_evaluation_status", 'rejected'::"public"."risk_evaluation_status"])))))
     LEFT JOIN "public"."risk_evaluations" "re_trip" ON ((("re_trip"."entity_type" = 'trip'::"text") AND ("re_trip"."entity_id" = "t"."id") AND ("re_trip"."status" <> ALL (ARRAY['expired'::"public"."risk_evaluation_status", 'rejected'::"public"."risk_evaluation_status"])))))
     LEFT JOIN "public"."risk_costs" "rc" ON (("rc"."trip_id" = "t"."id")))
  GROUP BY "t"."id", "t"."trip_number", "t"."status_operational", "re_trip"."status", "re_trip"."criticality";


ALTER VIEW "public"."vw_trip_risk_summary" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."waiting_time_rules" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "vehicle_type_id" "uuid",
    "context" "text" DEFAULT 'both'::"text" NOT NULL,
    "free_hours" numeric DEFAULT 6 NOT NULL,
    "rate_per_hour" numeric,
    "rate_per_day" numeric,
    "min_charge" numeric,
    "valid_from" "date",
    "valid_until" "date",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid" DEFAULT "auth"."uid"(),
    CONSTRAINT "waiting_time_rules_context_check" CHECK (("context" = ANY (ARRAY['loading'::"text", 'unloading'::"text", 'both'::"text"])))
);


ALTER TABLE "public"."waiting_time_rules" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."workflow_definitions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "entity_type" "text" NOT NULL,
    "stages" "jsonb" NOT NULL,
    "active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."workflow_definitions" OWNER TO "postgres";


COMMENT ON TABLE "public"."workflow_definitions" IS 'Defines valid stages for each entity type';



CREATE TABLE IF NOT EXISTS "public"."workflow_event_logs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_id" "uuid",
    "action" "text" NOT NULL,
    "agent" "text" NOT NULL,
    "details" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."workflow_event_logs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."workflow_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_type" "text" NOT NULL,
    "entity_type" "text" NOT NULL,
    "entity_id" "uuid" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "retry_count" integer DEFAULT 0 NOT NULL,
    "max_retries" integer DEFAULT 3 NOT NULL,
    "error_message" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "processed_at" timestamp with time zone,
    "created_by" "uuid",
    "execute_after" timestamp with time zone
);


ALTER TABLE "public"."workflow_events" OWNER TO "postgres";


COMMENT ON COLUMN "public"."workflow_events"."execute_after" IS 'When set, event is only processed after now() >= execute_after. NULL = immediate.';



CREATE TABLE IF NOT EXISTS "public"."workflow_transitions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workflow_id" "uuid" NOT NULL,
    "from_stage" "text" NOT NULL,
    "to_stage" "text" NOT NULL,
    "conditions" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "required_fields" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "required_documents" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "requires_approval" boolean DEFAULT false NOT NULL,
    "approval_type" "text",
    "post_actions" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "description" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."workflow_transitions" OWNER TO "postgres";


COMMENT ON TABLE "public"."workflow_transitions" IS 'Valid transitions between stages with conditions and requirements';



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
    CONSTRAINT "adapter_field_definitions_field_type_check" CHECK (("field_type" = ANY (ARRAY['text'::"text", 'textarea'::"text", 'number'::"text", 'boolean'::"text", 'select'::"text", 'multiselect'::"text", 'file_upload'::"text", 'secret'::"text", 'url'::"text"])))
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
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "config_schema" "jsonb"
);


ALTER TABLE "vectraclip"."agent_specialties" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."agent_specialty_configs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "agent_id" "uuid" NOT NULL,
    "specialty_id" "text" NOT NULL,
    "values" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."agent_specialty_configs" OWNER TO "postgres";


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
    "system_prompt" "text",
    "requires_approval" boolean DEFAULT false NOT NULL,
    "platform_url" "text",
    "is_system" boolean DEFAULT false NOT NULL,
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


CREATE TABLE IF NOT EXISTS "vectraclip"."approvals" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "request_type" "text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "approved_by_user_id" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "approvals_request_type_check" CHECK (("request_type" = ANY (ARRAY['hire_agent'::"text", 'strategy'::"text", 'budget_increase'::"text", 'task_done'::"text"]))),
    CONSTRAINT "approvals_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'approved'::"text", 'rejected'::"text"])))
);


ALTER TABLE "vectraclip"."approvals" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."companies" (
    "company_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "tier" "text" DEFAULT 'trial'::"text" NOT NULL,
    "owner_user_id" "uuid",
    "context_json" "jsonb",
    CONSTRAINT "companies_tier_check" CHECK (("tier" = ANY (ARRAY['trial'::"text", 'standard'::"text", 'enterprise'::"text"])))
);


ALTER TABLE "vectraclip"."companies" OWNER TO "postgres";


COMMENT ON COLUMN "vectraclip"."companies"."company_id" IS 'company';



COMMENT ON COLUMN "vectraclip"."companies"."context_json" IS 'Perfil operacional gerado pelo Oracle Research: modais, regiões, tipos de carga, etc.';



CREATE TABLE IF NOT EXISTS "vectraclip"."company_secrets" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "vault_secret_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."company_secrets" OWNER TO "postgres";


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


CREATE TABLE IF NOT EXISTS "vectraclip"."hermes_sender_whitelist" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "email" "text" NOT NULL,
    "label" "text",
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."hermes_sender_whitelist" OWNER TO "postgres";


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


CREATE TABLE IF NOT EXISTS "vectraclip"."kronos_rules" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "type" "text" NOT NULL,
    "pattern" "text" NOT NULL,
    "category" "text" NOT NULL,
    "subcategory" "text",
    "confidence" numeric(4,2) NOT NULL,
    "priority" integer DEFAULT 100 NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "kronos_rules_confidence_check" CHECK ((("confidence" >= (0)::numeric) AND ("confidence" <= (1)::numeric))),
    CONSTRAINT "kronos_rules_type_check" CHECK (("type" = ANY (ARRAY['expense'::"text", 'revenue'::"text"])))
);


ALTER TABLE "vectraclip"."kronos_rules" OWNER TO "postgres";


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



CREATE TABLE IF NOT EXISTS "vectraclip"."projects" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "mission" "text" DEFAULT ''::"text" NOT NULL,
    "status" "text" DEFAULT 'backlog'::"text" NOT NULL,
    "lead_agent_id" "uuid",
    "target_date" timestamp with time zone,
    "issue_completion_pct" numeric(5,2) DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "color" "text",
    "archived_at" timestamp with time zone,
    CONSTRAINT "projects_issue_completion_pct_check" CHECK ((("issue_completion_pct" >= (0)::numeric) AND ("issue_completion_pct" <= (100)::numeric))),
    CONSTRAINT "projects_status_check" CHECK (("status" = ANY (ARRAY['backlog'::"text", 'planned'::"text", 'in_progress'::"text", 'completed'::"text", 'canceled'::"text"])))
);


ALTER TABLE "vectraclip"."projects" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."prospect_profiles" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "nome_razao_social" "text",
    "cnpj" "text",
    "website" "text",
    "setor" "text",
    "endereco" "jsonb",
    "telefone" "text",
    "email_contato" "text",
    "decisores" "jsonb",
    "source_task_id" "uuid",
    "enriched_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "raw_research" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "artifacts" "jsonb"
);


ALTER TABLE "vectraclip"."prospect_profiles" OWNER TO "postgres";


COMMENT ON COLUMN "vectraclip"."prospect_profiles"."artifacts" IS 'JSON: fontes_analisadas[], outreach_email{assunto,corpo_texto}, storage[{bucket,path,url}]';



CREATE TABLE IF NOT EXISTS "vectraclip"."routines" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "schedule" "jsonb" NOT NULL,
    "agent_id" "uuid",
    "metadata" "jsonb",
    "next_run_at" timestamp with time zone,
    "last_run_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "operation_type" "text" DEFAULT 'email_lead'::"text" NOT NULL,
    "prompt_template" "text",
    CONSTRAINT "routines_operation_type_check" CHECK (("operation_type" = ANY (ARRAY['email_lead'::"text", 'route-cost-calculation'::"text", 'freight-quotation'::"text", 'crm-fill'::"text", 'crm-fill-precheck'::"text", 'financial-audit'::"text", 'financial-bookkeeping'::"text", 'other'::"text"]))),
    CONSTRAINT "routines_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'paused'::"text", 'error'::"text"])))
);


ALTER TABLE "vectraclip"."routines" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."run_transcript_entries" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "run_id" "uuid" NOT NULL,
    "role" "text" NOT NULL,
    "message" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "run_transcript_entries_role_check" CHECK (("role" = ANY (ARRAY['system'::"text", 'user'::"text", 'assistant'::"text", 'tool'::"text"])))
);


ALTER TABLE "vectraclip"."run_transcript_entries" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."runs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid" NOT NULL,
    "agent_id" "uuid",
    "task_id" "uuid",
    "routine_id" "uuid",
    "status" "text" DEFAULT 'running'::"text" NOT NULL,
    "started_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "finished_at" timestamp with time zone,
    "duration_ms" integer,
    "tokens_in" integer DEFAULT 0 NOT NULL,
    "tokens_out" integer DEFAULT 0 NOT NULL,
    "cost_usd" numeric(12,8) DEFAULT 0 NOT NULL,
    CONSTRAINT "runs_status_check" CHECK (("status" = ANY (ARRAY['running'::"text", 'succeeded'::"text", 'failed'::"text", 'cancelled'::"text"])))
);


ALTER TABLE "vectraclip"."runs" OWNER TO "postgres";


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


CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_edges" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "process_id" "uuid" NOT NULL,
    "source_id" "uuid" NOT NULL,
    "target_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "vectraclip"."sipoc_edges" OWNER TO "postgres";


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


CREATE TABLE IF NOT EXISTS "vectraclip"."sipoc_raci" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "process_id" "uuid" NOT NULL,
    "component_id" "uuid" NOT NULL,
    "position_id" "uuid" NOT NULL,
    "role" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "sipoc_raci_role_check" CHECK (("role" = ANY (ARRAY['R'::"text", 'A'::"text", 'C'::"text", 'I'::"text", ''::"text"])))
);


ALTER TABLE "vectraclip"."sipoc_raci" OWNER TO "postgres";


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
    "output_json" "jsonb",
    "approved_at" timestamp with time zone,
    "approved_by_user_id" "uuid",
    "input_json" "jsonb",
    "dependency_step_codes" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "successor_step_codes" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "is_critical_path" boolean DEFAULT false NOT NULL,
    "workflow_step_id" "uuid",
    CONSTRAINT "tasks_budget_limit_check" CHECK (("budget_limit" >= 0)),
    CONSTRAINT "tasks_cost_usd_nonnegative" CHECK (("cost_usd" >= (0)::numeric)),
    CONSTRAINT "tasks_executor_type_check" CHECK (("executor_type" = ANY (ARRAY['harness'::"text", 'managed_agent'::"text", 'auto'::"text"]))),
    CONSTRAINT "tasks_operation_type_check" CHECK (("operation_type" = ANY (ARRAY['orchestration'::"text", 'code_generation'::"text", 'code_review'::"text", 'research'::"text", 'document_generation'::"text", 'qa_testing'::"text", 'email_lead'::"text", 'freight-quotation'::"text", 'freight-quotation-approval'::"text", 'route-cost-calculation'::"text", 'crm-fill-precheck'::"text", 'crm-fill-finalize'::"text", 'crm-fill'::"text", 'oracle-research'::"text", 'oracle-extract'::"text", 'oracle-report'::"text", 'oracle-rag'::"text", 'oracle-vision'::"text", 'oracle-summarize'::"text", 'dispatch-research'::"text", 'financial-audit'::"text", 'financial-bookkeeping'::"text", 'conciliacao-backlog'::"text", 'other'::"text"]))),
    CONSTRAINT "tasks_spent_check" CHECK (("spent" >= (0)::numeric)),
    CONSTRAINT "tasks_status_check" CHECK (("status" = ANY (ARRAY['backlog'::"text", 'queued'::"text", 'in_progress'::"text", 'review'::"text", 'done'::"text", 'blocked'::"text", 'errored'::"text"])))
);


ALTER TABLE "vectraclip"."tasks" OWNER TO "postgres";


COMMENT ON COLUMN "vectraclip"."tasks"."output_json" IS 'Structured output produced by the executor agent (email leads, validated briefing, quote ids, etc). Set by the agent before transitioning to status=review so Morpheus can route the next step.';



COMMENT ON COLUMN "vectraclip"."tasks"."dependency_step_codes" IS 'Snapshot of DAG predecessors (step slugs) at materialization; used by agent_daemon promotion.';



COMMENT ON COLUMN "vectraclip"."tasks"."successor_step_codes" IS 'Snapshot of DAG successors (step slugs) at materialization; used by agent_daemon promotion.';



COMMENT ON COLUMN "vectraclip"."tasks"."workflow_step_id" IS 'Etapa SIPOC/workflow ativa (Morpheus). Nullable quando a task não está num pipeline versionado.';



CREATE OR REPLACE VIEW "vectraclip"."task_tree_status" AS
 SELECT "parent_task_id" AS "parent_id",
    "count"(*) AS "children_total",
    "count"(*) FILTER (WHERE ("status" = 'done'::"text")) AS "children_done",
    "count"(*) FILTER (WHERE ("status" = 'blocked'::"text")) AS "children_blocked",
    "count"(*) FILTER (WHERE ("status" = 'skipped'::"text")) AS "children_skipped",
    "count"(*) FILTER (WHERE ("status" = ANY (ARRAY['queued'::"text", 'in_progress'::"text", 'review'::"text", 'backlog'::"text"]))) AS "children_pending"
   FROM "vectraclip"."tasks" "t"
  WHERE ("parent_task_id" IS NOT NULL)
  GROUP BY "parent_task_id";


ALTER VIEW "vectraclip"."task_tree_status" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."tasks_block_log" (
    "id" bigint NOT NULL,
    "logged_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "reason" "text" NOT NULL,
    "payload" "jsonb" NOT NULL
);


ALTER TABLE "vectraclip"."tasks_block_log" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "vectraclip"."tasks_block_log_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "vectraclip"."tasks_block_log_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "vectraclip"."tasks_block_log_id_seq" OWNED BY "vectraclip"."tasks_block_log"."id";



CREATE TABLE IF NOT EXISTS "vectraclip"."workflow_definitions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "company_id" "uuid",
    "name" "text" NOT NULL,
    "slug" "text" NOT NULL,
    "description" "text",
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "version" integer DEFAULT 1 NOT NULL,
    "last_run_at" timestamp with time zone
);


ALTER TABLE "vectraclip"."workflow_definitions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "vectraclip"."workflow_steps" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workflow_id" "uuid" NOT NULL,
    "step_order" integer NOT NULL,
    "name" "text" NOT NULL,
    "slug" "text" NOT NULL,
    "specialty_slug" "text",
    "requires_approval" boolean DEFAULT false NOT NULL,
    "on_success_step_id" "uuid",
    "on_failure_action" "text" DEFAULT 'block'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "current_operation_type" "text",
    "next_operation_type" "text",
    "active" boolean DEFAULT true NOT NULL,
    "sipoc_meta" "jsonb",
    "contract_version" "text" DEFAULT 'v1'::"text" NOT NULL,
    "validation_status" "text" DEFAULT 'verde'::"text" NOT NULL,
    "validation_errors" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "logic_pattern" "text",
    "responsavel" "text",
    "setor" "text",
    "ferramentas" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "sla_horas" integer,
    "alertas" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "suppliers" "jsonb",
    "inputs" "jsonb",
    "outputs" "jsonb",
    "customers" "jsonb",
    "decisions" "jsonb",
    "five_w2h" "jsonb",
    "proximo_step_codes" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "default_operation_type" "text",
    CONSTRAINT "workflow_steps_logic_pattern_check" CHECK ((("logic_pattern" IS NULL) OR ("logic_pattern" = ANY (ARRAY['SIMPLE'::"text", 'SPLIT'::"text", 'MERGE'::"text", 'LOOP-FOR-EACH'::"text", 'LOOP-WHILE'::"text", 'WAIT-EVENT'::"text", 'WAIT-TIME'::"text", 'SUBFLOW'::"text", 'ERROR-HANDLER'::"text", 'FORCE-FAIL'::"text", 'MANUAL'::"text"])))),
    CONSTRAINT "workflow_steps_on_failure_action_check" CHECK (("on_failure_action" = ANY (ARRAY['block'::"text", 'retry'::"text", 'skip'::"text"]))),
    CONSTRAINT "workflow_steps_responsavel_check" CHECK ((("responsavel" IS NULL) OR ("responsavel" = ANY (ARRAY['agente'::"text", 'humano'::"text", 'sistema'::"text"])))),
    CONSTRAINT "workflow_steps_validation_status_check" CHECK (("validation_status" = ANY (ARRAY['verde'::"text", 'amarelo'::"text", 'vermelho'::"text"])))
);


ALTER TABLE "vectraclip"."workflow_steps" OWNER TO "postgres";


ALTER TABLE ONLY "public"."cnh_categories" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."cnh_categories_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."mirofish_monthly_revenue" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."mirofish_monthly_revenue_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."vectra_manifestos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."vectra_manifestos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."vectra_motoristas_margem" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."vectra_motoristas_margem_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."vectra_rentabilidade_rotas" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."vectra_rentabilidade_rotas_id_seq"'::"regclass");



ALTER TABLE ONLY "vectraclip"."managed_agent_turn_logs" ALTER COLUMN "id" SET DEFAULT "nextval"('"vectraclip"."managed_agent_turn_logs_id_seq"'::"regclass");



ALTER TABLE ONLY "vectraclip"."tasks_block_log" ALTER COLUMN "id" SET DEFAULT "nextval"('"vectraclip"."tasks_block_log_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."agent_jobs"
    ADD CONSTRAINT "agent_jobs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ai_budget_config"
    ADD CONSTRAINT "ai_budget_config_key_key" UNIQUE ("key");



ALTER TABLE ONLY "public"."ai_budget_config"
    ADD CONSTRAINT "ai_budget_config_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ai_insights"
    ADD CONSTRAINT "ai_insights_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ai_usage_tracking"
    ADD CONSTRAINT "ai_usage_tracking_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."antt_floor_rates"
    ADD CONSTRAINT "antt_floor_rates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."antt_violation_alerts"
    ADD CONSTRAINT "antt_violation_alerts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_requests"
    ADD CONSTRAINT "approval_requests_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."approval_rules"
    ADD CONSTRAINT "approval_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."audit_logs"
    ADD CONSTRAINT "audit_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."clients"
    ADD CONSTRAINT "clients_cpf_key" UNIQUE ("cpf");



ALTER TABLE ONLY "public"."clients"
    ADD CONSTRAINT "clients_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."cnh_categories"
    ADD CONSTRAINT "cnh_categories_code_unique" UNIQUE ("code");



ALTER TABLE ONLY "public"."cnh_categories"
    ADD CONSTRAINT "cnh_categories_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."collected_data"
    ADD CONSTRAINT "collected_data_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."collection_orders"
    ADD CONSTRAINT "collection_orders_oc_number_key" UNIQUE ("oc_number");



ALTER TABLE ONLY "public"."collection_orders"
    ADD CONSTRAINT "collection_orders_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."collection_orders"
    ADD CONSTRAINT "collection_orders_seq_unique" UNIQUE ("oc_year", "oc_month", "oc_seq");



ALTER TABLE ONLY "public"."commercial_closeout_events"
    ADD CONSTRAINT "commercial_closeout_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."commercial_followup_rules"
    ADD CONSTRAINT "commercial_followup_rules_name_key" UNIQUE ("name");



ALTER TABLE ONLY "public"."commercial_followup_rules"
    ADD CONSTRAINT "commercial_followup_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."commercial_followup_runs"
    ADD CONSTRAINT "commercial_followup_runs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."commercial_message_events"
    ADD CONSTRAINT "commercial_message_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."commercial_operational_handoffs"
    ADD CONSTRAINT "commercial_operational_handoffs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."company_settings"
    ADD CONSTRAINT "company_settings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."compliance_checks"
    ADD CONSTRAINT "compliance_checks_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."conditional_fees"
    ADD CONSTRAINT "conditional_fees_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."conditional_fees"
    ADD CONSTRAINT "conditional_fees_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."delivery_assessments"
    ADD CONSTRAINT "delivery_assessments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."delivery_conditions"
    ADD CONSTRAINT "delivery_conditions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."discharge_checklist_items"
    ADD CONSTRAINT "discharge_checklist_items_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."driver_offer_ranking_config"
    ADD CONSTRAINT "driver_offer_ranking_config_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "driver_offer_sequences_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."driver_offers"
    ADD CONSTRAINT "driver_offers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."driver_qualifications"
    ADD CONSTRAINT "driver_qualifications_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."drivers"
    ADD CONSTRAINT "drivers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."edge_function_api_keys"
    ADD CONSTRAINT "edge_function_api_keys_key_hash_key" UNIQUE ("key_hash");



ALTER TABLE ONLY "public"."edge_function_api_keys"
    ADD CONSTRAINT "edge_function_api_keys_name_key" UNIQUE ("name");



ALTER TABLE ONLY "public"."edge_function_api_keys"
    ADD CONSTRAINT "edge_function_api_keys_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."equipment_rental_rates"
    ADD CONSTRAINT "equipment_rental_rates_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."equipment_rental_rates"
    ADD CONSTRAINT "equipment_rental_rates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."financial_documents"
    ADD CONSTRAINT "financial_documents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."financial_installments"
    ADD CONSTRAINT "financial_installments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."gris_services"
    ADD CONSTRAINT "gris_services_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."gris_services"
    ADD CONSTRAINT "gris_services_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."icms_rates"
    ADD CONSTRAINT "icms_rates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."icms_rates"
    ADD CONSTRAINT "icms_rates_unique_pair" UNIQUE ("origin_state", "destination_state");



ALTER TABLE ONLY "public"."insurance_logs"
    ADD CONSTRAINT "insurance_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."load_composition_discount_breakdown"
    ADD CONSTRAINT "load_composition_discount_breakdown_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."load_composition_metrics"
    ADD CONSTRAINT "load_composition_metrics_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."load_composition_routings"
    ADD CONSTRAINT "load_composition_routings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."load_composition_suggestions"
    ADD CONSTRAINT "load_composition_suggestions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."logistics_traffic_rules"
    ADD CONSTRAINT "logistics_traffic_rules_city_state_organ_name_key" UNIQUE ("city", "state", "organ_name");



ALTER TABLE ONLY "public"."logistics_traffic_rules"
    ADD CONSTRAINT "logistics_traffic_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ltl_parameters"
    ADD CONSTRAINT "ltl_parameters_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."market_indices"
    ADD CONSTRAINT "market_indices_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mirofish_monthly_revenue"
    ADD CONSTRAINT "mirofish_monthly_revenue_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mirofish_recommendations"
    ADD CONSTRAINT "mirofish_recommendations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mirofish_reports"
    ADD CONSTRAINT "mirofish_reports_mirofish_report_id_key" UNIQUE ("mirofish_report_id");



ALTER TABLE ONLY "public"."mirofish_reports"
    ADD CONSTRAINT "mirofish_reports_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mirofish_route_insights"
    ADD CONSTRAINT "mirofish_route_insights_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mirofish_shipper_insights"
    ADD CONSTRAINT "mirofish_shipper_insights_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."news_items"
    ADD CONSTRAINT "news_items_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notification_logs"
    ADD CONSTRAINT "notification_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notification_queue"
    ADD CONSTRAINT "notification_queue_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notification_templates"
    ADD CONSTRAINT "notification_templates_key_key" UNIQUE ("key");



ALTER TABLE ONLY "public"."notification_templates"
    ADD CONSTRAINT "notification_templates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ntc_articles_seen"
    ADD CONSTRAINT "ntc_articles_seen_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ntc_articles_seen"
    ADD CONSTRAINT "ntc_articles_seen_url_key" UNIQUE ("url");



ALTER TABLE ONLY "public"."ntc_cost_indices"
    ADD CONSTRAINT "ntc_cost_indices_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ntc_fuel_reference"
    ADD CONSTRAINT "ntc_fuel_reference_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ntc_fuel_reference"
    ADD CONSTRAINT "ntc_fuel_reference_reference_month_key" UNIQUE ("reference_month");



ALTER TABLE ONLY "public"."ntc_scrape_log"
    ADD CONSTRAINT "ntc_scrape_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."occurrences"
    ADD CONSTRAINT "occurrences_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."operational_reports"
    ADD CONSTRAINT "operational_reports_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."order_gris_services"
    ADD CONSTRAINT "order_gris_services_order_id_gris_service_id_key" UNIQUE ("order_id", "gris_service_id");



ALTER TABLE ONLY "public"."order_gris_services"
    ADD CONSTRAINT "order_gris_services_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_os_number_key" UNIQUE ("os_number");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."owners"
    ADD CONSTRAINT "owners_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."partner_quotes"
    ADD CONSTRAINT "partner_quotes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."partner_shippers"
    ADD CONSTRAINT "partner_shippers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."partner_shippers"
    ADD CONSTRAINT "partner_shippers_slug_key" UNIQUE ("slug");



ALTER TABLE ONLY "public"."partner_tokens"
    ADD CONSTRAINT "partner_tokens_partner_slug_key" UNIQUE ("partner_slug");



ALTER TABLE ONLY "public"."partner_tokens"
    ADD CONSTRAINT "partner_tokens_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."partner_tokens"
    ADD CONSTRAINT "partner_tokens_token_key" UNIQUE ("token");



ALTER TABLE ONLY "public"."partner_users"
    ADD CONSTRAINT "partner_users_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."partner_users"
    ADD CONSTRAINT "partner_users_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."payment_proofs"
    ADD CONSTRAINT "payment_proofs_document_id_key" UNIQUE ("document_id");



ALTER TABLE ONLY "public"."payment_proofs"
    ADD CONSTRAINT "payment_proofs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."payment_terms"
    ADD CONSTRAINT "payment_terms_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."payment_terms"
    ADD CONSTRAINT "payment_terms_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."petrobras_diesel_prices"
    ADD CONSTRAINT "petrobras_diesel_prices_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."petrobras_diesel_prices"
    ADD CONSTRAINT "petrobras_diesel_prices_uf_periodo_coleta_key" UNIQUE ("uf", "periodo_coleta");



ALTER TABLE ONLY "public"."price_table_rows"
    ADD CONSTRAINT "price_table_rows_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."price_table_rows"
    ADD CONSTRAINT "price_table_rows_unique_range" UNIQUE ("price_table_id", "km_from", "km_to");



ALTER TABLE ONLY "public"."price_tables"
    ADD CONSTRAINT "price_tables_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pricing_parameters"
    ADD CONSTRAINT "pricing_parameters_key_key" UNIQUE ("key");



ALTER TABLE ONLY "public"."pricing_parameters"
    ADD CONSTRAINT "pricing_parameters_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pricing_route_overrides"
    ADD CONSTRAINT "pricing_route_overrides_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pricing_rules_config"
    ADD CONSTRAINT "pricing_rules_config_key_vehicle_type_id_key" UNIQUE NULLS NOT DISTINCT ("key", "vehicle_type_id");



ALTER TABLE ONLY "public"."pricing_rules_config"
    ADD CONSTRAINT "pricing_rules_config_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."processes"
    ADD CONSTRAINT "processes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."product_dimensions"
    ADD CONSTRAINT "product_dimensions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_user_id_key" UNIQUE ("user_id");



ALTER TABLE ONLY "public"."quote_contracts"
    ADD CONSTRAINT "quote_contracts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."quote_payment_proofs"
    ADD CONSTRAINT "quote_payment_proofs_document_id_key" UNIQUE ("document_id");



ALTER TABLE ONLY "public"."quote_payment_proofs"
    ADD CONSTRAINT "quote_payment_proofs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."quote_route_stops"
    ADD CONSTRAINT "quote_route_stops_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."quote_route_stops"
    ADD CONSTRAINT "quote_route_stops_quote_id_sequence_key" UNIQUE ("quote_id", "sequence");



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."regulatory_updates"
    ADD CONSTRAINT "regulatory_updates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."risk_costs"
    ADD CONSTRAINT "risk_costs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."risk_evaluations"
    ADD CONSTRAINT "risk_evaluations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."risk_evidence"
    ADD CONSTRAINT "risk_evidence_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."risk_policies"
    ADD CONSTRAINT "risk_policies_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."risk_policies"
    ADD CONSTRAINT "risk_policies_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."risk_policy_rules"
    ADD CONSTRAINT "risk_policy_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."risk_services_catalog"
    ADD CONSTRAINT "risk_services_catalog_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."risk_services_catalog"
    ADD CONSTRAINT "risk_services_catalog_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."route_metrics_config"
    ADD CONSTRAINT "route_metrics_config_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."route_metrics_config"
    ADD CONSTRAINT "route_metrics_config_unique" UNIQUE ("origin_uf", "destination_uf", "vehicle_type_id");



ALTER TABLE ONLY "public"."settings"
    ADD CONSTRAINT "settings_pkey" PRIMARY KEY ("key");



ALTER TABLE ONLY "public"."shippers"
    ADD CONSTRAINT "shippers_cnpj_key" UNIQUE ("cnpj");



ALTER TABLE ONLY "public"."shippers"
    ADD CONSTRAINT "shippers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sipoc_customers"
    ADD CONSTRAINT "sipoc_customers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sipoc_decisions"
    ADD CONSTRAINT "sipoc_decisions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sipoc_inputs"
    ADD CONSTRAINT "sipoc_inputs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sipoc_maps"
    ADD CONSTRAINT "sipoc_maps_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sipoc_maps"
    ADD CONSTRAINT "sipoc_maps_process_id_step_id_version_key" UNIQUE ("process_id", "step_id", "version");



ALTER TABLE ONLY "public"."sipoc_outputs"
    ADD CONSTRAINT "sipoc_outputs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sipoc_suppliers"
    ADD CONSTRAINT "sipoc_suppliers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."skill_executions"
    ADD CONSTRAINT "skill_executions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tac_rates"
    ADD CONSTRAINT "tac_rates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tac_rates"
    ADD CONSTRAINT "tac_rates_reference_date_key" UNIQUE ("reference_date");



ALTER TABLE ONLY "public"."tasks"
    ADD CONSTRAINT "tasks_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."toll_routes"
    ADD CONSTRAINT "toll_routes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."trip_cost_items"
    ADD CONSTRAINT "trip_cost_items_idempotency_key_key" UNIQUE ("idempotency_key");



ALTER TABLE ONLY "public"."trip_cost_items"
    ADD CONSTRAINT "trip_cost_items_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."trip_orders"
    ADD CONSTRAINT "trip_orders_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."trip_orders"
    ADD CONSTRAINT "trip_orders_trip_id_order_id_key" UNIQUE ("trip_id", "order_id");



ALTER TABLE ONLY "public"."trips"
    ADD CONSTRAINT "trips_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."trips"
    ADD CONSTRAINT "trips_trip_number_key" UNIQUE ("trip_number");



ALTER TABLE ONLY "public"."unloading_cost_rates"
    ADD CONSTRAINT "unloading_cost_rates_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."unloading_cost_rates"
    ADD CONSTRAINT "unloading_cost_rates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."driver_offers"
    ADD CONSTRAINT "uq_offer_driver" UNIQUE ("sequence_id", "driver_id");



ALTER TABLE ONLY "public"."driver_offers"
    ADD CONSTRAINT "uq_offer_position" UNIQUE ("sequence_id", "position");



ALTER TABLE ONLY "public"."price_tables"
    ADD CONSTRAINT "uq_price_tables_name_version" UNIQUE ("name", "version");



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "uq_sequence_quote" UNIQUE ("quote_id");



ALTER TABLE ONLY "public"."user_roles"
    ADD CONSTRAINT "user_roles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_roles"
    ADD CONSTRAINT "user_roles_user_id_role_key" UNIQUE ("user_id", "role");



ALTER TABLE ONLY "public"."vectra_manifestos"
    ADD CONSTRAINT "vectra_manifestos_manifesto_key" UNIQUE ("manifesto");



ALTER TABLE ONLY "public"."vectra_manifestos"
    ADD CONSTRAINT "vectra_manifestos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vectra_motoristas_margem"
    ADD CONSTRAINT "vectra_motoristas_margem_motorista_key" UNIQUE ("motorista");



ALTER TABLE ONLY "public"."vectra_motoristas_margem"
    ADD CONSTRAINT "vectra_motoristas_margem_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vectra_rentabilidade_rotas"
    ADD CONSTRAINT "vectra_rentabilidade_rotas_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vehicle_types"
    ADD CONSTRAINT "vehicle_types_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."vehicle_types"
    ADD CONSTRAINT "vehicle_types_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vehicles"
    ADD CONSTRAINT "vehicles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vehicles"
    ADD CONSTRAINT "vehicles_plate_unique" UNIQUE ("plate");



ALTER TABLE ONLY "public"."waiting_time_rules"
    ADD CONSTRAINT "waiting_time_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."workflow_definitions"
    ADD CONSTRAINT "workflow_definitions_entity_type_key" UNIQUE ("entity_type");



ALTER TABLE ONLY "public"."workflow_definitions"
    ADD CONSTRAINT "workflow_definitions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."workflow_event_logs"
    ADD CONSTRAINT "workflow_event_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."workflow_events"
    ADD CONSTRAINT "workflow_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."workflow_transitions"
    ADD CONSTRAINT "workflow_transitions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."workflow_transitions"
    ADD CONSTRAINT "workflow_transitions_workflow_id_from_stage_to_stage_key" UNIQUE ("workflow_id", "from_stage", "to_stage");



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



ALTER TABLE ONLY "vectraclip"."agent_specialty_configs"
    ADD CONSTRAINT "agent_specialty_configs_agent_id_specialty_id_key" UNIQUE ("agent_id", "specialty_id");



ALTER TABLE ONLY "vectraclip"."agent_specialty_configs"
    ADD CONSTRAINT "agent_specialty_configs_agent_specialty_key" UNIQUE ("agent_id", "specialty_id");



ALTER TABLE ONLY "vectraclip"."agent_specialty_configs"
    ADD CONSTRAINT "agent_specialty_configs_agent_specialty_unique" UNIQUE ("agent_id", "specialty_id");



ALTER TABLE ONLY "vectraclip"."agent_specialty_configs"
    ADD CONSTRAINT "agent_specialty_configs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_company_entity_key" UNIQUE ("company_id", "id");



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."app_users"
    ADD CONSTRAINT "app_users_email_key" UNIQUE ("email");



ALTER TABLE ONLY "vectraclip"."app_users"
    ADD CONSTRAINT "app_users_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."approvals"
    ADD CONSTRAINT "approvals_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."companies"
    ADD CONSTRAINT "companies_pkey" PRIMARY KEY ("company_id");



ALTER TABLE ONLY "vectraclip"."company_secrets"
    ADD CONSTRAINT "company_secrets_company_id_name_key" UNIQUE ("company_id", "name");



ALTER TABLE ONLY "vectraclip"."company_secrets"
    ADD CONSTRAINT "company_secrets_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."goals"
    ADD CONSTRAINT "goals_company_entity_key" UNIQUE ("company_id", "id");



ALTER TABLE ONLY "vectraclip"."goals"
    ADD CONSTRAINT "goals_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."heartbeats"
    ADD CONSTRAINT "heartbeats_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."hermes_sender_whitelist"
    ADD CONSTRAINT "hermes_sender_whitelist_company_id_email_key" UNIQUE ("company_id", "email");



ALTER TABLE ONLY "vectraclip"."hermes_sender_whitelist"
    ADD CONSTRAINT "hermes_sender_whitelist_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."incident_audit"
    ADD CONSTRAINT "incident_audit_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."incidents"
    ADD CONSTRAINT "incidents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."kronos_rules"
    ADD CONSTRAINT "kronos_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."llm_models"
    ADD CONSTRAINT "llm_models_pkey" PRIMARY KEY ("id", "effective_from");



ALTER TABLE ONLY "vectraclip"."managed_agent_sessions"
    ADD CONSTRAINT "managed_agent_sessions_pkey" PRIMARY KEY ("session_id");



ALTER TABLE ONLY "vectraclip"."managed_agent_turn_logs"
    ADD CONSTRAINT "managed_agent_turn_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."projects"
    ADD CONSTRAINT "projects_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."prospect_profiles"
    ADD CONSTRAINT "prospect_profiles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."routines"
    ADD CONSTRAINT "routines_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."run_transcript_entries"
    ADD CONSTRAINT "run_transcript_entries_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."runs"
    ADD CONSTRAINT "runs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_companies"
    ADD CONSTRAINT "sipoc_companies_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_components"
    ADD CONSTRAINT "sipoc_components_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_edges"
    ADD CONSTRAINT "sipoc_edges_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_edges"
    ADD CONSTRAINT "sipoc_edges_src_tgt_uq" UNIQUE ("process_id", "source_id", "target_id");



ALTER TABLE ONLY "vectraclip"."sipoc_positions"
    ADD CONSTRAINT "sipoc_positions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_processes"
    ADD CONSTRAINT "sipoc_processes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_raci"
    ADD CONSTRAINT "sipoc_raci_component_position_uq" UNIQUE ("component_id", "position_id");



ALTER TABLE ONLY "vectraclip"."sipoc_raci"
    ADD CONSTRAINT "sipoc_raci_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_sector_baselines"
    ADD CONSTRAINT "sipoc_sector_baselines_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."sipoc_sector_baselines"
    ADD CONSTRAINT "sipoc_sector_baselines_sector_slug_key" UNIQUE ("sector_slug");



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_company_id_slug_key" UNIQUE ("company_id", "slug");



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."tasks_block_log"
    ADD CONSTRAINT "tasks_block_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_company_entity_key" UNIQUE ("company_id", "id");



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."workflow_definitions"
    ADD CONSTRAINT "workflow_definitions_company_id_slug_key" UNIQUE ("company_id", "slug");



ALTER TABLE ONLY "vectraclip"."workflow_definitions"
    ADD CONSTRAINT "workflow_definitions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "vectraclip"."workflow_steps"
    ADD CONSTRAINT "workflow_steps_pkey" PRIMARY KEY ("id");



CREATE UNIQUE INDEX "antt_floor_rates_unique" ON "public"."antt_floor_rates" USING "btree" ("operation_table", "cargo_type", "axes_count", "valid_from");



CREATE INDEX "antt_violation_alerts_quote_id_idx" ON "public"."antt_violation_alerts" USING "btree" ("quote_id");



CREATE INDEX "antt_violation_alerts_resolved_at_idx" ON "public"."antt_violation_alerts" USING "btree" ("resolved_at") WHERE ("resolved_at" IS NULL);



CREATE UNIQUE INDEX "drivers_cpf_unique" ON "public"."drivers" USING "btree" ("cpf") WHERE ("cpf" IS NOT NULL);



CREATE INDEX "idx_agent_jobs_pending" ON "public"."agent_jobs" USING "btree" ("status") WHERE ("status" = 'pending'::"text");



CREATE INDEX "idx_ai_insights_entity" ON "public"."ai_insights" USING "btree" ("entity_type", "entity_id");



CREATE INDEX "idx_ai_insights_type" ON "public"."ai_insights" USING "btree" ("insight_type", "created_at" DESC);



CREATE INDEX "idx_ai_usage_analysis_type" ON "public"."ai_usage_tracking" USING "btree" ("analysis_type");



CREATE INDEX "idx_ai_usage_created_at" ON "public"."ai_usage_tracking" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_ai_usage_model" ON "public"."ai_usage_tracking" USING "btree" ("model_used");



CREATE INDEX "idx_ai_usage_status" ON "public"."ai_usage_tracking" USING "btree" ("status");



CREATE INDEX "idx_approval_requests_entity" ON "public"."approval_requests" USING "btree" ("entity_type", "entity_id");



CREATE INDEX "idx_approval_requests_pending" ON "public"."approval_requests" USING "btree" ("status", "assigned_to_role") WHERE ("status" = 'pending'::"text");



CREATE INDEX "idx_audit_logs_table_record" ON "public"."audit_logs" USING "btree" ("table_name", "record_id");



CREATE INDEX "idx_clients_user_id" ON "public"."clients" USING "btree" ("user_id");



CREATE INDEX "idx_collection_orders_issued" ON "public"."collection_orders" USING "btree" ("issued_at" DESC);



CREATE INDEX "idx_collection_orders_order_id" ON "public"."collection_orders" USING "btree" ("order_id");



CREATE INDEX "idx_collection_orders_status" ON "public"."collection_orders" USING "btree" ("status");



CREATE INDEX "idx_commercial_closeout_events_message_event_id" ON "public"."commercial_closeout_events" USING "btree" ("message_event_id");



CREATE INDEX "idx_commercial_closeout_events_quote_id" ON "public"."commercial_closeout_events" USING "btree" ("quote_id");



CREATE INDEX "idx_commercial_followup_runs_notification_log_id" ON "public"."commercial_followup_runs" USING "btree" ("notification_log_id");



CREATE INDEX "idx_commercial_followup_runs_quote_id" ON "public"."commercial_followup_runs" USING "btree" ("quote_id");



CREATE INDEX "idx_commercial_followup_runs_rule_id" ON "public"."commercial_followup_runs" USING "btree" ("rule_id");



CREATE INDEX "idx_commercial_message_events_client_id" ON "public"."commercial_message_events" USING "btree" ("client_id");



CREATE INDEX "idx_commercial_message_events_direction" ON "public"."commercial_message_events" USING "btree" ("direction", "created_at" DESC);



CREATE INDEX "idx_commercial_message_events_phone" ON "public"."commercial_message_events" USING "btree" ("phone", "created_at" DESC);



CREATE INDEX "idx_commercial_message_events_quote" ON "public"."commercial_message_events" USING "btree" ("quote_id", "created_at" DESC);



CREATE INDEX "idx_commercial_message_events_shipper_id" ON "public"."commercial_message_events" USING "btree" ("shipper_id");



CREATE INDEX "idx_commercial_operational_handoffs_order_id" ON "public"."commercial_operational_handoffs" USING "btree" ("order_id");



CREATE INDEX "idx_commercial_operational_handoffs_quote_id" ON "public"."commercial_operational_handoffs" USING "btree" ("quote_id");



CREATE INDEX "idx_compliance_checks_order" ON "public"."compliance_checks" USING "btree" ("order_id");



CREATE INDEX "idx_compliance_checks_status" ON "public"."compliance_checks" USING "btree" ("status") WHERE ("status" = ANY (ARRAY['warning'::"public"."compliance_check_status", 'violation'::"public"."compliance_check_status"]));



CREATE INDEX "idx_delivery_assessments_order" ON "public"."delivery_assessments" USING "btree" ("order_id");



CREATE INDEX "idx_delivery_assessments_quote" ON "public"."delivery_assessments" USING "btree" ("quote_id");



CREATE INDEX "idx_delivery_assessments_status" ON "public"."delivery_assessments" USING "btree" ("status");



CREATE INDEX "idx_discount_composition" ON "public"."load_composition_discount_breakdown" USING "btree" ("composition_id");



CREATE INDEX "idx_discount_quote" ON "public"."load_composition_discount_breakdown" USING "btree" ("quote_id");



CREATE INDEX "idx_discount_shipper" ON "public"."load_composition_discount_breakdown" USING "btree" ("shipper_id");



CREATE INDEX "idx_documents_fat_id" ON "public"."documents" USING "btree" ("fat_id");



CREATE INDEX "idx_documents_order_id" ON "public"."documents" USING "btree" ("order_id");



CREATE INDEX "idx_documents_quote_id" ON "public"."documents" USING "btree" ("quote_id");



CREATE INDEX "idx_documents_type" ON "public"."documents" USING "btree" ("type");



CREATE INDEX "idx_driver_offer_sequences_accepted_driver_id" ON "public"."driver_offer_sequences" USING "btree" ("accepted_driver_id");



CREATE INDEX "idx_driver_offer_sequences_order_id" ON "public"."driver_offer_sequences" USING "btree" ("order_id");



CREATE INDEX "idx_driver_offer_sequences_trip_id" ON "public"."driver_offer_sequences" USING "btree" ("trip_id");



CREATE INDEX "idx_driver_offer_sequences_vehicle_type_id" ON "public"."driver_offer_sequences" USING "btree" ("vehicle_type_id");



CREATE INDEX "idx_driver_qualifications_dispatch" ON "public"."driver_qualifications" USING "btree" ("whatsapp_sent_at") WHERE (("status" = 'pendente'::"public"."driver_qualification_status") AND ("whatsapp_sent_at" IS NULL));



CREATE INDEX "idx_driver_qualifications_order" ON "public"."driver_qualifications" USING "btree" ("order_id");



CREATE INDEX "idx_driver_qualifications_remind" ON "public"."driver_qualifications" USING "btree" ("whatsapp_sent_at") WHERE (("status" = 'pendente'::"public"."driver_qualification_status") AND ("whatsapp_reminded_at" IS NULL));



CREATE INDEX "idx_driver_qualifications_status" ON "public"."driver_qualifications" USING "btree" ("status") WHERE ("status" = ANY (ARRAY['pendente'::"public"."driver_qualification_status", 'em_analise'::"public"."driver_qualification_status"]));



CREATE INDEX "idx_drivers_active" ON "public"."drivers" USING "btree" ("active");



CREATE INDEX "idx_drivers_cnh" ON "public"."drivers" USING "btree" ("cnh") WHERE ("cnh" IS NOT NULL);



CREATE INDEX "idx_drivers_cooldown" ON "public"."drivers" USING "btree" ("last_refusal_at", "cooldown_days");



CREATE INDEX "idx_drivers_name" ON "public"."drivers" USING "btree" ("name");



CREATE INDEX "idx_drivers_phone_normalized" ON "public"."drivers" USING "btree" ("phone_normalized");



CREATE INDEX "idx_financial_documents_owner_id" ON "public"."financial_documents" USING "btree" ("owner_id");



CREATE INDEX "idx_financial_documents_source" ON "public"."financial_documents" USING "btree" ("source_type", "source_id");



CREATE INDEX "idx_financial_documents_type" ON "public"."financial_documents" USING "btree" ("type");



CREATE INDEX "idx_financial_installments_doc" ON "public"."financial_installments" USING "btree" ("financial_document_id");



CREATE INDEX "idx_lc_metrics_comp" ON "public"."load_composition_metrics" USING "btree" ("composition_id");



CREATE INDEX "idx_lc_routing_comp" ON "public"."load_composition_routings" USING "btree" ("composition_id");



CREATE INDEX "idx_lc_routing_quote" ON "public"."load_composition_routings" USING "btree" ("quote_id");



CREATE INDEX "idx_lcs_anchor_quote" ON "public"."load_composition_suggestions" USING "btree" ("anchor_quote_id") WHERE ("anchor_quote_id" IS NOT NULL);



CREATE UNIQUE INDEX "idx_lcs_dedup_quote_ids" ON "public"."load_composition_suggestions" USING "btree" ("shipper_id", "quote_ids") WHERE ("status" <> ALL (ARRAY['rejected'::"text", 'executed'::"text"]));



CREATE INDEX "idx_load_comp_created_at" ON "public"."load_composition_suggestions" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_load_comp_shipper" ON "public"."load_composition_suggestions" USING "btree" ("shipper_id");



CREATE INDEX "idx_load_comp_status" ON "public"."load_composition_suggestions" USING "btree" ("status");



CREATE INDEX "idx_load_composition_suggestions_created_order_id" ON "public"."load_composition_suggestions" USING "btree" ("created_order_id");



CREATE INDEX "idx_load_composition_suggestions_suggested_vehicle_type_id" ON "public"."load_composition_suggestions" USING "btree" ("suggested_vehicle_type_id");



CREATE INDEX "idx_market_indices_gerado" ON "public"."market_indices" USING "btree" ("gerado_em" DESC);



CREATE INDEX "idx_market_indices_gerado_em" ON "public"."market_indices" USING "btree" ("gerado_em" DESC);



CREATE UNIQUE INDEX "idx_market_indices_periodo" ON "public"."market_indices" USING "btree" ("periodo_referencia");



CREATE INDEX "idx_mirofish_recommendations_priority" ON "public"."mirofish_recommendations" USING "btree" ("priority", "status");



CREATE INDEX "idx_mirofish_recommendations_report_id" ON "public"."mirofish_recommendations" USING "btree" ("report_id");



CREATE INDEX "idx_mirofish_reports_mirofish_report_id" ON "public"."mirofish_reports" USING "btree" ("mirofish_report_id");



CREATE INDEX "idx_mirofish_reports_period_type" ON "public"."mirofish_reports" USING "btree" ("period_type");



CREATE INDEX "idx_mirofish_reports_status" ON "public"."mirofish_reports" USING "btree" ("status");



CREATE INDEX "idx_mirofish_route_insights_report_id" ON "public"."mirofish_route_insights" USING "btree" ("report_id");



CREATE INDEX "idx_mirofish_route_insights_route" ON "public"."mirofish_route_insights" USING "btree" ("route");



CREATE INDEX "idx_mirofish_shipper_insights_report_id" ON "public"."mirofish_shipper_insights" USING "btree" ("report_id");



CREATE INDEX "idx_mirofish_shipper_insights_shipper_id" ON "public"."mirofish_shipper_insights" USING "btree" ("shipper_id");



CREATE INDEX "idx_news_items_created" ON "public"."news_items" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_news_items_relevance" ON "public"."news_items" USING "btree" ("relevance_score" DESC);



CREATE INDEX "idx_notification_logs_entity" ON "public"."notification_logs" USING "btree" ("entity_type", "entity_id");



CREATE INDEX "idx_notification_logs_pending" ON "public"."notification_logs" USING "btree" ("status", "created_at") WHERE ("status" = 'pending'::"text");



CREATE INDEX "idx_notification_queue_pending" ON "public"."notification_queue" USING "btree" ("status", "created_at") WHERE ("status" = 'pending'::"text");



CREATE INDEX "idx_ntc_articles_pendentes" ON "public"."ntc_articles_seen" USING "btree" ("precisa_insercao_manual") WHERE ("precisa_insercao_manual" = true);



CREATE INDEX "idx_ntc_articles_periodo" ON "public"."ntc_articles_seen" USING "btree" ("periodo_referencia");



CREATE INDEX "idx_ntc_cost_indices_lookup" ON "public"."ntc_cost_indices" USING "btree" ("index_type", "distance_km", "period" DESC);



CREATE UNIQUE INDEX "idx_ntc_cost_indices_unique" ON "public"."ntc_cost_indices" USING "btree" ("index_type", "period", COALESCE("distance_km", 0), COALESCE("pickup_km", 0));



CREATE INDEX "idx_ntc_scrape_log_is_new" ON "public"."ntc_scrape_log" USING "btree" ("is_new_period") WHERE ("is_new_period" = true);



CREATE INDEX "idx_ntc_scrape_log_scraped_at" ON "public"."ntc_scrape_log" USING "btree" ("scraped_at" DESC);



CREATE INDEX "idx_occurrences_order_id" ON "public"."occurrences" USING "btree" ("order_id");



CREATE INDEX "idx_occurrences_severity" ON "public"."occurrences" USING "btree" ("severity");



CREATE INDEX "idx_offers_driver" ON "public"."driver_offers" USING "btree" ("driver_id");



CREATE INDEX "idx_offers_sequence" ON "public"."driver_offers" USING "btree" ("sequence_id");



CREATE INDEX "idx_offers_timeout" ON "public"."driver_offers" USING "btree" ("timeout_at") WHERE ("status" = 'sent'::"public"."driver_offer_status");



CREATE UNIQUE INDEX "idx_operational_reports_date_type" ON "public"."operational_reports" USING "btree" ("report_date", "report_type");



CREATE INDEX "idx_orders_carrier_payment_term" ON "public"."orders" USING "btree" ("carrier_payment_term_id");



CREATE INDEX "idx_orders_client_id" ON "public"."orders" USING "btree" ("client_id");



CREATE INDEX "idx_orders_os_number" ON "public"."orders" USING "btree" ("os_number");



CREATE INDEX "idx_orders_payment_term_id" ON "public"."orders" USING "btree" ("payment_term_id");



CREATE INDEX "idx_orders_price_table_id" ON "public"."orders" USING "btree" ("price_table_id");



CREATE INDEX "idx_orders_quote_id" ON "public"."orders" USING "btree" ("quote_id");



CREATE INDEX "idx_orders_shipper_id" ON "public"."orders" USING "btree" ("shipper_id");



CREATE INDEX "idx_orders_stage" ON "public"."orders" USING "btree" ("stage");



CREATE INDEX "idx_orders_vehicle_type_id" ON "public"."orders" USING "btree" ("vehicle_type_id");



CREATE INDEX "idx_owners_active" ON "public"."owners" USING "btree" ("active");



CREATE INDEX "idx_owners_name" ON "public"."owners" USING "btree" ("name");



CREATE INDEX "idx_partner_quotes_created" ON "public"."partner_quotes" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_partner_quotes_shipper" ON "public"."partner_quotes" USING "btree" ("shipper_id");



CREATE INDEX "idx_partner_quotes_user" ON "public"."partner_quotes" USING "btree" ("user_id");



CREATE INDEX "idx_partner_users_shipper_id" ON "public"."partner_users" USING "btree" ("shipper_id");



CREATE INDEX "idx_petrobras_diesel_uf_fetched" ON "public"."petrobras_diesel_prices" USING "btree" ("uf", "fetched_at" DESC);



CREATE INDEX "idx_price_table_rows_cover" ON "public"."price_table_rows" USING "btree" ("km_from" DESC, "km_to") INCLUDE ("price_table_id") WHERE ("price_table_id" IS NOT NULL);



CREATE INDEX "idx_price_table_rows_table_km_range" ON "public"."price_table_rows" USING "btree" ("price_table_id", "km_from", "km_to");



CREATE INDEX "idx_price_tables_active" ON "public"."price_tables" USING "btree" ("active");



CREATE INDEX "idx_price_tables_validity" ON "public"."price_tables" USING "btree" ("valid_from", "valid_until");



CREATE INDEX "idx_pricing_rules_lookup" ON "public"."pricing_rules_config" USING "btree" ("key", "vehicle_type_id") WHERE ("is_active" = true);



CREATE INDEX "idx_product_dimensions_codigo" ON "public"."product_dimensions" USING "btree" ("codigo_base");



CREATE INDEX "idx_product_dimensions_supplier" ON "public"."product_dimensions" USING "btree" ("supplier");



CREATE INDEX "idx_profiles_perfil" ON "public"."profiles" USING "btree" ("perfil");



CREATE INDEX "idx_profiles_user_id" ON "public"."profiles" USING "btree" ("user_id");



CREATE INDEX "idx_quote_contracts_quote_id" ON "public"."quote_contracts" USING "btree" ("quote_id", "version" DESC);



CREATE INDEX "idx_quote_route_stops_quote_id" ON "public"."quote_route_stops" USING "btree" ("quote_id");



CREATE INDEX "idx_quote_route_stops_sequence" ON "public"."quote_route_stops" USING "btree" ("quote_id", "sequence");



CREATE INDEX "idx_quotes_approval_status" ON "public"."quotes" USING "btree" ("approval_status") WHERE ("approval_status" IS NOT NULL);



CREATE INDEX "idx_quotes_client_id" ON "public"."quotes" USING "btree" ("client_id");



CREATE INDEX "idx_quotes_created_by" ON "public"."quotes" USING "btree" ("created_by");



CREATE INDEX "idx_quotes_estimated_loading_date" ON "public"."quotes" USING "btree" ("estimated_loading_date") WHERE ("estimated_loading_date" IS NOT NULL);



CREATE INDEX "idx_quotes_payment_term_id" ON "public"."quotes" USING "btree" ("payment_term_id");



CREATE INDEX "idx_quotes_price_table_id" ON "public"."quotes" USING "btree" ("price_table_id");



CREATE INDEX "idx_quotes_resend_email_id_not_null" ON "public"."quotes" USING "btree" ("resend_email_id") WHERE ("resend_email_id" IS NOT NULL);



CREATE INDEX "idx_quotes_shipper_id" ON "public"."quotes" USING "btree" ("shipper_id");



CREATE INDEX "idx_quotes_stage" ON "public"."quotes" USING "btree" ("stage");



CREATE INDEX "idx_quotes_vehicle_type_id" ON "public"."quotes" USING "btree" ("vehicle_type_id");



CREATE UNIQUE INDEX "idx_regulatory_updates_dedup" ON "public"."regulatory_updates" USING "btree" ("source", "url") WHERE ("url" IS NOT NULL);



CREATE INDEX "idx_regulatory_updates_source" ON "public"."regulatory_updates" USING "btree" ("source", "created_at" DESC);



CREATE UNIQUE INDEX "idx_regulatory_updates_source_name_url" ON "public"."regulatory_updates" USING "btree" ("source_name", "source_url") WHERE ("source_url" IS NOT NULL);



CREATE INDEX "idx_regulatory_updates_source_url" ON "public"."regulatory_updates" USING "btree" ("source_url");



CREATE INDEX "idx_risk_costs_evaluation_id" ON "public"."risk_costs" USING "btree" ("evaluation_id");



CREATE INDEX "idx_risk_costs_order" ON "public"."risk_costs" USING "btree" ("order_id");



CREATE INDEX "idx_risk_costs_service_id" ON "public"."risk_costs" USING "btree" ("service_id");



CREATE INDEX "idx_risk_costs_trip" ON "public"."risk_costs" USING "btree" ("trip_id");



CREATE UNIQUE INDEX "idx_risk_evaluations_active" ON "public"."risk_evaluations" USING "btree" ("entity_type", "entity_id") WHERE ("status" <> ALL (ARRAY['expired'::"public"."risk_evaluation_status", 'rejected'::"public"."risk_evaluation_status"]));



CREATE INDEX "idx_risk_evaluations_entity_status" ON "public"."risk_evaluations" USING "btree" ("entity_type", "entity_id", "status");



CREATE INDEX "idx_risk_evaluations_policy_id" ON "public"."risk_evaluations" USING "btree" ("policy_id");



CREATE INDEX "idx_risk_evaluations_status" ON "public"."risk_evaluations" USING "btree" ("status");



CREATE INDEX "idx_risk_evidence_document_id" ON "public"."risk_evidence" USING "btree" ("document_id");



CREATE INDEX "idx_risk_evidence_evaluation" ON "public"."risk_evidence" USING "btree" ("evaluation_id");



CREATE INDEX "idx_risk_evidence_type" ON "public"."risk_evidence" USING "btree" ("evidence_type");



CREATE INDEX "idx_risk_policy_rules_policy" ON "public"."risk_policy_rules" USING "btree" ("policy_id");



CREATE INDEX "idx_risk_policy_rules_trigger" ON "public"."risk_policy_rules" USING "btree" ("trigger_type");



CREATE INDEX "idx_route_overrides_active" ON "public"."pricing_route_overrides" USING "btree" ("origin_uf", "destination_uf", "is_active");



CREATE INDEX "idx_route_overrides_cities" ON "public"."pricing_route_overrides" USING "btree" ("origin_city", "destination_city", "modality", "is_active");



CREATE INDEX "idx_sequences_quote" ON "public"."driver_offer_sequences" USING "btree" ("quote_id");



CREATE INDEX "idx_sequences_status" ON "public"."driver_offer_sequences" USING "btree" ("status");



CREATE INDEX "idx_shippers_name" ON "public"."shippers" USING "btree" ("name");



CREATE INDEX "idx_toll_routes_vehicle_type_id" ON "public"."toll_routes" USING "btree" ("vehicle_type_id");



CREATE INDEX "idx_transitions_from" ON "public"."workflow_transitions" USING "btree" ("workflow_id", "from_stage");



CREATE INDEX "idx_transitions_workflow" ON "public"."workflow_transitions" USING "btree" ("workflow_id");



CREATE INDEX "idx_trips_vehicle_type_id" ON "public"."trips" USING "btree" ("vehicle_type_id");



CREATE INDEX "idx_user_roles_role" ON "public"."user_roles" USING "btree" ("role");



CREATE INDEX "idx_user_roles_user_id" ON "public"."user_roles" USING "btree" ("user_id");



CREATE INDEX "idx_vehicles_active" ON "public"."vehicles" USING "btree" ("active");



CREATE INDEX "idx_vehicles_driver_id" ON "public"."vehicles" USING "btree" ("driver_id");



CREATE INDEX "idx_vehicles_owner_id" ON "public"."vehicles" USING "btree" ("owner_id");



CREATE INDEX "idx_vehicles_plate" ON "public"."vehicles" USING "btree" ("plate");



CREATE UNIQUE INDEX "idx_vehicles_renavam_unique" ON "public"."vehicles" USING "btree" ("renavam") WHERE ("renavam" IS NOT NULL);



CREATE INDEX "idx_vehicles_vehicle_type_id" ON "public"."vehicles" USING "btree" ("vehicle_type_id");



CREATE INDEX "idx_vm_has_ciot" ON "public"."vectra_manifestos" USING "btree" ("has_ciot");



CREATE INDEX "idx_vm_motorista" ON "public"."vectra_manifestos" USING "btree" ("motorista");



CREATE INDEX "idx_vm_tipo" ON "public"."vectra_manifestos" USING "btree" ("tipo");



CREATE INDEX "idx_vmm_margem_pct" ON "public"."vectra_motoristas_margem" USING "btree" ("margem_pct");



CREATE INDEX "idx_vmm_motorista" ON "public"."vectra_motoristas_margem" USING "btree" ("motorista");



CREATE INDEX "idx_vrr_rota" ON "public"."vectra_rentabilidade_rotas" USING "btree" ("rota");



CREATE INDEX "idx_waiting_time_rules_vehicle_type_id" ON "public"."waiting_time_rules" USING "btree" ("vehicle_type_id");



CREATE INDEX "idx_workflow_event_logs_event" ON "public"."workflow_event_logs" USING "btree" ("event_id");



CREATE INDEX "idx_workflow_events_deferred" ON "public"."workflow_events" USING "btree" ("status", "execute_after") WHERE (("status" = 'pending'::"text") AND ("execute_after" IS NOT NULL));



CREATE INDEX "idx_workflow_events_entity" ON "public"."workflow_events" USING "btree" ("entity_type", "entity_id");



CREATE INDEX "idx_workflow_events_pending" ON "public"."workflow_events" USING "btree" ("status", "created_at") WHERE ("status" = 'pending'::"text");



CREATE INDEX "insurance_logs_created_at_idx" ON "public"."insurance_logs" USING "btree" ("created_at" DESC);



CREATE INDEX "insurance_logs_prod_created_status_idx" ON "public"."insurance_logs" USING "btree" ("created_at" DESC, "status") WHERE ("environment" = 'prod'::"text");



CREATE INDEX "insurance_logs_request_id_idx" ON "public"."insurance_logs" USING "btree" ("request_id");



CREATE INDEX "insurance_logs_status_idx" ON "public"."insurance_logs" USING "btree" ("status");



CREATE INDEX "ix_documents_trip_id" ON "public"."documents" USING "btree" ("trip_id");



CREATE INDEX "ix_order_gris_services_order" ON "public"."order_gris_services" USING "btree" ("order_id");



CREATE INDEX "ix_orders_driver_id" ON "public"."orders" USING "btree" ("driver_id");



CREATE INDEX "ix_orders_trip_id" ON "public"."orders" USING "btree" ("trip_id");



CREATE INDEX "ix_payment_proofs_order" ON "public"."payment_proofs" USING "btree" ("order_id");



CREATE INDEX "ix_payment_proofs_trip" ON "public"."payment_proofs" USING "btree" ("trip_id");



CREATE INDEX "ix_quote_payment_proofs_quote" ON "public"."quote_payment_proofs" USING "btree" ("quote_id");



CREATE INDEX "ix_trip_cost_items_order" ON "public"."trip_cost_items" USING "btree" ("order_id");



CREATE INDEX "ix_trip_cost_items_trip_scope" ON "public"."trip_cost_items" USING "btree" ("trip_id", "scope");



CREATE INDEX "ix_trip_orders_order" ON "public"."trip_orders" USING "btree" ("order_id");



CREATE INDEX "ix_trip_orders_trip" ON "public"."trip_orders" USING "btree" ("trip_id");



CREATE INDEX "ix_trips_financial_status" ON "public"."trips" USING "btree" ("financial_status");



CREATE INDEX "ix_trips_plate_driver_status" ON "public"."trips" USING "btree" ("vehicle_plate", "driver_id", "status_operational");



CREATE INDEX "route_metrics_config_vehicle_type_idx" ON "public"."route_metrics_config" USING "btree" ("vehicle_type_id");



CREATE UNIQUE INDEX "uq_route_override_v2" ON "public"."pricing_route_overrides" USING "btree" (COALESCE("origin_city", ("origin_uf")::"text"), COALESCE("destination_city", ("destination_uf")::"text"), "modality", COALESCE("cargo_type", 'geral'::"text")) WHERE ("is_active" = true);



CREATE INDEX "adapter_catalog_company_active_idx" ON "vectraclip"."adapter_catalog" USING "btree" ("company_id", "is_active");



CREATE INDEX "adapter_field_definitions_adapter_active_idx" ON "vectraclip"."adapter_field_definitions" USING "btree" ("adapter_id", "is_active", "sort_order");



CREATE INDEX "adapter_field_definitions_company_adapter_idx" ON "vectraclip"."adapter_field_definitions" USING "btree" ("company_id", "adapter_id");



CREATE INDEX "agent_adapter_configs_adapter_idx" ON "vectraclip"."agent_adapter_configs" USING "btree" ("adapter_id");



CREATE INDEX "agent_adapter_configs_company_agent_idx" ON "vectraclip"."agent_adapter_configs" USING "btree" ("company_id", "agent_id");



CREATE INDEX "agent_execution_configs_agent_idx" ON "vectraclip"."agent_execution_configs" USING "btree" ("agent_id");



CREATE INDEX "agent_execution_configs_company_active_idx" ON "vectraclip"."agent_execution_configs" USING "btree" ("company_id", "is_active");



CREATE INDEX "agent_specialties_is_active_idx" ON "vectraclip"."agent_specialties" USING "btree" ("is_active");



CREATE INDEX "agent_specialty_configs_company_id_idx" ON "vectraclip"."agent_specialty_configs" USING "btree" ("company_id");



CREATE INDEX "goals_company_id_idx" ON "vectraclip"."goals" USING "btree" ("company_id");



CREATE INDEX "goals_parent_goal_id_idx" ON "vectraclip"."goals" USING "btree" ("parent_goal_id");



CREATE INDEX "heartbeats_model_id_idx" ON "vectraclip"."heartbeats" USING "btree" ("model_id");



CREATE INDEX "hermes_sender_whitelist_company_active_idx" ON "vectraclip"."hermes_sender_whitelist" USING "btree" ("company_id", "is_active");



CREATE INDEX "idx_approvals_company_created_at" ON "vectraclip"."approvals" USING "btree" ("company_id", "created_at" DESC);



CREATE INDEX "idx_approvals_request_type" ON "vectraclip"."approvals" USING "btree" ("request_type");



CREATE INDEX "idx_approvals_status" ON "vectraclip"."approvals" USING "btree" ("status");



CREATE INDEX "idx_companies_owner_user_id" ON "vectraclip"."companies" USING "btree" ("owner_user_id");



CREATE INDEX "idx_kronos_rules_type_active_prio" ON "vectraclip"."kronos_rules" USING "btree" ("type", "is_active", "priority");



CREATE INDEX "idx_projects_archived_at" ON "vectraclip"."projects" USING "btree" ("archived_at") WHERE ("archived_at" IS NOT NULL);



CREATE INDEX "idx_projects_company" ON "vectraclip"."projects" USING "btree" ("company_id");



CREATE INDEX "idx_prospect_profiles_cnpj" ON "vectraclip"."prospect_profiles" USING "btree" ("cnpj") WHERE ("cnpj" IS NOT NULL);



CREATE INDEX "idx_prospect_profiles_company" ON "vectraclip"."prospect_profiles" USING "btree" ("company_id");



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



CREATE INDEX "routines_company_id_idx" ON "vectraclip"."routines" USING "btree" ("company_id");



CREATE INDEX "rte_created_at_idx" ON "vectraclip"."run_transcript_entries" USING "btree" ("run_id", "created_at");



CREATE INDEX "rte_run_id_idx" ON "vectraclip"."run_transcript_entries" USING "btree" ("run_id");



CREATE INDEX "runs_agent_id_idx" ON "vectraclip"."runs" USING "btree" ("agent_id");



CREATE INDEX "runs_company_id_idx" ON "vectraclip"."runs" USING "btree" ("company_id");



CREATE INDEX "runs_routine_id_idx" ON "vectraclip"."runs" USING "btree" ("routine_id");



CREATE INDEX "runs_started_at_idx" ON "vectraclip"."runs" USING "btree" ("started_at" DESC);



CREATE INDEX "tasks_operation_type_idx" ON "vectraclip"."tasks" USING "btree" ("operation_type");



CREATE INDEX "tasks_workflow_step_id_idx" ON "vectraclip"."tasks" USING "btree" ("workflow_step_id") WHERE ("workflow_step_id" IS NOT NULL);



CREATE INDEX "workflow_definitions_company_active_idx" ON "vectraclip"."workflow_definitions" USING "btree" ("company_id", "is_active");



CREATE INDEX "workflow_steps_op_type_active_idx" ON "vectraclip"."workflow_steps" USING "btree" ("current_operation_type", "active") WHERE ("current_operation_type" IS NOT NULL);



CREATE INDEX "workflow_steps_workflow_order_idx" ON "vectraclip"."workflow_steps" USING "btree" ("workflow_id", "step_order");



CREATE OR REPLACE TRIGGER "audit_clients_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."clients" FOR EACH ROW EXECUTE FUNCTION "public"."audit_trigger_func"();



CREATE OR REPLACE TRIGGER "audit_occurrences_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."occurrences" FOR EACH ROW EXECUTE FUNCTION "public"."audit_trigger_func"();



CREATE OR REPLACE TRIGGER "audit_orders_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."audit_trigger_func"();



CREATE OR REPLACE TRIGGER "audit_quotes_trigger" AFTER INSERT OR DELETE OR UPDATE ON "public"."quotes" FOR EACH ROW EXECUTE FUNCTION "public"."audit_trigger_func"();



CREATE OR REPLACE TRIGGER "collection_orders_set_updated_at" BEFORE UPDATE ON "public"."collection_orders" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "company_settings_updated_at" BEFORE UPDATE ON "public"."company_settings" FOR EACH ROW EXECUTE FUNCTION "public"."update_company_settings_updated_at"();



CREATE OR REPLACE TRIGGER "identify_consolidation_trigger" AFTER INSERT OR UPDATE ON "public"."quotes" FOR EACH ROW EXECUTE FUNCTION "public"."tr_identify_consolidation_v7"();



CREATE OR REPLACE TRIGGER "load_composition_suggestions_updated_at_trigger" BEFORE UPDATE ON "public"."load_composition_suggestions" FOR EACH ROW EXECUTE FUNCTION "public"."update_load_composition_updated_at"();



CREATE OR REPLACE TRIGGER "quote_contracts_updated_at" BEFORE UPDATE ON "public"."quote_contracts" FOR EACH ROW EXECUTE FUNCTION "public"."update_quote_contracts_updated_at"();



CREATE OR REPLACE TRIGGER "set_order_os_number" BEFORE INSERT ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."set_os_number"();



CREATE OR REPLACE TRIGGER "set_quote_code" BEFORE INSERT ON "public"."quotes" FOR EACH ROW EXECUTE FUNCTION "public"."set_quote_code"();



CREATE OR REPLACE TRIGGER "shippers_set_updated_at" BEFORE UPDATE ON "public"."shippers" FOR EACH ROW EXECUTE FUNCTION "public"."set_updated_at"();



CREATE OR REPLACE TRIGGER "trg_auto_group_order_to_trip" AFTER UPDATE OF "stage" ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."try_auto_group_order_to_trip"();



CREATE OR REPLACE TRIGGER "trg_collected_data_enqueue" AFTER INSERT ON "public"."collected_data" FOR EACH ROW EXECUTE FUNCTION "public"."enqueue_agent_job"();



CREATE OR REPLACE TRIGGER "trg_delivery_assessments_updated_at" BEFORE UPDATE ON "public"."delivery_assessments" FOR EACH ROW EXECUTE FUNCTION "public"."update_delivery_assessments_updated_at"();



CREATE OR REPLACE TRIGGER "trg_driver_qualification_updated_at" BEFORE UPDATE ON "public"."driver_qualifications" FOR EACH ROW EXECUTE FUNCTION "public"."update_driver_qualification_updated_at"();



CREATE OR REPLACE TRIGGER "trg_emit_approval_decided_event" AFTER UPDATE OF "status" ON "public"."approval_requests" FOR EACH ROW EXECUTE FUNCTION "public"."emit_approval_decided_event"();



CREATE OR REPLACE TRIGGER "trg_emit_document_uploaded_event" AFTER INSERT ON "public"."documents" FOR EACH ROW EXECUTE FUNCTION "public"."emit_document_uploaded_event"();



CREATE OR REPLACE TRIGGER "trg_emit_financial_status_event" AFTER UPDATE OF "status" ON "public"."financial_documents" FOR EACH ROW EXECUTE FUNCTION "public"."emit_financial_status_event"();



CREATE OR REPLACE TRIGGER "trg_emit_order_created_event" AFTER INSERT ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."emit_order_created_event"();



CREATE OR REPLACE TRIGGER "trg_emit_order_stage_event" AFTER UPDATE OF "stage" ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."emit_order_stage_event"();



CREATE OR REPLACE TRIGGER "trg_emit_quote_stage_event" AFTER UPDATE OF "stage" ON "public"."quotes" FOR EACH ROW EXECUTE FUNCTION "public"."emit_quote_stage_event"();



CREATE OR REPLACE TRIGGER "trg_enforce_pod_before_entregue" BEFORE INSERT OR UPDATE OF "stage", "has_pod" ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."enforce_pod_before_entregue"();



CREATE OR REPLACE TRIGGER "trg_market_indices_updated_at" BEFORE UPDATE ON "public"."market_indices" FOR EACH ROW EXECUTE FUNCTION "public"."set_updated_at"();



CREATE OR REPLACE TRIGGER "trg_normalize_clients" BEFORE INSERT OR UPDATE ON "public"."clients" FOR EACH ROW EXECUTE FUNCTION "public"."normalize_clients"();



CREATE OR REPLACE TRIGGER "trg_normalize_owners" BEFORE INSERT OR UPDATE ON "public"."owners" FOR EACH ROW EXECUTE FUNCTION "public"."normalize_owners"();



CREATE OR REPLACE TRIGGER "trg_normalize_vehicles" BEFORE INSERT OR UPDATE ON "public"."vehicles" FOR EACH ROW EXECUTE FUNCTION "public"."normalize_vehicles"();



CREATE OR REPLACE TRIGGER "trg_price_table_rows_no_overlap" BEFORE INSERT OR UPDATE ON "public"."price_table_rows" FOR EACH ROW EXECUTE FUNCTION "public"."price_table_rows_no_overlap"();



CREATE OR REPLACE TRIGGER "trg_price_tables_set_updated_at" BEFORE UPDATE ON "public"."price_tables" FOR EACH ROW EXECUTE FUNCTION "public"."set_updated_at"();



CREATE OR REPLACE TRIGGER "trg_pricing_route_overrides_updated_at" BEFORE UPDATE ON "public"."pricing_route_overrides" FOR EACH ROW EXECUTE FUNCTION "public"."update_pricing_route_overrides_updated_at"();



CREATE OR REPLACE TRIGGER "trg_risk_evaluation_approved" AFTER UPDATE ON "public"."risk_evaluations" FOR EACH ROW EXECUTE FUNCTION "public"."fn_risk_evaluation_approved"();



CREATE OR REPLACE TRIGGER "trg_route_metrics_config_updated_at" BEFORE UPDATE ON "public"."route_metrics_config" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "trg_sequences_updated_at" BEFORE UPDATE ON "public"."driver_offer_sequences" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "trg_sync_financial_doc_amount" AFTER UPDATE OF "carreteiro_real" ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."sync_financial_doc_amount_on_carreteiro_change"();



CREATE OR REPLACE TRIGGER "trg_uppercase_clients" BEFORE INSERT OR UPDATE ON "public"."clients" FOR EACH ROW EXECUTE FUNCTION "public"."enforce_uppercase_clients"();



CREATE OR REPLACE TRIGGER "trg_uppercase_drivers" BEFORE INSERT OR UPDATE ON "public"."drivers" FOR EACH ROW EXECUTE FUNCTION "public"."enforce_uppercase_drivers"();



CREATE OR REPLACE TRIGGER "trg_uppercase_owners" BEFORE INSERT OR UPDATE ON "public"."owners" FOR EACH ROW EXECUTE FUNCTION "public"."enforce_uppercase_owners"();



CREATE OR REPLACE TRIGGER "update_antt_floor_rates_updated_at" BEFORE UPDATE ON "public"."antt_floor_rates" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_approval_requests_updated_at" BEFORE UPDATE ON "public"."approval_requests" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_clients_updated_at" BEFORE UPDATE ON "public"."clients" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_conditional_fees_updated_at" BEFORE UPDATE ON "public"."conditional_fees" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_delivery_conditions_updated_at" BEFORE UPDATE ON "public"."delivery_conditions" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_discharge_checklist_items_updated_at" BEFORE UPDATE ON "public"."discharge_checklist_items" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_discount_breakdown_timestamp" BEFORE UPDATE ON "public"."load_composition_discount_breakdown" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_documents_updated_at" BEFORE UPDATE ON "public"."documents" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_drivers_updated_at" BEFORE UPDATE ON "public"."drivers" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_financial_documents_updated_at" BEFORE UPDATE ON "public"."financial_documents" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_financial_installments_updated_at" BEFORE UPDATE ON "public"."financial_installments" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_icms_rates_updated_at" BEFORE UPDATE ON "public"."icms_rates" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ntc_cost_indices_updated_at" BEFORE UPDATE ON "public"."ntc_cost_indices" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ntc_fuel_reference_updated_at" BEFORE UPDATE ON "public"."ntc_fuel_reference" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_occurrences_updated_at" BEFORE UPDATE ON "public"."occurrences" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_orders_updated_at" BEFORE UPDATE ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_owners_updated_at" BEFORE UPDATE ON "public"."owners" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_payment_proofs_updated_at" BEFORE UPDATE ON "public"."payment_proofs" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_payment_terms_updated_at" BEFORE UPDATE ON "public"."payment_terms" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pricing_parameters_updated_at" BEFORE UPDATE ON "public"."pricing_parameters" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_processes_modtime" BEFORE UPDATE ON "public"."processes" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_profiles_updated_at" BEFORE UPDATE ON "public"."profiles" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_quote_payment_proofs_updated_at" BEFORE UPDATE ON "public"."quote_payment_proofs" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_quotes_updated_at" BEFORE UPDATE ON "public"."quotes" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_shippers_updated_at" BEFORE UPDATE ON "public"."shippers" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_sipoc_maps_modtime" BEFORE UPDATE ON "public"."sipoc_maps" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_tac_rates_updated_at" BEFORE UPDATE ON "public"."tac_rates" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_toll_routes_updated_at" BEFORE UPDATE ON "public"."toll_routes" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_trip_cost_items_updated_at" BEFORE UPDATE ON "public"."trip_cost_items" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_trips_updated_at" BEFORE UPDATE ON "public"."trips" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_vehicle_types_updated_at" BEFORE UPDATE ON "public"."vehicle_types" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_vehicles_updated_at" BEFORE UPDATE ON "public"."vehicles" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_waiting_time_rules_updated_at" BEFORE UPDATE ON "public"."waiting_time_rules" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "set_updated_at_agents" BEFORE UPDATE ON "vectraclip"."agents" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_app_users" BEFORE UPDATE ON "vectraclip"."app_users" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_companies" BEFORE UPDATE ON "vectraclip"."companies" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_heartbeats" BEFORE UPDATE ON "vectraclip"."heartbeats" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "set_updated_at_prospect_profiles" BEFORE UPDATE ON "vectraclip"."prospect_profiles" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_companies" BEFORE UPDATE ON "vectraclip"."sipoc_companies" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_components" BEFORE UPDATE ON "vectraclip"."sipoc_components" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_positions" BEFORE UPDATE ON "vectraclip"."sipoc_positions" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_processes" BEFORE UPDATE ON "vectraclip"."sipoc_processes" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_sector_baselines" BEFORE UPDATE ON "vectraclip"."sipoc_sector_baselines" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_sipoc_sectors" BEFORE UPDATE ON "vectraclip"."sipoc_sectors" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at_tasks" BEFORE UPDATE ON "vectraclip"."tasks" FOR EACH ROW EXECUTE FUNCTION "public"."moddatetime"('updated_at');



CREATE OR REPLACE TRIGGER "tasks_parent_cycle_guard" BEFORE INSERT OR UPDATE OF "parent_task_id" ON "vectraclip"."tasks" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."tasks_prevent_parent_cycle"();



CREATE OR REPLACE TRIGGER "trg_agent_execution_configs_sync_company_agent" BEFORE INSERT OR UPDATE OF "company_id", "agent_id" ON "vectraclip"."agent_execution_configs" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."agent_execution_configs_sync_company_agent"();



CREATE OR REPLACE TRIGGER "trg_heartbeats_validate_model_id" BEFORE INSERT OR UPDATE OF "model_id" ON "vectraclip"."heartbeats" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."validate_heartbeat_model_id"();



CREATE OR REPLACE TRIGGER "trg_kronos_rules_updated_at" BEFORE UPDATE ON "vectraclip"."kronos_rules" FOR EACH ROW EXECUTE FUNCTION "vectraclip"."set_kronos_rules_updated_at"();



ALTER TABLE ONLY "public"."agent_jobs"
    ADD CONSTRAINT "agent_jobs_collected_data_id_fkey" FOREIGN KEY ("collected_data_id") REFERENCES "public"."collected_data"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ai_budget_config"
    ADD CONSTRAINT "ai_budget_config_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."antt_violation_alerts"
    ADD CONSTRAINT "antt_violation_alerts_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."antt_violation_alerts"
    ADD CONSTRAINT "antt_violation_alerts_resolved_by_fkey" FOREIGN KEY ("resolved_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."audit_logs"
    ADD CONSTRAINT "audit_logs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."clients"
    ADD CONSTRAINT "clients_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."clients"
    ADD CONSTRAINT "clients_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."collected_data"
    ADD CONSTRAINT "collected_data_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."collection_orders"
    ADD CONSTRAINT "collection_orders_cancelled_by_fkey" FOREIGN KEY ("cancelled_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."collection_orders"
    ADD CONSTRAINT "collection_orders_issued_by_fkey" FOREIGN KEY ("issued_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."collection_orders"
    ADD CONSTRAINT "collection_orders_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."commercial_closeout_events"
    ADD CONSTRAINT "commercial_closeout_events_message_event_id_fkey" FOREIGN KEY ("message_event_id") REFERENCES "public"."commercial_message_events"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."commercial_closeout_events"
    ADD CONSTRAINT "commercial_closeout_events_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."commercial_followup_runs"
    ADD CONSTRAINT "commercial_followup_runs_notification_log_id_fkey" FOREIGN KEY ("notification_log_id") REFERENCES "public"."notification_logs"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."commercial_followup_runs"
    ADD CONSTRAINT "commercial_followup_runs_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."commercial_followup_runs"
    ADD CONSTRAINT "commercial_followup_runs_rule_id_fkey" FOREIGN KEY ("rule_id") REFERENCES "public"."commercial_followup_rules"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."commercial_message_events"
    ADD CONSTRAINT "commercial_message_events_client_id_fkey" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."commercial_message_events"
    ADD CONSTRAINT "commercial_message_events_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."commercial_message_events"
    ADD CONSTRAINT "commercial_message_events_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."shippers"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."commercial_operational_handoffs"
    ADD CONSTRAINT "commercial_operational_handoffs_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."commercial_operational_handoffs"
    ADD CONSTRAINT "commercial_operational_handoffs_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."compliance_checks"
    ADD CONSTRAINT "compliance_checks_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."delivery_assessments"
    ADD CONSTRAINT "delivery_assessments_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."delivery_assessments"
    ADD CONSTRAINT "delivery_assessments_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_trip_id_fkey" FOREIGN KEY ("trip_id") REFERENCES "public"."trips"("id");



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_uploaded_by_fkey" FOREIGN KEY ("uploaded_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "driver_offer_sequences_accepted_driver_id_fkey" FOREIGN KEY ("accepted_driver_id") REFERENCES "public"."drivers"("id");



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "driver_offer_sequences_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "driver_offer_sequences_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "driver_offer_sequences_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "driver_offer_sequences_trip_id_fkey" FOREIGN KEY ("trip_id") REFERENCES "public"."trips"("id");



ALTER TABLE ONLY "public"."driver_offer_sequences"
    ADD CONSTRAINT "driver_offer_sequences_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id");



ALTER TABLE ONLY "public"."driver_offers"
    ADD CONSTRAINT "driver_offers_driver_id_fkey" FOREIGN KEY ("driver_id") REFERENCES "public"."drivers"("id");



ALTER TABLE ONLY "public"."driver_offers"
    ADD CONSTRAINT "driver_offers_sequence_id_fkey" FOREIGN KEY ("sequence_id") REFERENCES "public"."driver_offer_sequences"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."driver_qualifications"
    ADD CONSTRAINT "driver_qualifications_decided_by_fkey" FOREIGN KEY ("decided_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."driver_qualifications"
    ADD CONSTRAINT "driver_qualifications_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."drivers"
    ADD CONSTRAINT "drivers_cnh_category_fk" FOREIGN KEY ("cnh_category") REFERENCES "public"."cnh_categories"("code") ON UPDATE CASCADE ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."financial_documents"
    ADD CONSTRAINT "financial_documents_owner_id_fkey" FOREIGN KEY ("owner_id") REFERENCES "public"."owners"("id");



ALTER TABLE ONLY "public"."financial_installments"
    ADD CONSTRAINT "financial_installments_financial_document_id_fkey" FOREIGN KEY ("financial_document_id") REFERENCES "public"."financial_documents"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."icms_rates"
    ADD CONSTRAINT "icms_rates_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."load_composition_discount_breakdown"
    ADD CONSTRAINT "load_composition_discount_breakdown_composition_id_fkey" FOREIGN KEY ("composition_id") REFERENCES "public"."load_composition_suggestions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."load_composition_discount_breakdown"
    ADD CONSTRAINT "load_composition_discount_breakdown_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."load_composition_discount_breakdown"
    ADD CONSTRAINT "load_composition_discount_breakdown_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."load_composition_discount_breakdown"
    ADD CONSTRAINT "load_composition_discount_breakdown_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."shippers"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."load_composition_metrics"
    ADD CONSTRAINT "load_composition_metrics_composition_id_fkey" FOREIGN KEY ("composition_id") REFERENCES "public"."load_composition_suggestions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."load_composition_routings"
    ADD CONSTRAINT "load_composition_routings_composition_id_fkey" FOREIGN KEY ("composition_id") REFERENCES "public"."load_composition_suggestions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."load_composition_routings"
    ADD CONSTRAINT "load_composition_routings_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."load_composition_suggestions"
    ADD CONSTRAINT "load_composition_suggestions_anchor_quote_id_fkey" FOREIGN KEY ("anchor_quote_id") REFERENCES "public"."quotes"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."load_composition_suggestions"
    ADD CONSTRAINT "load_composition_suggestions_approved_by_fkey" FOREIGN KEY ("approved_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."load_composition_suggestions"
    ADD CONSTRAINT "load_composition_suggestions_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."load_composition_suggestions"
    ADD CONSTRAINT "load_composition_suggestions_created_order_id_fkey" FOREIGN KEY ("created_order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."load_composition_suggestions"
    ADD CONSTRAINT "load_composition_suggestions_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."shippers"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."load_composition_suggestions"
    ADD CONSTRAINT "load_composition_suggestions_suggested_vehicle_type_id_fkey" FOREIGN KEY ("suggested_vehicle_type_id") REFERENCES "public"."vehicle_types"("id");



ALTER TABLE ONLY "public"."mirofish_recommendations"
    ADD CONSTRAINT "mirofish_recommendations_report_id_fkey" FOREIGN KEY ("report_id") REFERENCES "public"."mirofish_reports"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."mirofish_route_insights"
    ADD CONSTRAINT "mirofish_route_insights_report_id_fkey" FOREIGN KEY ("report_id") REFERENCES "public"."mirofish_reports"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."mirofish_shipper_insights"
    ADD CONSTRAINT "mirofish_shipper_insights_report_id_fkey" FOREIGN KEY ("report_id") REFERENCES "public"."mirofish_reports"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."mirofish_shipper_insights"
    ADD CONSTRAINT "mirofish_shipper_insights_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."shippers"("id");



ALTER TABLE ONLY "public"."occurrences"
    ADD CONSTRAINT "occurrences_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."occurrences"
    ADD CONSTRAINT "occurrences_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."occurrences"
    ADD CONSTRAINT "occurrences_resolved_by_fkey" FOREIGN KEY ("resolved_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."order_gris_services"
    ADD CONSTRAINT "order_gris_services_gris_service_id_fkey" FOREIGN KEY ("gris_service_id") REFERENCES "public"."gris_services"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."order_gris_services"
    ADD CONSTRAINT "order_gris_services_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_assigned_to_fkey" FOREIGN KEY ("assigned_to") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_carrier_payment_term_id_fkey" FOREIGN KEY ("carrier_payment_term_id") REFERENCES "public"."payment_terms"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_client_id_fkey" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_driver_id_fkey" FOREIGN KEY ("driver_id") REFERENCES "public"."drivers"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_payment_term_id_fkey" FOREIGN KEY ("payment_term_id") REFERENCES "public"."payment_terms"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_price_table_id_fkey" FOREIGN KEY ("price_table_id") REFERENCES "public"."price_tables"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."shippers"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_trip_id_fkey" FOREIGN KEY ("trip_id") REFERENCES "public"."trips"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id");



ALTER TABLE ONLY "public"."partner_quotes"
    ADD CONSTRAINT "partner_quotes_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."partner_shippers"("id");



ALTER TABLE ONLY "public"."partner_quotes"
    ADD CONSTRAINT "partner_quotes_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."partner_users"("id");



ALTER TABLE ONLY "public"."partner_users"
    ADD CONSTRAINT "partner_users_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."partner_shippers"("id");



ALTER TABLE ONLY "public"."payment_proofs"
    ADD CONSTRAINT "payment_proofs_document_id_fkey" FOREIGN KEY ("document_id") REFERENCES "public"."documents"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."payment_proofs"
    ADD CONSTRAINT "payment_proofs_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."payment_proofs"
    ADD CONSTRAINT "payment_proofs_trip_id_fkey" FOREIGN KEY ("trip_id") REFERENCES "public"."trips"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."price_table_rows"
    ADD CONSTRAINT "price_table_rows_price_table_id_fkey" FOREIGN KEY ("price_table_id") REFERENCES "public"."price_tables"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."price_tables"
    ADD CONSTRAINT "price_tables_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pricing_rules_config"
    ADD CONSTRAINT "pricing_rules_config_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."quote_contracts"
    ADD CONSTRAINT "quote_contracts_generated_by_fkey" FOREIGN KEY ("generated_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."quote_contracts"
    ADD CONSTRAINT "quote_contracts_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."quote_payment_proofs"
    ADD CONSTRAINT "quote_payment_proofs_document_id_fkey" FOREIGN KEY ("document_id") REFERENCES "public"."documents"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."quote_payment_proofs"
    ADD CONSTRAINT "quote_payment_proofs_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."quote_route_stops"
    ADD CONSTRAINT "quote_route_stops_quote_id_fkey" FOREIGN KEY ("quote_id") REFERENCES "public"."quotes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_assigned_to_fkey" FOREIGN KEY ("assigned_to") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_client_id_fkey" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_payment_term_id_fkey" FOREIGN KEY ("payment_term_id") REFERENCES "public"."payment_terms"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_price_table_id_fkey" FOREIGN KEY ("price_table_id") REFERENCES "public"."price_tables"("id");



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_shipper_id_fkey" FOREIGN KEY ("shipper_id") REFERENCES "public"."shippers"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."quotes"
    ADD CONSTRAINT "quotes_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."risk_costs"
    ADD CONSTRAINT "risk_costs_evaluation_id_fkey" FOREIGN KEY ("evaluation_id") REFERENCES "public"."risk_evaluations"("id");



ALTER TABLE ONLY "public"."risk_costs"
    ADD CONSTRAINT "risk_costs_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."risk_costs"
    ADD CONSTRAINT "risk_costs_service_id_fkey" FOREIGN KEY ("service_id") REFERENCES "public"."risk_services_catalog"("id");



ALTER TABLE ONLY "public"."risk_costs"
    ADD CONSTRAINT "risk_costs_trip_id_fkey" FOREIGN KEY ("trip_id") REFERENCES "public"."trips"("id");



ALTER TABLE ONLY "public"."risk_evaluations"
    ADD CONSTRAINT "risk_evaluations_evaluated_by_fkey" FOREIGN KEY ("evaluated_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."risk_evaluations"
    ADD CONSTRAINT "risk_evaluations_policy_id_fkey" FOREIGN KEY ("policy_id") REFERENCES "public"."risk_policies"("id");



ALTER TABLE ONLY "public"."risk_evidence"
    ADD CONSTRAINT "risk_evidence_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."risk_evidence"
    ADD CONSTRAINT "risk_evidence_document_id_fkey" FOREIGN KEY ("document_id") REFERENCES "public"."documents"("id");



ALTER TABLE ONLY "public"."risk_evidence"
    ADD CONSTRAINT "risk_evidence_evaluation_id_fkey" FOREIGN KEY ("evaluation_id") REFERENCES "public"."risk_evaluations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."risk_policies"
    ADD CONSTRAINT "risk_policies_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."risk_policy_rules"
    ADD CONSTRAINT "risk_policy_rules_policy_id_fkey" FOREIGN KEY ("policy_id") REFERENCES "public"."risk_policies"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."route_metrics_config"
    ADD CONSTRAINT "route_metrics_config_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."shippers"
    ADD CONSTRAINT "shippers_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."sipoc_customers"
    ADD CONSTRAINT "sipoc_customers_sipoc_map_id_fkey" FOREIGN KEY ("sipoc_map_id") REFERENCES "public"."sipoc_maps"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sipoc_decisions"
    ADD CONSTRAINT "sipoc_decisions_sipoc_map_id_fkey" FOREIGN KEY ("sipoc_map_id") REFERENCES "public"."sipoc_maps"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sipoc_inputs"
    ADD CONSTRAINT "sipoc_inputs_sipoc_map_id_fkey" FOREIGN KEY ("sipoc_map_id") REFERENCES "public"."sipoc_maps"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sipoc_inputs"
    ADD CONSTRAINT "sipoc_inputs_supplier_id_fkey" FOREIGN KEY ("supplier_id") REFERENCES "public"."sipoc_suppliers"("id");



ALTER TABLE ONLY "public"."sipoc_maps"
    ADD CONSTRAINT "sipoc_maps_process_id_fkey" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sipoc_outputs"
    ADD CONSTRAINT "sipoc_outputs_sipoc_map_id_fkey" FOREIGN KEY ("sipoc_map_id") REFERENCES "public"."sipoc_maps"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sipoc_suppliers"
    ADD CONSTRAINT "sipoc_suppliers_sipoc_map_id_fkey" FOREIGN KEY ("sipoc_map_id") REFERENCES "public"."sipoc_maps"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."skill_executions"
    ADD CONSTRAINT "skill_executions_sipoc_map_id_fkey" FOREIGN KEY ("sipoc_map_id") REFERENCES "public"."sipoc_maps"("id");



ALTER TABLE ONLY "public"."toll_routes"
    ADD CONSTRAINT "toll_routes_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."trip_cost_items"
    ADD CONSTRAINT "trip_cost_items_manually_edited_by_fkey" FOREIGN KEY ("manually_edited_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."trip_cost_items"
    ADD CONSTRAINT "trip_cost_items_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."trip_cost_items"
    ADD CONSTRAINT "trip_cost_items_trip_id_fkey" FOREIGN KEY ("trip_id") REFERENCES "public"."trips"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."trip_orders"
    ADD CONSTRAINT "trip_orders_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."trip_orders"
    ADD CONSTRAINT "trip_orders_trip_id_fkey" FOREIGN KEY ("trip_id") REFERENCES "public"."trips"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."trips"
    ADD CONSTRAINT "trips_closed_by_fkey" FOREIGN KEY ("closed_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."trips"
    ADD CONSTRAINT "trips_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."trips"
    ADD CONSTRAINT "trips_driver_id_fkey" FOREIGN KEY ("driver_id") REFERENCES "public"."drivers"("id");



ALTER TABLE ONLY "public"."trips"
    ADD CONSTRAINT "trips_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id");



ALTER TABLE ONLY "public"."user_roles"
    ADD CONSTRAINT "user_roles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."vehicles"
    ADD CONSTRAINT "vehicles_driver_id_fkey" FOREIGN KEY ("driver_id") REFERENCES "public"."drivers"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."vehicles"
    ADD CONSTRAINT "vehicles_owner_id_fkey" FOREIGN KEY ("owner_id") REFERENCES "public"."owners"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."vehicles"
    ADD CONSTRAINT "vehicles_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id");



ALTER TABLE ONLY "public"."waiting_time_rules"
    ADD CONSTRAINT "waiting_time_rules_vehicle_type_id_fkey" FOREIGN KEY ("vehicle_type_id") REFERENCES "public"."vehicle_types"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."workflow_event_logs"
    ADD CONSTRAINT "workflow_event_logs_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."workflow_events"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."workflow_transitions"
    ADD CONSTRAINT "workflow_transitions_workflow_id_fkey" FOREIGN KEY ("workflow_id") REFERENCES "public"."workflow_definitions"("id") ON DELETE CASCADE;



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



ALTER TABLE ONLY "vectraclip"."agent_specialty_configs"
    ADD CONSTRAINT "agent_specialty_configs_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "vectraclip"."agents"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agent_specialty_configs"
    ADD CONSTRAINT "agent_specialty_configs_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agent_specialty_configs"
    ADD CONSTRAINT "agent_specialty_configs_specialty_id_fkey" FOREIGN KEY ("specialty_id") REFERENCES "vectraclip"."agent_specialties"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."agents"
    ADD CONSTRAINT "agents_reports_to_company_fkey" FOREIGN KEY ("company_id", "reports_to_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."app_users"
    ADD CONSTRAINT "app_users_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."approvals"
    ADD CONSTRAINT "approvals_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."companies"
    ADD CONSTRAINT "companies_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "auth"."users"("id") ON DELETE RESTRICT DEFERRABLE;



ALTER TABLE ONLY "vectraclip"."company_secrets"
    ADD CONSTRAINT "company_secrets_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



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



ALTER TABLE ONLY "vectraclip"."hermes_sender_whitelist"
    ADD CONSTRAINT "hermes_sender_whitelist_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



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



ALTER TABLE ONLY "vectraclip"."projects"
    ADD CONSTRAINT "projects_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."projects"
    ADD CONSTRAINT "projects_lead_agent_id_fkey" FOREIGN KEY ("lead_agent_id") REFERENCES "vectraclip"."agents"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."prospect_profiles"
    ADD CONSTRAINT "prospect_profiles_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."prospect_profiles"
    ADD CONSTRAINT "prospect_profiles_source_task_id_fkey" FOREIGN KEY ("source_task_id") REFERENCES "vectraclip"."tasks"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."routines"
    ADD CONSTRAINT "routines_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "vectraclip"."agents"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."routines"
    ADD CONSTRAINT "routines_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."run_transcript_entries"
    ADD CONSTRAINT "run_transcript_entries_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "vectraclip"."runs"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."runs"
    ADD CONSTRAINT "runs_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "vectraclip"."agents"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."runs"
    ADD CONSTRAINT "runs_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."runs"
    ADD CONSTRAINT "runs_routine_id_fkey" FOREIGN KEY ("routine_id") REFERENCES "vectraclip"."routines"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."runs"
    ADD CONSTRAINT "runs_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "vectraclip"."tasks"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."sipoc_components"
    ADD CONSTRAINT "sipoc_components_process_id_fkey" FOREIGN KEY ("process_id") REFERENCES "vectraclip"."sipoc_processes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_edges"
    ADD CONSTRAINT "sipoc_edges_process_id_fkey" FOREIGN KEY ("process_id") REFERENCES "vectraclip"."sipoc_processes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_edges"
    ADD CONSTRAINT "sipoc_edges_source_id_fkey" FOREIGN KEY ("source_id") REFERENCES "vectraclip"."sipoc_components"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_edges"
    ADD CONSTRAINT "sipoc_edges_target_id_fkey" FOREIGN KEY ("target_id") REFERENCES "vectraclip"."sipoc_components"("id") ON DELETE CASCADE;



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



ALTER TABLE ONLY "vectraclip"."sipoc_raci"
    ADD CONSTRAINT "sipoc_raci_component_id_fkey" FOREIGN KEY ("component_id") REFERENCES "vectraclip"."sipoc_components"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_raci"
    ADD CONSTRAINT "sipoc_raci_position_id_fkey" FOREIGN KEY ("position_id") REFERENCES "vectraclip"."sipoc_positions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_raci"
    ADD CONSTRAINT "sipoc_raci_process_id_fkey" FOREIGN KEY ("process_id") REFERENCES "vectraclip"."sipoc_processes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."sipoc_companies"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."sipoc_sectors"
    ADD CONSTRAINT "sipoc_sectors_parent_sector_id_fkey" FOREIGN KEY ("parent_sector_id") REFERENCES "vectraclip"."sipoc_sectors"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_assigned_agent_company_fkey" FOREIGN KEY ("company_id", "assigned_to_agent_id") REFERENCES "vectraclip"."agents"("company_id", "id") ON DELETE SET NULL ("assigned_to_agent_id");



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_goal_company_fkey" FOREIGN KEY ("company_id", "goal_id") REFERENCES "vectraclip"."goals"("company_id", "id") ON DELETE SET NULL ("goal_id");



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_parent_task_company_fkey" FOREIGN KEY ("company_id", "parent_task_id") REFERENCES "vectraclip"."tasks"("company_id", "id") ON DELETE SET NULL ("parent_task_id");



ALTER TABLE ONLY "vectraclip"."tasks"
    ADD CONSTRAINT "tasks_workflow_step_id_fkey" FOREIGN KEY ("workflow_step_id") REFERENCES "vectraclip"."workflow_steps"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "vectraclip"."workflow_definitions"
    ADD CONSTRAINT "workflow_definitions_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE;



ALTER TABLE ONLY "vectraclip"."workflow_steps"
    ADD CONSTRAINT "workflow_steps_on_success_step_id_fkey" FOREIGN KEY ("on_success_step_id") REFERENCES "vectraclip"."workflow_steps"("id");



ALTER TABLE ONLY "vectraclip"."workflow_steps"
    ADD CONSTRAINT "workflow_steps_workflow_id_fkey" FOREIGN KEY ("workflow_id") REFERENCES "vectraclip"."workflow_definitions"("id") ON DELETE CASCADE;



CREATE POLICY "Admin can delete drivers" ON "public"."drivers" FOR DELETE USING ("public"."is_admin"());



CREATE POLICY "Admin can delete shippers" ON "public"."shippers" FOR DELETE USING ("public"."is_admin"());



CREATE POLICY "Admin can manage approval_rules" ON "public"."approval_rules" TO "authenticated" USING ("public"."is_admin"()) WITH CHECK ("public"."is_admin"());



CREATE POLICY "Admin can manage notification_templates" ON "public"."notification_templates" TO "authenticated" USING ("public"."is_admin"()) WITH CHECK ("public"."is_admin"());



CREATE POLICY "Admin can manage workflow_definitions" ON "public"."workflow_definitions" TO "authenticated" USING ("public"."is_admin"()) WITH CHECK ("public"."is_admin"());



CREATE POLICY "Admin can manage workflow_transitions" ON "public"."workflow_transitions" TO "authenticated" USING ("public"."is_admin"()) WITH CHECK ("public"."is_admin"());



CREATE POLICY "Authenticated can view gris_services" ON "public"."gris_services" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated can view order_gris_services" ON "public"."order_gris_services" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can insert ai_insights" ON "public"."ai_insights" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert compliance_checks" ON "public"."compliance_checks" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert driver_qualifications" ON "public"."driver_qualifications" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert notification_logs" ON "public"."notification_logs" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert notification_queue" ON "public"."notification_queue" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert risk_costs" ON "public"."risk_costs" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert risk_evaluations" ON "public"."risk_evaluations" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert risk_evidence" ON "public"."risk_evidence" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert workflow_event_logs" ON "public"."workflow_event_logs" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can insert workflow_events" ON "public"."workflow_events" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can manage payment_proofs" ON "public"."payment_proofs" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Authenticated users can manage quote_payment_proofs" ON "public"."quote_payment_proofs" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Authenticated users can manage route overrides" ON "public"."pricing_route_overrides" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Authenticated users can manage trip_cost_items" ON "public"."trip_cost_items" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Authenticated users can manage trip_orders" ON "public"."trip_orders" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Authenticated users can manage trips" ON "public"."trips" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Authenticated users can read compliance_checks" ON "public"."compliance_checks" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can read driver_qualifications" ON "public"."driver_qualifications" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can read market_indices" ON "public"."market_indices" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can read news_items" ON "public"."news_items" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can read ntc_articles_seen" ON "public"."ntc_articles_seen" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can read operational_reports" ON "public"."operational_reports" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can read regulatory_updates" ON "public"."regulatory_updates" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can read route overrides" ON "public"."pricing_route_overrides" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can update driver_qualifications" ON "public"."driver_qualifications" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can update notification_logs" ON "public"."notification_logs" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can update notification_queue" ON "public"."notification_queue" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can update risk_costs" ON "public"."risk_costs" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can update risk_evaluations" ON "public"."risk_evaluations" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can update workflow_events" ON "public"."workflow_events" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view ai_insights" ON "public"."ai_insights" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view approval_rules" ON "public"."approval_rules" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view drivers" ON "public"."drivers" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view notification_logs" ON "public"."notification_logs" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view notification_queue" ON "public"."notification_queue" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view notification_templates" ON "public"."notification_templates" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view payment_proofs" ON "public"."payment_proofs" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view quote_payment_proofs" ON "public"."quote_payment_proofs" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view risk_costs" ON "public"."risk_costs" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view risk_evaluations" ON "public"."risk_evaluations" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view risk_evidence" ON "public"."risk_evidence" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view risk_policies" ON "public"."risk_policies" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view risk_policy_rules" ON "public"."risk_policy_rules" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view risk_services_catalog" ON "public"."risk_services_catalog" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view shippers" ON "public"."shippers" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view trip_cost_items" ON "public"."trip_cost_items" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view trip_orders" ON "public"."trip_orders" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view trips" ON "public"."trips" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view workflow_definitions" ON "public"."workflow_definitions" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view workflow_event_logs" ON "public"."workflow_event_logs" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view workflow_events" ON "public"."workflow_events" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated users can view workflow_transitions" ON "public"."workflow_transitions" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Authenticated with profile can manage gris_services" ON "public"."gris_services" TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "Authenticated with profile can manage order_gris_services" ON "public"."order_gris_services" TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "Comercial and Admin can create shippers" ON "public"."shippers" FOR INSERT WITH CHECK ("public"."has_any_role"(( SELECT "auth"."uid"() AS "uid"), ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role"]));



CREATE POLICY "Comercial and Admin can update drivers" ON "public"."drivers" FOR UPDATE USING ("public"."has_any_role"(( SELECT "auth"."uid"() AS "uid"), ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role"]));



CREATE POLICY "Comercial and Admin can update shippers" ON "public"."shippers" FOR UPDATE USING ("public"."has_any_role"(( SELECT "auth"."uid"() AS "uid"), ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role"]));



CREATE POLICY "Enable insert for authenticated users only" ON "public"."ntc_scrape_log" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Enable read access for all users" ON "public"."vehicle_types" FOR SELECT USING (true);



CREATE POLICY "Insert/update via service role" ON "public"."market_indices" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Leitura pública para autenticados" ON "public"."market_indices" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Only service_role can manage api_keys" ON "public"."edge_function_api_keys" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Service role can manage market_indices" ON "public"."market_indices" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Service role can manage news_items" ON "public"."news_items" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Service role can manage ntc_articles_seen" ON "public"."ntc_articles_seen" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Service role can manage operational_reports" ON "public"."operational_reports" TO "service_role" USING (true);



CREATE POLICY "Service role can manage regulatory_updates" ON "public"."regulatory_updates" TO "service_role" USING (true);



ALTER TABLE "public"."agent_jobs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_read_ai_insights" ON "public"."ai_insights" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_antt_floor_rates" ON "public"."antt_floor_rates" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_clients" ON "public"."clients" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_compliance_checks" ON "public"."compliance_checks" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_documents" ON "public"."documents" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_driver_qualifications" ON "public"."driver_qualifications" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_drivers" ON "public"."drivers" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_market_indices" ON "public"."market_indices" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_occurrences" ON "public"."occurrences" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_orders" ON "public"."orders" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_owners" ON "public"."owners" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_payment_proofs" ON "public"."payment_proofs" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_petrobras_diesel_prices" ON "public"."petrobras_diesel_prices" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_risk_evaluations" ON "public"."risk_evaluations" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_trip_cost_items" ON "public"."trip_cost_items" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_trip_orders" ON "public"."trip_orders" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_trips" ON "public"."trips" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_vehicle_types" ON "public"."vehicle_types" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_vehicles" ON "public"."vehicles" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



CREATE POLICY "agent_read_workflow_events" ON "public"."workflow_events" FOR SELECT TO "authenticated" USING ((("auth"."jwt"() ->> 'user_role'::"text") = 'agent'::"text"));



ALTER TABLE "public"."ai_budget_config" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "ai_budget_config_all_service" ON "public"."ai_budget_config" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "ai_budget_config_select_authenticated" ON "public"."ai_budget_config" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "ai_budget_config_update_admin" ON "public"."ai_budget_config" FOR UPDATE TO "authenticated" USING ("public"."is_admin"()) WITH CHECK ("public"."is_admin"());



ALTER TABLE "public"."ai_insights" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."ai_usage_tracking" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "ai_usage_tracking_insert_service" ON "public"."ai_usage_tracking" FOR INSERT TO "service_role" WITH CHECK (true);



CREATE POLICY "ai_usage_tracking_select_authenticated" ON "public"."ai_usage_tracking" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "allow_insert_insurance_logs_service_role" ON "public"."insurance_logs" FOR INSERT TO "service_role" WITH CHECK (true);



CREATE POLICY "allow_select_insurance_logs_authenticated" ON "public"."insurance_logs" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "anon_read_petrobras_diesel_prices" ON "public"."petrobras_diesel_prices" FOR SELECT TO "anon" USING (true);



CREATE POLICY "anon_read_recommendations" ON "public"."mirofish_recommendations" FOR SELECT TO "anon" USING (true);



CREATE POLICY "anon_read_reports" ON "public"."mirofish_reports" FOR SELECT TO "anon" USING (true);



CREATE POLICY "anon_read_route_insights" ON "public"."mirofish_route_insights" FOR SELECT TO "anon" USING (true);



CREATE POLICY "anon_read_shipper_insights" ON "public"."mirofish_shipper_insights" FOR SELECT TO "anon" USING (true);



CREATE POLICY "anon_select_monthly_revenue" ON "public"."mirofish_monthly_revenue" FOR SELECT TO "anon" USING (true);



CREATE POLICY "antt_alerts_insert" ON "public"."antt_violation_alerts" FOR INSERT TO "service_role" WITH CHECK (true);



CREATE POLICY "antt_alerts_select" ON "public"."antt_violation_alerts" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "antt_alerts_update" ON "public"."antt_violation_alerts" FOR UPDATE TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."antt_floor_rates" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "antt_floor_rates_delete" ON "public"."antt_floor_rates" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "antt_floor_rates_insert" ON "public"."antt_floor_rates" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "antt_floor_rates_select" ON "public"."antt_floor_rates" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "antt_floor_rates_update" ON "public"."antt_floor_rates" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."antt_violation_alerts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."approval_requests" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "approval_requests_delete" ON "public"."approval_requests" FOR DELETE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "approval_requests_insert" ON "public"."approval_requests" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "approval_requests_select" ON "public"."approval_requests" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "approval_requests_update" ON "public"."approval_requests" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."approval_rules" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."audit_logs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "audit_logs_admin_select" ON "public"."audit_logs" FOR SELECT TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "authenticated_read" ON "public"."delivery_assessments" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "authenticated_read" ON "public"."petrobras_diesel_prices" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "authenticated_write" ON "public"."delivery_assessments" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."clients" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "clients_delete" ON "public"."clients" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "clients_insert" ON "public"."clients" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "clients_select" ON "public"."clients" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "clients_update" ON "public"."clients" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."cnh_categories" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "cnh_categories_read" ON "public"."cnh_categories" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."collected_data" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."collection_orders" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "collection_orders_insert" ON "public"."collection_orders" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "collection_orders_select" ON "public"."collection_orders" FOR SELECT TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "collection_orders_update" ON "public"."collection_orders" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."commercial_closeout_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "commercial_closeout_events_select_authenticated" ON "public"."commercial_closeout_events" FOR SELECT USING ((( SELECT "auth"."role"() AS "role") = 'authenticated'::"text"));



ALTER TABLE "public"."commercial_followup_rules" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "commercial_followup_rules_select_authenticated" ON "public"."commercial_followup_rules" FOR SELECT USING ((( SELECT "auth"."role"() AS "role") = 'authenticated'::"text"));



ALTER TABLE "public"."commercial_followup_runs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "commercial_followup_runs_select_authenticated" ON "public"."commercial_followup_runs" FOR SELECT USING ((( SELECT "auth"."role"() AS "role") = 'authenticated'::"text"));



ALTER TABLE "public"."commercial_message_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "commercial_message_events_select_authenticated" ON "public"."commercial_message_events" FOR SELECT USING ((( SELECT "auth"."role"() AS "role") = 'authenticated'::"text"));



ALTER TABLE "public"."commercial_operational_handoffs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "commercial_operational_handoffs_select_authenticated" ON "public"."commercial_operational_handoffs" FOR SELECT USING ((( SELECT "auth"."role"() AS "role") = 'authenticated'::"text"));



ALTER TABLE "public"."company_settings" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "company_settings_select" ON "public"."company_settings" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."compliance_checks" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conditional_fees" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "conditional_fees_delete" ON "public"."conditional_fees" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "conditional_fees_insert" ON "public"."conditional_fees" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "conditional_fees_select" ON "public"."conditional_fees" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "conditional_fees_update" ON "public"."conditional_fees" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "config_select" ON "public"."driver_offer_ranking_config" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "config_service" ON "public"."driver_offer_ranking_config" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "public"."delivery_assessments" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."delivery_conditions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "delivery_conditions_delete" ON "public"."delivery_conditions" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "delivery_conditions_insert" ON "public"."delivery_conditions" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "delivery_conditions_select" ON "public"."delivery_conditions" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "delivery_conditions_update" ON "public"."delivery_conditions" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "deny_authenticated" ON "public"."vectra_manifestos" AS RESTRICTIVE TO "authenticated" USING (false);



CREATE POLICY "deny_authenticated" ON "public"."vectra_motoristas_margem" AS RESTRICTIVE TO "authenticated" USING (false);



CREATE POLICY "deny_authenticated" ON "public"."vectra_rentabilidade_rotas" AS RESTRICTIVE TO "authenticated" USING (false);



ALTER TABLE "public"."discharge_checklist_items" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "discharge_checklist_items_delete" ON "public"."discharge_checklist_items" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "discharge_checklist_items_insert" ON "public"."discharge_checklist_items" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "discharge_checklist_items_select" ON "public"."discharge_checklist_items" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "discharge_checklist_items_update" ON "public"."discharge_checklist_items" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."documents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "documents_delete" ON "public"."documents" FOR DELETE USING (("public"."is_admin"() OR ("public"."has_profile"(ARRAY['financeiro'::"public"."user_profile"]) AND ("type" = ANY (ARRAY['a_vista_fat'::"public"."document_type", 'saldo_fat'::"public"."document_type", 'a_prazo_fat'::"public"."document_type", 'adiantamento'::"public"."document_type", 'adiantamento_carreteiro'::"public"."document_type", 'saldo_carreteiro'::"public"."document_type", 'comprovante_vpo'::"public"."document_type", 'nfe'::"public"."document_type", 'cte'::"public"."document_type", 'pod'::"public"."document_type", 'mdfe'::"public"."document_type", 'analise_gr'::"public"."document_type", 'doc_rota'::"public"."document_type", 'comprovante_descarga'::"public"."document_type"]))) OR ("public"."has_profile"(ARRAY['operacional'::"public"."user_profile"]) AND ("uploaded_by" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "documents_insert" ON "public"."documents" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "documents_select" ON "public"."documents" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "documents_update" ON "public"."documents" FOR UPDATE USING (("public"."is_admin"() OR ("uploaded_by" = ( SELECT "auth"."uid"() AS "uid")) OR "public"."has_profile"(ARRAY['financeiro'::"public"."user_profile"]))) WITH CHECK (("public"."is_admin"() OR ("uploaded_by" = ( SELECT "auth"."uid"() AS "uid")) OR "public"."has_profile"(ARRAY['financeiro'::"public"."user_profile"])));



ALTER TABLE "public"."driver_offer_ranking_config" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."driver_offer_sequences" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."driver_offers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."driver_qualifications" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."drivers" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "drivers_delete" ON "public"."drivers" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "drivers_insert" ON "public"."drivers" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "drivers_select" ON "public"."drivers" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "drivers_update" ON "public"."drivers" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."edge_function_api_keys" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."equipment_rental_rates" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "equipment_rental_rates_all_authenticated" ON "public"."equipment_rental_rates" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "equipment_rental_rates_all_service_role" ON "public"."equipment_rental_rates" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "equipment_rental_rates_select_authenticated" ON "public"."equipment_rental_rates" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."financial_documents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "financial_documents_delete" ON "public"."financial_documents" FOR DELETE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "financial_documents_insert" ON "public"."financial_documents" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "financial_documents_select" ON "public"."financial_documents" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "financial_documents_update" ON "public"."financial_documents" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."financial_installments" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "financial_installments_delete" ON "public"."financial_installments" FOR DELETE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "financial_installments_insert" ON "public"."financial_installments" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "financial_installments_select" ON "public"."financial_installments" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "financial_installments_update" ON "public"."financial_installments" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."gris_services" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."icms_rates" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "icms_rates_delete" ON "public"."icms_rates" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "icms_rates_insert" ON "public"."icms_rates" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "icms_rates_select" ON "public"."icms_rates" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "icms_rates_update" ON "public"."icms_rates" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "insert_own_discounts" ON "public"."load_composition_discount_breakdown" FOR INSERT WITH CHECK (((( SELECT "auth"."uid"() AS "uid") = "created_by") OR (( SELECT "auth"."uid"() AS "uid") IN ( SELECT "profiles"."user_id"
   FROM "public"."profiles"
  WHERE ("profiles"."perfil" = ANY (ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"]))))));



ALTER TABLE "public"."insurance_logs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "lc_metrics_insert" ON "public"."load_composition_metrics" FOR INSERT WITH CHECK (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "lc_metrics_view" ON "public"."load_composition_metrics" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."load_composition_suggestions" "s"
  WHERE (("s"."id" = "load_composition_metrics"."composition_id") AND ("auth"."role"() = 'authenticated'::"text")))));



CREATE POLICY "lc_routings_insert" ON "public"."load_composition_routings" FOR INSERT WITH CHECK (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "lc_routings_view" ON "public"."load_composition_routings" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."load_composition_suggestions" "s"
  WHERE (("s"."id" = "load_composition_routings"."composition_id") AND ("auth"."role"() = 'authenticated'::"text")))));



CREATE POLICY "load_comp_delete" ON "public"."load_composition_suggestions" FOR DELETE USING ((("created_by" = ( SELECT "auth"."uid"() AS "uid")) AND ("status" = 'pending'::"text")));



CREATE POLICY "load_comp_insert" ON "public"."load_composition_suggestions" FOR INSERT WITH CHECK (("auth"."role"() = 'authenticated'::"text"));



CREATE POLICY "load_comp_update" ON "public"."load_composition_suggestions" FOR UPDATE USING (((( SELECT "auth"."uid"() AS "uid") = "created_by") OR (( SELECT "auth"."uid"() AS "uid") = "approved_by") OR ("auth"."role"() = 'service_role'::"text"))) WITH CHECK (((( SELECT "auth"."uid"() AS "uid") = "created_by") OR (( SELECT "auth"."uid"() AS "uid") = "approved_by") OR ("auth"."role"() = 'service_role'::"text")));



CREATE POLICY "load_comp_view" ON "public"."load_composition_suggestions" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));



ALTER TABLE "public"."load_composition_discount_breakdown" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."load_composition_metrics" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."load_composition_routings" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."load_composition_suggestions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."logistics_traffic_rules" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "logistics_traffic_rules_read" ON "public"."logistics_traffic_rules" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."user_roles" "ur"
  WHERE (("ur"."user_id" = ( SELECT "auth"."uid"() AS "uid")) AND ("ur"."role" = ANY (ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role", 'operacao'::"public"."app_role"]))))));



ALTER TABLE "public"."ltl_parameters" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "ltl_parameters_insert" ON "public"."ltl_parameters" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "ltl_parameters_select" ON "public"."ltl_parameters" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "ltl_parameters_update" ON "public"."ltl_parameters" FOR UPDATE TO "authenticated" USING (true);



ALTER TABLE "public"."market_indices" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mirofish_monthly_revenue" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mirofish_recommendations" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "mirofish_recommendations_read" ON "public"."mirofish_recommendations" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."user_roles" "ur"
  WHERE (("ur"."user_id" = ( SELECT "auth"."uid"() AS "uid")) AND ("ur"."role" = ANY (ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role"]))))));



ALTER TABLE "public"."mirofish_reports" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "mirofish_reports_read" ON "public"."mirofish_reports" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."user_roles" "ur"
  WHERE (("ur"."user_id" = ( SELECT "auth"."uid"() AS "uid")) AND ("ur"."role" = ANY (ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role"]))))));



ALTER TABLE "public"."mirofish_route_insights" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "mirofish_route_insights_read" ON "public"."mirofish_route_insights" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."user_roles" "ur"
  WHERE (("ur"."user_id" = ( SELECT "auth"."uid"() AS "uid")) AND ("ur"."role" = ANY (ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role"]))))));



ALTER TABLE "public"."mirofish_shipper_insights" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "mirofish_shipper_insights_read" ON "public"."mirofish_shipper_insights" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."user_roles" "ur"
  WHERE (("ur"."user_id" = ( SELECT "auth"."uid"() AS "uid")) AND ("ur"."role" = ANY (ARRAY['admin'::"public"."app_role", 'comercial'::"public"."app_role"]))))));



ALTER TABLE "public"."news_items" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notification_logs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notification_queue" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notification_templates" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."ntc_articles_seen" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."ntc_cost_indices" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "ntc_cost_indices_delete" ON "public"."ntc_cost_indices" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "ntc_cost_indices_insert" ON "public"."ntc_cost_indices" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "ntc_cost_indices_select" ON "public"."ntc_cost_indices" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "ntc_cost_indices_update" ON "public"."ntc_cost_indices" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."ntc_fuel_reference" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "ntc_fuel_reference_delete" ON "public"."ntc_fuel_reference" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "ntc_fuel_reference_insert" ON "public"."ntc_fuel_reference" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "ntc_fuel_reference_select" ON "public"."ntc_fuel_reference" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "ntc_fuel_reference_update" ON "public"."ntc_fuel_reference" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."ntc_scrape_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."occurrences" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "occurrences_delete" ON "public"."occurrences" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "occurrences_insert" ON "public"."occurrences" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "occurrences_select" ON "public"."occurrences" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "occurrences_update" ON "public"."occurrences" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "offers_select" ON "public"."driver_offers" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "offers_service" ON "public"."driver_offers" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "public"."operational_reports" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."order_gris_services" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."orders" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "orders_delete" ON "public"."orders" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "orders_insert" ON "public"."orders" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "orders_select" ON "public"."orders" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "orders_update" ON "public"."orders" FOR UPDATE TO "authenticated" USING (("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]) OR ("public"."has_profile"(ARRAY['financeiro'::"public"."user_profile"]) AND ("stage" = 'documentacao'::"public"."order_stage")))) WITH CHECK (("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]) OR ("public"."has_profile"(ARRAY['financeiro'::"public"."user_profile"]) AND ("stage" = 'documentacao'::"public"."order_stage"))));



ALTER TABLE "public"."owners" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "owners_delete" ON "public"."owners" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "owners_insert" ON "public"."owners" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "owners_select" ON "public"."owners" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "owners_update" ON "public"."owners" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."partner_quotes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "partner_quotes_insert_own" ON "public"."partner_quotes" FOR INSERT WITH CHECK ((( SELECT "auth"."uid"() AS "uid") = "user_id"));



CREATE POLICY "partner_quotes_select_own" ON "public"."partner_quotes" FOR SELECT USING ((( SELECT "auth"."uid"() AS "uid") = "user_id"));



ALTER TABLE "public"."partner_shippers" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "partner_shippers_select_authenticated" ON "public"."partner_shippers" FOR SELECT USING ((( SELECT "auth"."role"() AS "role") = 'authenticated'::"text"));



ALTER TABLE "public"."partner_tokens" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."partner_users" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."payment_proofs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."payment_terms" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "payment_terms_delete" ON "public"."payment_terms" FOR DELETE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "payment_terms_insert" ON "public"."payment_terms" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "payment_terms_select" ON "public"."payment_terms" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "payment_terms_update" ON "public"."payment_terms" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."petrobras_diesel_prices" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."price_table_rows" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "price_table_rows_delete" ON "public"."price_table_rows" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "price_table_rows_insert" ON "public"."price_table_rows" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "price_table_rows_select" ON "public"."price_table_rows" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "price_table_rows_update" ON "public"."price_table_rows" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."price_tables" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "price_tables_delete" ON "public"."price_tables" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "price_tables_insert" ON "public"."price_tables" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "price_tables_select" ON "public"."price_tables" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "price_tables_update" ON "public"."price_tables" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."pricing_parameters" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "pricing_parameters_delete" ON "public"."pricing_parameters" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "pricing_parameters_insert" ON "public"."pricing_parameters" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "pricing_parameters_select" ON "public"."pricing_parameters" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "pricing_parameters_update" ON "public"."pricing_parameters" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."pricing_route_overrides" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pricing_rules_config" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "pricing_rules_delete" ON "public"."pricing_rules_config" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "pricing_rules_insert" ON "public"."pricing_rules_config" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "pricing_rules_select" ON "public"."pricing_rules_config" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "pricing_rules_update" ON "public"."pricing_rules_config" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."processes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."product_dimensions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "product_dimensions_select_authenticated" ON "public"."product_dimensions" FOR SELECT USING ((( SELECT "auth"."role"() AS "role") = 'authenticated'::"text"));



ALTER TABLE "public"."profiles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "profiles_select" ON "public"."profiles" FOR SELECT USING ((("id" = ( SELECT "auth"."uid"() AS "uid")) OR ("user_id" = ( SELECT "auth"."uid"() AS "uid")) OR "public"."is_admin"()));



CREATE POLICY "profiles_update" ON "public"."profiles" FOR UPDATE USING ((("id" = ( SELECT "auth"."uid"() AS "uid")) OR ("user_id" = ( SELECT "auth"."uid"() AS "uid")) OR "public"."is_admin"())) WITH CHECK ((("id" = ( SELECT "auth"."uid"() AS "uid")) OR ("user_id" = ( SELECT "auth"."uid"() AS "uid")) OR "public"."is_admin"()));



ALTER TABLE "public"."quote_contracts" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "quote_contracts_select" ON "public"."quote_contracts" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."quote_payment_proofs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."quote_route_stops" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "quote_route_stops_delete" ON "public"."quote_route_stops" FOR DELETE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "quote_route_stops_insert" ON "public"."quote_route_stops" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "quote_route_stops_select" ON "public"."quote_route_stops" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "quote_route_stops_update" ON "public"."quote_route_stops" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."quotes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "quotes_delete" ON "public"."quotes" FOR DELETE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "quotes_insert" ON "public"."quotes" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "quotes_select" ON "public"."quotes" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "quotes_update" ON "public"."quotes" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."regulatory_updates" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."risk_costs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."risk_evaluations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."risk_evidence" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."risk_policies" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."risk_policy_rules" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."risk_services_catalog" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."route_metrics_config" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "route_metrics_config_select_authenticated" ON "public"."route_metrics_config" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "route_metrics_config_write_authenticated" ON "public"."route_metrics_config" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "select_own_discounts" ON "public"."load_composition_discount_breakdown" FOR SELECT USING (((( SELECT "auth"."uid"() AS "uid") = "created_by") OR (( SELECT "auth"."uid"() AS "uid") IN ( SELECT "profiles"."user_id"
   FROM "public"."profiles"
  WHERE ("profiles"."perfil" = ANY (ARRAY['admin'::"public"."user_profile", 'financeiro'::"public"."user_profile"]))))));



CREATE POLICY "sequences_select" ON "public"."driver_offer_sequences" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "sequences_service" ON "public"."driver_offer_sequences" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "service_role_all" ON "public"."petrobras_diesel_prices" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "service_role_full" ON "public"."delivery_assessments" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "public"."settings" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."shippers" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "shippers_delete" ON "public"."shippers" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "shippers_insert" ON "public"."shippers" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "shippers_select" ON "public"."shippers" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "shippers_update" ON "public"."shippers" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."sipoc_customers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sipoc_decisions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sipoc_inputs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sipoc_maps" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sipoc_outputs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sipoc_suppliers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."skill_executions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tac_rates" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tac_rates_delete" ON "public"."tac_rates" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "tac_rates_insert" ON "public"."tac_rates" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "tac_rates_select" ON "public"."tac_rates" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "tac_rates_update" ON "public"."tac_rates" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."tasks" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."toll_routes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "toll_routes_delete" ON "public"."toll_routes" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "toll_routes_insert" ON "public"."toll_routes" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "toll_routes_select" ON "public"."toll_routes" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "toll_routes_update" ON "public"."toll_routes" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."trip_cost_items" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."trip_orders" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."trips" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."unloading_cost_rates" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "unloading_cost_rates_all_authenticated" ON "public"."unloading_cost_rates" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "unloading_cost_rates_all_service_role" ON "public"."unloading_cost_rates" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "unloading_cost_rates_select_authenticated" ON "public"."unloading_cost_rates" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."user_roles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "user_roles_admin" ON "public"."user_roles" TO "authenticated" USING ("public"."is_admin"()) WITH CHECK ("public"."is_admin"());



CREATE POLICY "user_roles_select" ON "public"."user_roles" FOR SELECT USING ((("user_id" = ( SELECT "auth"."uid"() AS "uid")) OR "public"."is_admin"()));



ALTER TABLE "public"."vectra_manifestos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."vectra_motoristas_margem" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."vectra_rentabilidade_rotas" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."vehicle_types" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "vehicle_types_delete" ON "public"."vehicle_types" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "vehicle_types_insert" ON "public"."vehicle_types" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "vehicle_types_update" ON "public"."vehicle_types" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."vehicles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "vehicles_delete" ON "public"."vehicles" FOR DELETE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'comercial'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "vehicles_insert" ON "public"."vehicles" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'comercial'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



CREATE POLICY "vehicles_select" ON "public"."vehicles" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "vehicles_update" ON "public"."vehicles" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'comercial'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'comercial'::"public"."user_profile", 'operacional'::"public"."user_profile", 'financeiro'::"public"."user_profile"]));



ALTER TABLE "public"."waiting_time_rules" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "waiting_time_rules_delete" ON "public"."waiting_time_rules" FOR DELETE TO "authenticated" USING ("public"."is_admin"());



CREATE POLICY "waiting_time_rules_insert" ON "public"."waiting_time_rules" FOR INSERT TO "authenticated" WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



CREATE POLICY "waiting_time_rules_select" ON "public"."waiting_time_rules" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "waiting_time_rules_update" ON "public"."waiting_time_rules" FOR UPDATE TO "authenticated" USING ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"])) WITH CHECK ("public"."has_profile"(ARRAY['admin'::"public"."user_profile", 'operacional'::"public"."user_profile"]));



ALTER TABLE "public"."workflow_definitions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."workflow_event_logs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."workflow_events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."workflow_transitions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."adapter_catalog" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "adapter_catalog_select_authenticated" ON "vectraclip"."adapter_catalog" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "adapter_catalog_write_service_role" ON "vectraclip"."adapter_catalog" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."adapter_field_definitions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "adapter_fields_select_authenticated" ON "vectraclip"."adapter_field_definitions" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "adapter_fields_write_service_role" ON "vectraclip"."adapter_field_definitions" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agent_adapter_configs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_adapter_configs_select_authenticated" ON "vectraclip"."agent_adapter_configs" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "agent_adapter_configs_write_service_role" ON "vectraclip"."agent_adapter_configs" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agent_execution_configs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_execution_configs_select_authenticated" ON "vectraclip"."agent_execution_configs" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "agent_execution_configs_write_service_role" ON "vectraclip"."agent_execution_configs" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agent_specialties" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_specialties_select_authenticated" ON "vectraclip"."agent_specialties" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "agent_specialties_write_service_role" ON "vectraclip"."agent_specialties" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."agent_specialty_configs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agent_specialty_configs_delete" ON "vectraclip"."agent_specialty_configs" FOR DELETE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "agent_specialty_configs_insert" ON "vectraclip"."agent_specialty_configs" FOR INSERT WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "agent_specialty_configs_select" ON "vectraclip"."agent_specialty_configs" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "agent_specialty_configs_update" ON "vectraclip"."agent_specialty_configs" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"])))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



ALTER TABLE "vectraclip"."agents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agents_delete_own_company_admin" ON "vectraclip"."agents" FOR DELETE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "agents_insert_own_company_admin_op" ON "vectraclip"."agents" FOR INSERT WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "agents_select_own_company" ON "vectraclip"."agents" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "agents_update_own_company_admin_op" ON "vectraclip"."agents" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"])))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "agents_write_service_role" ON "vectraclip"."agents" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."app_users" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "app_users_delete_admin" ON "vectraclip"."app_users" FOR DELETE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "app_users_insert_admin" ON "vectraclip"."app_users" FOR INSERT WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "app_users_select_own_company" ON "vectraclip"."app_users" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "app_users_update_admin" ON "vectraclip"."app_users" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text"))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



ALTER TABLE "vectraclip"."approvals" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "approvals_insert_own_company" ON "vectraclip"."approvals" FOR INSERT WITH CHECK (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "approvals_select_own_company" ON "vectraclip"."approvals" FOR SELECT USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "approvals_update_own_company" ON "vectraclip"."approvals" FOR UPDATE USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid")) WITH CHECK (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



ALTER TABLE "vectraclip"."companies" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "companies_select_own" ON "vectraclip"."companies" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "companies_update_admin" ON "vectraclip"."companies" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text"))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "company members can manage goals" ON "vectraclip"."goals" USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



ALTER TABLE "vectraclip"."company_secrets" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "company_secrets_insert_admin" ON "vectraclip"."company_secrets" FOR INSERT WITH CHECK ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "company_secrets_select_own_company" ON "vectraclip"."company_secrets" FOR SELECT USING (("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"));



CREATE POLICY "company_secrets_update_admin" ON "vectraclip"."company_secrets" FOR UPDATE USING ((("company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid") AND (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text") = 'admin'::"text")));



CREATE POLICY "company_secrets_write_service_role" ON "vectraclip"."company_secrets" USING (("auth"."role"() = 'service_role'::"text"));



ALTER TABLE "vectraclip"."goals" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."heartbeats" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "heartbeats_delete_own_company_admin" ON "vectraclip"."heartbeats" FOR DELETE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "heartbeats_insert_own_company" ON "vectraclip"."heartbeats" FOR INSERT WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "heartbeats_select_own_company" ON "vectraclip"."heartbeats" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "heartbeats_update_own_company_admin" ON "vectraclip"."heartbeats" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text"))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



ALTER TABLE "vectraclip"."hermes_sender_whitelist" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "hermes_whitelist_service_role" ON "vectraclip"."hermes_sender_whitelist" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "hermes_whitelist_tenant_isolation" ON "vectraclip"."hermes_sender_whitelist" TO "authenticated" USING (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id")) WITH CHECK (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id"));



ALTER TABLE "vectraclip"."incident_audit" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "incident_audit_select_own_company" ON "vectraclip"."incident_audit" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "vectraclip"."incidents" "i"
  WHERE (("i"."id" = "incident_audit"."incident_id") AND ("i"."company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid")))));



ALTER TABLE "vectraclip"."incidents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "incidents_select_own_company" ON "vectraclip"."incidents" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



ALTER TABLE "vectraclip"."llm_models" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "llm_models_select_authenticated" ON "vectraclip"."llm_models" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "llm_models_write_service_role" ON "vectraclip"."llm_models" TO "service_role" USING (true) WITH CHECK (true);



ALTER TABLE "vectraclip"."managed_agent_sessions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."managed_agent_turn_logs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."projects" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "projects_delete" ON "vectraclip"."projects" FOR DELETE USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "projects_insert" ON "vectraclip"."projects" FOR INSERT WITH CHECK (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "projects_select" ON "vectraclip"."projects" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "projects_update" ON "vectraclip"."projects" FOR UPDATE USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid")) WITH CHECK (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



ALTER TABLE "vectraclip"."prospect_profiles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "prospect_profiles_delete_own_company_admin" ON "vectraclip"."prospect_profiles" FOR DELETE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "prospect_profiles_insert_own_company_admin_op" ON "vectraclip"."prospect_profiles" FOR INSERT WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "prospect_profiles_select_own_company" ON "vectraclip"."prospect_profiles" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "prospect_profiles_update_own_company_admin_op" ON "vectraclip"."prospect_profiles" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"])))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



ALTER TABLE "vectraclip"."routines" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "routines_delete_own_company_admin" ON "vectraclip"."routines" FOR DELETE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "routines_insert_own_company_admin_op" ON "vectraclip"."routines" FOR INSERT WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "routines_select_own_company" ON "vectraclip"."routines" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "routines_update_own_company_admin_op" ON "vectraclip"."routines" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"])))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



ALTER TABLE "vectraclip"."run_transcript_entries" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."runs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "runs insert own company" ON "vectraclip"."runs" FOR INSERT WITH CHECK (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "runs select own company" ON "vectraclip"."runs" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "runs update own company" ON "vectraclip"."runs" FOR UPDATE USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "service_role full access" ON "vectraclip"."sipoc_edges" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "service_role full access" ON "vectraclip"."sipoc_raci" TO "service_role" USING (true) WITH CHECK (true);



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



ALTER TABLE "vectraclip"."sipoc_edges" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_edges_tenant_delete" ON "vectraclip"."sipoc_edges" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_edges"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_edges_tenant_insert" ON "vectraclip"."sipoc_edges" FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_edges"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_edges_tenant_select" ON "vectraclip"."sipoc_edges" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_edges"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



CREATE POLICY "sipoc_edges_tenant_update" ON "vectraclip"."sipoc_edges" FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM ("vectraclip"."sipoc_processes" "p"
     JOIN "vectraclip"."sipoc_sectors" "s" ON (("s"."id" = "p"."sector_id")))
  WHERE (("p"."id" = "sipoc_edges"."process_id") AND ("s"."company_id" = "vectraclip"."sipoc_company_id"())))));



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



ALTER TABLE "vectraclip"."sipoc_raci" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "vectraclip"."sipoc_sector_baselines" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_sector_baselines_select_all" ON "vectraclip"."sipoc_sector_baselines" FOR SELECT USING (true);



ALTER TABLE "vectraclip"."sipoc_sectors" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sipoc_sectors_tenant_delete" ON "vectraclip"."sipoc_sectors" FOR DELETE USING (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_sectors_tenant_insert" ON "vectraclip"."sipoc_sectors" FOR INSERT TO "authenticated" WITH CHECK (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_sectors_tenant_select" ON "vectraclip"."sipoc_sectors" FOR SELECT USING (("company_id" = "vectraclip"."sipoc_company_id"()));



CREATE POLICY "sipoc_sectors_tenant_update" ON "vectraclip"."sipoc_sectors" FOR UPDATE USING (("company_id" = "vectraclip"."sipoc_company_id"())) WITH CHECK (("company_id" = "vectraclip"."sipoc_company_id"()));



ALTER TABLE "vectraclip"."tasks" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tasks_delete_own_company_admin" ON "vectraclip"."tasks" FOR DELETE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = 'admin'::"text")));



CREATE POLICY "tasks_insert_own_company_admin_op" ON "vectraclip"."tasks" FOR INSERT WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "tasks_select_own_company" ON "vectraclip"."tasks" FOR SELECT USING (("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"));



CREATE POLICY "tasks_update_own_company_admin_op" ON "vectraclip"."tasks" FOR UPDATE USING ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"])))) WITH CHECK ((("company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid") AND (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'role'::"text")) = ANY (ARRAY['admin'::"text", 'operator'::"text"]))));



CREATE POLICY "tasks_write_service_role" ON "vectraclip"."tasks" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "transcript entries select own company" ON "vectraclip"."run_transcript_entries" FOR SELECT USING (("run_id" IN ( SELECT "runs"."id"
   FROM "vectraclip"."runs"
  WHERE ("runs"."company_id" = (( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text")))::"uuid"))));



ALTER TABLE "vectraclip"."workflow_definitions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "workflow_definitions_service_role" ON "vectraclip"."workflow_definitions" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "workflow_definitions_tenant_isolation" ON "vectraclip"."workflow_definitions" TO "authenticated" USING (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id")) WITH CHECK (((((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid" = "company_id"));



ALTER TABLE "vectraclip"."workflow_steps" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "workflow_steps_read_authenticated" ON "vectraclip"."workflow_steps" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "workflow_steps_service_role" ON "vectraclip"."workflow_steps" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "workflow_steps_write_authenticated" ON "vectraclip"."workflow_steps" TO "authenticated" USING (("workflow_id" IN ( SELECT "workflow_definitions"."id"
   FROM "vectraclip"."workflow_definitions"
  WHERE ("workflow_definitions"."company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid")))) WITH CHECK (("workflow_id" IN ( SELECT "workflow_definitions"."id"
   FROM "vectraclip"."workflow_definitions"
  WHERE ("workflow_definitions"."company_id" = (((("auth"."jwt"() -> 'app_metadata'::"text") -> 'vectraclip'::"text") ->> 'company_id'::"text"))::"uuid"))));





ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";






ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."financial_documents";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."financial_installments";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."occurrences";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."orders";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."quotes";









GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";



GRANT USAGE ON SCHEMA "vectraclip" TO "anon";
GRANT USAGE ON SCHEMA "vectraclip" TO "authenticated";
GRANT USAGE ON SCHEMA "vectraclip" TO "service_role";











































































































































































GRANT ALL ON FUNCTION "public"."audit_trigger_func"() TO "anon";
GRANT ALL ON FUNCTION "public"."audit_trigger_func"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."audit_trigger_func"() TO "service_role";



GRANT ALL ON FUNCTION "public"."check_ai_budget"() TO "anon";
GRANT ALL ON FUNCTION "public"."check_ai_budget"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."check_ai_budget"() TO "service_role";



GRANT ALL ON FUNCTION "public"."copy_quote_adiantamento_to_fat"("p_quote_id" "uuid", "p_fat_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."copy_quote_adiantamento_to_fat"("p_quote_id" "uuid", "p_fat_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."copy_quote_adiantamento_to_fat"("p_quote_id" "uuid", "p_fat_id" "uuid") TO "service_role";



GRANT ALL ON TABLE "public"."trips" TO "anon";
GRANT ALL ON TABLE "public"."trips" TO "authenticated";
GRANT ALL ON TABLE "public"."trips" TO "service_role";



REVOKE ALL ON FUNCTION "public"."create_trip"("p_vehicle_plate" "text", "p_driver_id" "uuid", "p_vehicle_type_id" "uuid", "p_departure_at" timestamp with time zone, "p_notes" "text", "p_trip_number" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."create_trip"("p_vehicle_plate" "text", "p_driver_id" "uuid", "p_vehicle_type_id" "uuid", "p_departure_at" timestamp with time zone, "p_notes" "text", "p_trip_number" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."create_trip"("p_vehicle_plate" "text", "p_driver_id" "uuid", "p_vehicle_type_id" "uuid", "p_departure_at" timestamp with time zone, "p_notes" "text", "p_trip_number" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."create_trip"("p_vehicle_plate" "text", "p_driver_id" "uuid", "p_vehicle_type_id" "uuid", "p_departure_at" timestamp with time zone, "p_notes" "text", "p_trip_number" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."create_trip_from_composition"("p_composition_id" "uuid", "p_user_id" "uuid", "p_total_value_fat" numeric, "p_total_cost_pag" numeric, "p_notes" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."create_trip_from_composition"("p_composition_id" "uuid", "p_user_id" "uuid", "p_total_value_fat" numeric, "p_total_cost_pag" numeric, "p_notes" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."create_trip_from_composition"("p_composition_id" "uuid", "p_user_id" "uuid", "p_total_value_fat" numeric, "p_total_cost_pag" numeric, "p_notes" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."current_user_profile"() TO "anon";
GRANT ALL ON FUNCTION "public"."current_user_profile"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."current_user_profile"() TO "service_role";



GRANT ALL ON FUNCTION "public"."emit_approval_decided_event"() TO "anon";
GRANT ALL ON FUNCTION "public"."emit_approval_decided_event"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."emit_approval_decided_event"() TO "service_role";



GRANT ALL ON FUNCTION "public"."emit_document_uploaded_event"() TO "anon";
GRANT ALL ON FUNCTION "public"."emit_document_uploaded_event"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."emit_document_uploaded_event"() TO "service_role";



GRANT ALL ON FUNCTION "public"."emit_financial_status_event"() TO "anon";
GRANT ALL ON FUNCTION "public"."emit_financial_status_event"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."emit_financial_status_event"() TO "service_role";



GRANT ALL ON FUNCTION "public"."emit_order_created_event"() TO "anon";
GRANT ALL ON FUNCTION "public"."emit_order_created_event"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."emit_order_created_event"() TO "service_role";



GRANT ALL ON FUNCTION "public"."emit_order_stage_event"() TO "anon";
GRANT ALL ON FUNCTION "public"."emit_order_stage_event"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."emit_order_stage_event"() TO "service_role";



GRANT ALL ON FUNCTION "public"."emit_quote_stage_event"() TO "anon";
GRANT ALL ON FUNCTION "public"."emit_quote_stage_event"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."emit_quote_stage_event"() TO "service_role";



GRANT ALL ON FUNCTION "public"."enforce_company_domain"() TO "anon";
GRANT ALL ON FUNCTION "public"."enforce_company_domain"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."enforce_company_domain"() TO "service_role";



GRANT ALL ON FUNCTION "public"."enforce_pod_before_entregue"() TO "anon";
GRANT ALL ON FUNCTION "public"."enforce_pod_before_entregue"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."enforce_pod_before_entregue"() TO "service_role";



GRANT ALL ON FUNCTION "public"."enforce_uppercase_clients"() TO "service_role";



GRANT ALL ON FUNCTION "public"."enforce_uppercase_drivers"() TO "service_role";



GRANT ALL ON FUNCTION "public"."enforce_uppercase_owners"() TO "service_role";



GRANT ALL ON FUNCTION "public"."enqueue_agent_job"() TO "anon";
GRANT ALL ON FUNCTION "public"."enqueue_agent_job"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."enqueue_agent_job"() TO "service_role";



GRANT ALL ON FUNCTION "public"."ensure_financial_document"("doc_type" "public"."financial_doc_type", "source_id_in" "uuid", "total_amount_in" numeric) TO "anon";
GRANT ALL ON FUNCTION "public"."ensure_financial_document"("doc_type" "public"."financial_doc_type", "source_id_in" "uuid", "total_amount_in" numeric) TO "authenticated";
GRANT ALL ON FUNCTION "public"."ensure_financial_document"("doc_type" "public"."financial_doc_type", "source_id_in" "uuid", "total_amount_in" numeric) TO "service_role";



GRANT ALL ON FUNCTION "public"."find_price_row_by_km"("p_price_table_id" "uuid", "p_km_numeric" numeric, "p_rounding" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."find_price_row_by_km"("p_price_table_id" "uuid", "p_km_numeric" numeric, "p_rounding" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."find_price_row_by_km"("p_price_table_id" "uuid", "p_km_numeric" numeric, "p_rounding" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_risk_evaluation_approved"() TO "anon";
GRANT ALL ON FUNCTION "public"."fn_risk_evaluation_approved"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_risk_evaluation_approved"() TO "service_role";



GRANT ALL ON FUNCTION "public"."generate_os_number"() TO "anon";
GRANT ALL ON FUNCTION "public"."generate_os_number"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."generate_os_number"() TO "service_role";



GRANT ALL ON FUNCTION "public"."generate_quote_code"() TO "anon";
GRANT ALL ON FUNCTION "public"."generate_quote_code"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."generate_quote_code"() TO "service_role";



GRANT ALL ON FUNCTION "public"."generate_trip_number"() TO "anon";
GRANT ALL ON FUNCTION "public"."generate_trip_number"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."generate_trip_number"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_ai_daily_spend"() TO "anon";
GRANT ALL ON FUNCTION "public"."get_ai_daily_spend"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_ai_daily_spend"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_ai_monthly_spend"() TO "anon";
GRANT ALL ON FUNCTION "public"."get_ai_monthly_spend"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_ai_monthly_spend"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_ai_usage_stats"() TO "anon";
GRANT ALL ON FUNCTION "public"."get_ai_usage_stats"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_ai_usage_stats"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_card_full_data"("p_quote_id" "uuid", "p_order_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."get_card_full_data"("p_quote_id" "uuid", "p_order_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_card_full_data"("p_quote_id" "uuid", "p_order_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_diesel_cost_by_route"("p_from" "date", "p_to" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."get_diesel_cost_by_route"("p_from" "date", "p_to" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_diesel_cost_by_route"("p_from" "date", "p_to" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_route_metrics"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_vehicle_type_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."get_route_metrics"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_vehicle_type_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_route_metrics"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_vehicle_type_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_user_role"("_user_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."get_user_role"("_user_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_user_role"("_user_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_valid_transitions"("p_entity_type" "text", "p_from_stage" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."get_valid_transitions"("p_entity_type" "text", "p_from_stage" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_valid_transitions"("p_entity_type" "text", "p_from_stage" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_vault_secret"("p_name" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."get_vault_secret"("p_name" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_vault_secret"("p_name" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_new_user_profile"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_new_user_profile"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_new_user_profile"() TO "service_role";



GRANT ALL ON FUNCTION "public"."has_any_role"("_user_id" "uuid", "_roles" "public"."app_role"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."has_any_role"("_user_id" "uuid", "_roles" "public"."app_role"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."has_any_role"("_user_id" "uuid", "_roles" "public"."app_role"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."has_profile"("allowed" "public"."user_profile"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."has_profile"("allowed" "public"."user_profile"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."has_profile"("allowed" "public"."user_profile"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") TO "anon";
GRANT ALL ON FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") TO "authenticated";
GRANT ALL ON FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") TO "service_role";



GRANT ALL ON FUNCTION "public"."is_admin"() TO "anon";
GRANT ALL ON FUNCTION "public"."is_admin"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."is_admin"() TO "service_role";



GRANT ALL ON FUNCTION "public"."link_order_to_target_trip"("p_order_id" "uuid", "p_trip_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."link_order_to_target_trip"("p_order_id" "uuid", "p_trip_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."link_order_to_target_trip"("p_order_id" "uuid", "p_trip_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."link_order_to_trip"("p_order_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."link_order_to_trip"("p_order_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."link_order_to_trip"("p_order_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."mask_cep"("input" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."mask_cep"("input" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."mask_cep"("input" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."mask_cnpj"("input" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."mask_cnpj"("input" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."mask_cnpj"("input" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."mask_cpf"("input" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."mask_cpf"("input" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."mask_cpf"("input" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."mask_plate"("input" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."mask_plate"("input" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."mask_plate"("input" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."moddatetime"() TO "postgres";
GRANT ALL ON FUNCTION "public"."moddatetime"() TO "anon";
GRANT ALL ON FUNCTION "public"."moddatetime"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."moddatetime"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."next_collection_order_seq"("p_year" integer, "p_month" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."next_collection_order_seq"("p_year" integer, "p_month" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."next_collection_order_seq"("p_year" integer, "p_month" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."next_collection_order_seq"("p_year" integer, "p_month" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."norm_plate"("input" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."norm_plate"("input" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."norm_plate"("input" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."normalize_clients"() TO "service_role";



GRANT ALL ON FUNCTION "public"."normalize_owners"() TO "service_role";



GRANT ALL ON FUNCTION "public"."normalize_vehicles"() TO "service_role";



GRANT ALL ON FUNCTION "public"."only_digits"("input" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."only_digits"("input" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."only_digits"("input" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."price_table_rows_no_overlap"() TO "anon";
GRANT ALL ON FUNCTION "public"."price_table_rows_no_overlap"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."price_table_rows_no_overlap"() TO "service_role";



GRANT ALL ON FUNCTION "public"."rank_drivers_for_quote"("p_vehicle_type_id" "uuid", "p_origin_city" "text", "p_origin_state" character varying, "p_dest_city" "text", "p_dest_state" character varying, "p_min_quality_score" integer, "p_w_proximity" integer, "p_w_history" integer, "p_w_quality" integer, "p_w_price" integer, "p_max_results" integer, "p_exclude_driver_ids" "uuid"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."rank_drivers_for_quote"("p_vehicle_type_id" "uuid", "p_origin_city" "text", "p_origin_state" character varying, "p_dest_city" "text", "p_dest_state" character varying, "p_min_quality_score" integer, "p_w_proximity" integer, "p_w_history" integer, "p_w_quality" integer, "p_w_price" integer, "p_max_results" integer, "p_exclude_driver_ids" "uuid"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."rank_drivers_for_quote"("p_vehicle_type_id" "uuid", "p_origin_city" "text", "p_origin_state" character varying, "p_dest_city" "text", "p_dest_state" character varying, "p_min_quality_score" integer, "p_w_proximity" integer, "p_w_history" integer, "p_w_quality" integer, "p_w_price" integer, "p_max_results" integer, "p_exclude_driver_ids" "uuid"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."rls_auto_enable"() TO "anon";
GRANT ALL ON FUNCTION "public"."rls_auto_enable"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."rls_auto_enable"() TO "service_role";



GRANT ALL ON FUNCTION "public"."send_queue_reject_blocked_contact"() TO "anon";
GRANT ALL ON FUNCTION "public"."send_queue_reject_blocked_contact"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."send_queue_reject_blocked_contact"() TO "service_role";



GRANT ALL ON FUNCTION "public"."set_os_number"() TO "anon";
GRANT ALL ON FUNCTION "public"."set_os_number"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_os_number"() TO "service_role";



GRANT ALL ON FUNCTION "public"."set_quote_code"() TO "anon";
GRANT ALL ON FUNCTION "public"."set_quote_code"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_quote_code"() TO "service_role";



GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."set_user_profile"("target_user_id" "uuid", "new_profile" "public"."user_profile") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."set_user_profile"("target_user_id" "uuid", "new_profile" "public"."user_profile") TO "anon";
GRANT ALL ON FUNCTION "public"."set_user_profile"("target_user_id" "uuid", "new_profile" "public"."user_profile") TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_user_profile"("target_user_id" "uuid", "new_profile" "public"."user_profile") TO "service_role";



GRANT ALL ON FUNCTION "public"."sync_cost_items_from_breakdown"("p_trip_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."sync_cost_items_from_breakdown"("p_trip_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sync_cost_items_from_breakdown"("p_trip_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."sync_financial_doc_amount_on_carreteiro_change"() TO "anon";
GRANT ALL ON FUNCTION "public"."sync_financial_doc_amount_on_carreteiro_change"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."sync_financial_doc_amount_on_carreteiro_change"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tr_identify_consolidation_on_quote_insert"() TO "anon";
GRANT ALL ON FUNCTION "public"."tr_identify_consolidation_on_quote_insert"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tr_identify_consolidation_on_quote_insert"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tr_identify_consolidation_v7"() TO "anon";
GRANT ALL ON FUNCTION "public"."tr_identify_consolidation_v7"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tr_identify_consolidation_v7"() TO "service_role";



GRANT ALL ON FUNCTION "public"."try_auto_group_order_to_trip"() TO "anon";
GRANT ALL ON FUNCTION "public"."try_auto_group_order_to_trip"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."try_auto_group_order_to_trip"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_company_settings_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_company_settings_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_company_settings_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_delivery_assessments_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_delivery_assessments_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_delivery_assessments_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_driver_qualification_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_driver_qualification_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_driver_qualification_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_load_composition_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_load_composition_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_load_composition_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_pricing_route_overrides_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_pricing_route_overrides_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_pricing_route_overrides_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_quote_contracts_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_quote_contracts_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_quote_contracts_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "service_role";



GRANT ALL ON FUNCTION "public"."validate_api_key"("p_key" "text", "p_scope" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."validate_api_key"("p_key" "text", "p_scope" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."validate_api_key"("p_key" "text", "p_scope" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."validate_quote_antt_floor"("p_quote_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."validate_quote_antt_floor"("p_quote_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."validate_quote_antt_floor"("p_quote_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."validate_transition"("p_entity_type" "text", "p_entity_id" "uuid", "p_from_stage" "text", "p_to_stage" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."validate_transition"("p_entity_type" "text", "p_entity_id" "uuid", "p_from_stage" "text", "p_to_stage" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."validate_transition"("p_entity_type" "text", "p_entity_id" "uuid", "p_from_stage" "text", "p_to_stage" "text") TO "service_role";












REVOKE ALL ON FUNCTION "vectraclip"."increment_task_cost"("p_task_id" "uuid", "p_delta" numeric) FROM PUBLIC;
GRANT ALL ON FUNCTION "vectraclip"."increment_task_cost"("p_task_id" "uuid", "p_delta" numeric) TO "service_role";



GRANT ALL ON FUNCTION "vectraclip"."read_company_secret"("p_company_id" "uuid", "p_name" "text") TO "authenticated";
GRANT ALL ON FUNCTION "vectraclip"."read_company_secret"("p_company_id" "uuid", "p_name" "text") TO "service_role";



GRANT ALL ON FUNCTION "vectraclip"."sipoc_company_id"() TO "authenticated";















GRANT ALL ON TABLE "public"."agent_jobs" TO "anon";
GRANT ALL ON TABLE "public"."agent_jobs" TO "authenticated";
GRANT ALL ON TABLE "public"."agent_jobs" TO "service_role";



GRANT ALL ON TABLE "public"."ai_budget_config" TO "anon";
GRANT ALL ON TABLE "public"."ai_budget_config" TO "authenticated";
GRANT ALL ON TABLE "public"."ai_budget_config" TO "service_role";



GRANT ALL ON TABLE "public"."ai_insights" TO "anon";
GRANT ALL ON TABLE "public"."ai_insights" TO "authenticated";
GRANT ALL ON TABLE "public"."ai_insights" TO "service_role";



GRANT ALL ON TABLE "public"."ai_usage_tracking" TO "anon";
GRANT ALL ON TABLE "public"."ai_usage_tracking" TO "authenticated";
GRANT ALL ON TABLE "public"."ai_usage_tracking" TO "service_role";



GRANT ALL ON TABLE "public"."antt_floor_rates" TO "anon";
GRANT ALL ON TABLE "public"."antt_floor_rates" TO "authenticated";
GRANT ALL ON TABLE "public"."antt_floor_rates" TO "service_role";



GRANT ALL ON TABLE "public"."antt_violation_alerts" TO "anon";
GRANT ALL ON TABLE "public"."antt_violation_alerts" TO "authenticated";
GRANT ALL ON TABLE "public"."antt_violation_alerts" TO "service_role";



GRANT ALL ON TABLE "public"."approval_requests" TO "anon";
GRANT ALL ON TABLE "public"."approval_requests" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_requests" TO "service_role";



GRANT ALL ON TABLE "public"."approval_rules" TO "anon";
GRANT ALL ON TABLE "public"."approval_rules" TO "authenticated";
GRANT ALL ON TABLE "public"."approval_rules" TO "service_role";



GRANT ALL ON TABLE "public"."audit_logs" TO "anon";
GRANT ALL ON TABLE "public"."audit_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."audit_logs" TO "service_role";



GRANT ALL ON TABLE "public"."clients" TO "anon";
GRANT ALL ON TABLE "public"."clients" TO "authenticated";
GRANT ALL ON TABLE "public"."clients" TO "service_role";



GRANT ALL ON TABLE "public"."cnh_categories" TO "anon";
GRANT ALL ON TABLE "public"."cnh_categories" TO "authenticated";
GRANT ALL ON TABLE "public"."cnh_categories" TO "service_role";



GRANT ALL ON SEQUENCE "public"."cnh_categories_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."cnh_categories_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."cnh_categories_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."collected_data" TO "anon";
GRANT ALL ON TABLE "public"."collected_data" TO "authenticated";
GRANT ALL ON TABLE "public"."collected_data" TO "service_role";



GRANT ALL ON TABLE "public"."collection_orders" TO "anon";
GRANT ALL ON TABLE "public"."collection_orders" TO "authenticated";
GRANT ALL ON TABLE "public"."collection_orders" TO "service_role";



GRANT ALL ON TABLE "public"."commercial_closeout_events" TO "anon";
GRANT ALL ON TABLE "public"."commercial_closeout_events" TO "authenticated";
GRANT ALL ON TABLE "public"."commercial_closeout_events" TO "service_role";



GRANT ALL ON TABLE "public"."commercial_followup_rules" TO "anon";
GRANT ALL ON TABLE "public"."commercial_followup_rules" TO "authenticated";
GRANT ALL ON TABLE "public"."commercial_followup_rules" TO "service_role";



GRANT ALL ON TABLE "public"."commercial_followup_runs" TO "anon";
GRANT ALL ON TABLE "public"."commercial_followup_runs" TO "authenticated";
GRANT ALL ON TABLE "public"."commercial_followup_runs" TO "service_role";



GRANT ALL ON TABLE "public"."commercial_message_events" TO "anon";
GRANT ALL ON TABLE "public"."commercial_message_events" TO "authenticated";
GRANT ALL ON TABLE "public"."commercial_message_events" TO "service_role";



GRANT ALL ON TABLE "public"."commercial_operational_handoffs" TO "anon";
GRANT ALL ON TABLE "public"."commercial_operational_handoffs" TO "authenticated";
GRANT ALL ON TABLE "public"."commercial_operational_handoffs" TO "service_role";



GRANT ALL ON TABLE "public"."company_settings" TO "anon";
GRANT ALL ON TABLE "public"."company_settings" TO "authenticated";
GRANT ALL ON TABLE "public"."company_settings" TO "service_role";



GRANT ALL ON TABLE "public"."compliance_checks" TO "anon";
GRANT ALL ON TABLE "public"."compliance_checks" TO "authenticated";
GRANT ALL ON TABLE "public"."compliance_checks" TO "service_role";



GRANT ALL ON TABLE "public"."conditional_fees" TO "anon";
GRANT ALL ON TABLE "public"."conditional_fees" TO "authenticated";
GRANT ALL ON TABLE "public"."conditional_fees" TO "service_role";



GRANT ALL ON TABLE "public"."delivery_assessments" TO "anon";
GRANT ALL ON TABLE "public"."delivery_assessments" TO "authenticated";
GRANT ALL ON TABLE "public"."delivery_assessments" TO "service_role";



GRANT ALL ON TABLE "public"."delivery_conditions" TO "anon";
GRANT ALL ON TABLE "public"."delivery_conditions" TO "authenticated";
GRANT ALL ON TABLE "public"."delivery_conditions" TO "service_role";



GRANT ALL ON TABLE "public"."discharge_checklist_items" TO "anon";
GRANT ALL ON TABLE "public"."discharge_checklist_items" TO "authenticated";
GRANT ALL ON TABLE "public"."discharge_checklist_items" TO "service_role";



GRANT ALL ON TABLE "public"."documents" TO "anon";
GRANT ALL ON TABLE "public"."documents" TO "authenticated";
GRANT ALL ON TABLE "public"."documents" TO "service_role";



GRANT ALL ON TABLE "public"."driver_offer_ranking_config" TO "anon";
GRANT ALL ON TABLE "public"."driver_offer_ranking_config" TO "authenticated";
GRANT ALL ON TABLE "public"."driver_offer_ranking_config" TO "service_role";



GRANT ALL ON TABLE "public"."driver_offer_sequences" TO "anon";
GRANT ALL ON TABLE "public"."driver_offer_sequences" TO "authenticated";
GRANT ALL ON TABLE "public"."driver_offer_sequences" TO "service_role";



GRANT ALL ON TABLE "public"."driver_offers" TO "anon";
GRANT ALL ON TABLE "public"."driver_offers" TO "authenticated";
GRANT ALL ON TABLE "public"."driver_offers" TO "service_role";



GRANT ALL ON TABLE "public"."driver_qualifications" TO "anon";
GRANT ALL ON TABLE "public"."driver_qualifications" TO "authenticated";
GRANT ALL ON TABLE "public"."driver_qualifications" TO "service_role";



GRANT ALL ON TABLE "public"."drivers" TO "anon";
GRANT ALL ON TABLE "public"."drivers" TO "authenticated";
GRANT ALL ON TABLE "public"."drivers" TO "service_role";



GRANT ALL ON TABLE "public"."edge_function_api_keys" TO "anon";
GRANT ALL ON TABLE "public"."edge_function_api_keys" TO "authenticated";
GRANT ALL ON TABLE "public"."edge_function_api_keys" TO "service_role";



GRANT ALL ON TABLE "public"."equipment_rental_rates" TO "anon";
GRANT ALL ON TABLE "public"."equipment_rental_rates" TO "authenticated";
GRANT ALL ON TABLE "public"."equipment_rental_rates" TO "service_role";



GRANT ALL ON TABLE "public"."financial_documents" TO "anon";
GRANT ALL ON TABLE "public"."financial_documents" TO "authenticated";
GRANT ALL ON TABLE "public"."financial_documents" TO "service_role";



GRANT ALL ON TABLE "public"."financial_installments" TO "anon";
GRANT ALL ON TABLE "public"."financial_installments" TO "authenticated";
GRANT ALL ON TABLE "public"."financial_installments" TO "service_role";



GRANT ALL ON TABLE "public"."financial_documents_kanban" TO "anon";
GRANT ALL ON TABLE "public"."financial_documents_kanban" TO "authenticated";
GRANT ALL ON TABLE "public"."financial_documents_kanban" TO "service_role";



GRANT ALL ON TABLE "public"."orders" TO "anon";
GRANT ALL ON TABLE "public"."orders" TO "authenticated";
GRANT ALL ON TABLE "public"."orders" TO "service_role";



GRANT ALL ON TABLE "public"."payment_proofs" TO "anon";
GRANT ALL ON TABLE "public"."payment_proofs" TO "authenticated";
GRANT ALL ON TABLE "public"."payment_proofs" TO "service_role";



GRANT ALL ON TABLE "public"."payment_terms" TO "anon";
GRANT ALL ON TABLE "public"."payment_terms" TO "authenticated";
GRANT ALL ON TABLE "public"."payment_terms" TO "service_role";



GRANT ALL ON TABLE "public"."v_order_payment_reconciliation" TO "anon";
GRANT ALL ON TABLE "public"."v_order_payment_reconciliation" TO "authenticated";
GRANT ALL ON TABLE "public"."v_order_payment_reconciliation" TO "service_role";



GRANT ALL ON TABLE "public"."vehicle_types" TO "anon";
GRANT ALL ON TABLE "public"."vehicle_types" TO "authenticated";
GRANT ALL ON TABLE "public"."vehicle_types" TO "service_role";



GRANT ALL ON TABLE "public"."financial_payable_kanban" TO "anon";
GRANT ALL ON TABLE "public"."financial_payable_kanban" TO "authenticated";
GRANT ALL ON TABLE "public"."financial_payable_kanban" TO "service_role";



GRANT ALL ON TABLE "public"."quote_payment_proofs" TO "anon";
GRANT ALL ON TABLE "public"."quote_payment_proofs" TO "authenticated";
GRANT ALL ON TABLE "public"."quote_payment_proofs" TO "service_role";



GRANT ALL ON TABLE "public"."quotes" TO "anon";
GRANT ALL ON TABLE "public"."quotes" TO "authenticated";
GRANT ALL ON TABLE "public"."quotes" TO "service_role";



GRANT ALL ON TABLE "public"."v_quote_payment_reconciliation" TO "anon";
GRANT ALL ON TABLE "public"."v_quote_payment_reconciliation" TO "authenticated";
GRANT ALL ON TABLE "public"."v_quote_payment_reconciliation" TO "service_role";



GRANT ALL ON TABLE "public"."financial_receivable_kanban" TO "anon";
GRANT ALL ON TABLE "public"."financial_receivable_kanban" TO "authenticated";
GRANT ALL ON TABLE "public"."financial_receivable_kanban" TO "service_role";



GRANT ALL ON TABLE "public"."order_gris_services" TO "anon";
GRANT ALL ON TABLE "public"."order_gris_services" TO "authenticated";
GRANT ALL ON TABLE "public"."order_gris_services" TO "service_role";



GRANT ALL ON TABLE "public"."gris_service_items" TO "anon";
GRANT ALL ON TABLE "public"."gris_service_items" TO "authenticated";
GRANT ALL ON TABLE "public"."gris_service_items" TO "service_role";



GRANT ALL ON TABLE "public"."gris_services" TO "anon";
GRANT ALL ON TABLE "public"."gris_services" TO "authenticated";
GRANT ALL ON TABLE "public"."gris_services" TO "service_role";



GRANT ALL ON TABLE "public"."icms_rates" TO "anon";
GRANT ALL ON TABLE "public"."icms_rates" TO "authenticated";
GRANT ALL ON TABLE "public"."icms_rates" TO "service_role";



GRANT ALL ON TABLE "public"."insurance_logs" TO "anon";
GRANT ALL ON TABLE "public"."insurance_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."insurance_logs" TO "service_role";



GRANT ALL ON TABLE "public"."insurance_metrics_error_breakdown" TO "anon";
GRANT ALL ON TABLE "public"."insurance_metrics_error_breakdown" TO "authenticated";
GRANT ALL ON TABLE "public"."insurance_metrics_error_breakdown" TO "service_role";



GRANT ALL ON TABLE "public"."insurance_metrics_latency" TO "anon";
GRANT ALL ON TABLE "public"."insurance_metrics_latency" TO "authenticated";
GRANT ALL ON TABLE "public"."insurance_metrics_latency" TO "service_role";



GRANT ALL ON TABLE "public"."insurance_metrics_volume" TO "anon";
GRANT ALL ON TABLE "public"."insurance_metrics_volume" TO "authenticated";
GRANT ALL ON TABLE "public"."insurance_metrics_volume" TO "service_role";



GRANT ALL ON TABLE "public"."load_composition_discount_breakdown" TO "anon";
GRANT ALL ON TABLE "public"."load_composition_discount_breakdown" TO "authenticated";
GRANT ALL ON TABLE "public"."load_composition_discount_breakdown" TO "service_role";



GRANT ALL ON TABLE "public"."load_composition_discount_summary" TO "anon";
GRANT ALL ON TABLE "public"."load_composition_discount_summary" TO "authenticated";
GRANT ALL ON TABLE "public"."load_composition_discount_summary" TO "service_role";



GRANT ALL ON TABLE "public"."load_composition_metrics" TO "anon";
GRANT ALL ON TABLE "public"."load_composition_metrics" TO "authenticated";
GRANT ALL ON TABLE "public"."load_composition_metrics" TO "service_role";



GRANT ALL ON TABLE "public"."load_composition_routings" TO "anon";
GRANT ALL ON TABLE "public"."load_composition_routings" TO "authenticated";
GRANT ALL ON TABLE "public"."load_composition_routings" TO "service_role";



GRANT ALL ON TABLE "public"."load_composition_suggestions" TO "anon";
GRANT ALL ON TABLE "public"."load_composition_suggestions" TO "authenticated";
GRANT ALL ON TABLE "public"."load_composition_suggestions" TO "service_role";



GRANT ALL ON TABLE "public"."load_composition_summary" TO "anon";
GRANT ALL ON TABLE "public"."load_composition_summary" TO "authenticated";
GRANT ALL ON TABLE "public"."load_composition_summary" TO "service_role";



GRANT ALL ON TABLE "public"."logistics_traffic_rules" TO "anon";
GRANT ALL ON TABLE "public"."logistics_traffic_rules" TO "authenticated";
GRANT ALL ON TABLE "public"."logistics_traffic_rules" TO "service_role";



GRANT ALL ON TABLE "public"."ltl_parameters" TO "anon";
GRANT ALL ON TABLE "public"."ltl_parameters" TO "authenticated";
GRANT ALL ON TABLE "public"."ltl_parameters" TO "service_role";



GRANT ALL ON TABLE "public"."market_indices" TO "anon";
GRANT ALL ON TABLE "public"."market_indices" TO "authenticated";
GRANT ALL ON TABLE "public"."market_indices" TO "service_role";



GRANT ALL ON TABLE "public"."mirofish_monthly_revenue" TO "anon";
GRANT ALL ON TABLE "public"."mirofish_monthly_revenue" TO "authenticated";
GRANT ALL ON TABLE "public"."mirofish_monthly_revenue" TO "service_role";



GRANT ALL ON SEQUENCE "public"."mirofish_monthly_revenue_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."mirofish_monthly_revenue_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."mirofish_monthly_revenue_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."mirofish_recommendations" TO "anon";
GRANT ALL ON TABLE "public"."mirofish_recommendations" TO "authenticated";
GRANT ALL ON TABLE "public"."mirofish_recommendations" TO "service_role";



GRANT ALL ON TABLE "public"."mirofish_reports" TO "anon";
GRANT ALL ON TABLE "public"."mirofish_reports" TO "authenticated";
GRANT ALL ON TABLE "public"."mirofish_reports" TO "service_role";



GRANT ALL ON TABLE "public"."mirofish_route_insights" TO "anon";
GRANT ALL ON TABLE "public"."mirofish_route_insights" TO "authenticated";
GRANT ALL ON TABLE "public"."mirofish_route_insights" TO "service_role";



GRANT ALL ON TABLE "public"."mirofish_shipper_insights" TO "anon";
GRANT ALL ON TABLE "public"."mirofish_shipper_insights" TO "authenticated";
GRANT ALL ON TABLE "public"."mirofish_shipper_insights" TO "service_role";



GRANT ALL ON TABLE "public"."news_items" TO "anon";
GRANT ALL ON TABLE "public"."news_items" TO "authenticated";
GRANT ALL ON TABLE "public"."news_items" TO "service_role";



GRANT ALL ON TABLE "public"."notification_logs" TO "anon";
GRANT ALL ON TABLE "public"."notification_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."notification_logs" TO "service_role";



GRANT ALL ON TABLE "public"."notification_queue" TO "anon";
GRANT ALL ON TABLE "public"."notification_queue" TO "authenticated";
GRANT ALL ON TABLE "public"."notification_queue" TO "service_role";



GRANT ALL ON TABLE "public"."notification_templates" TO "anon";
GRANT ALL ON TABLE "public"."notification_templates" TO "authenticated";
GRANT ALL ON TABLE "public"."notification_templates" TO "service_role";



GRANT ALL ON TABLE "public"."ntc_articles_seen" TO "anon";
GRANT ALL ON TABLE "public"."ntc_articles_seen" TO "authenticated";
GRANT ALL ON TABLE "public"."ntc_articles_seen" TO "service_role";



GRANT ALL ON TABLE "public"."ntc_cost_indices" TO "anon";
GRANT ALL ON TABLE "public"."ntc_cost_indices" TO "authenticated";
GRANT ALL ON TABLE "public"."ntc_cost_indices" TO "service_role";



GRANT ALL ON TABLE "public"."ntc_fuel_reference" TO "anon";
GRANT ALL ON TABLE "public"."ntc_fuel_reference" TO "authenticated";
GRANT ALL ON TABLE "public"."ntc_fuel_reference" TO "service_role";



GRANT ALL ON TABLE "public"."ntc_scrape_log" TO "anon";
GRANT ALL ON TABLE "public"."ntc_scrape_log" TO "authenticated";
GRANT ALL ON TABLE "public"."ntc_scrape_log" TO "service_role";



GRANT ALL ON TABLE "public"."occurrences" TO "anon";
GRANT ALL ON TABLE "public"."occurrences" TO "authenticated";
GRANT ALL ON TABLE "public"."occurrences" TO "service_role";



GRANT ALL ON TABLE "public"."operational_reports" TO "anon";
GRANT ALL ON TABLE "public"."operational_reports" TO "authenticated";
GRANT ALL ON TABLE "public"."operational_reports" TO "service_role";



GRANT ALL ON TABLE "public"."order_documents" TO "anon";
GRANT ALL ON TABLE "public"."order_documents" TO "authenticated";
GRANT ALL ON TABLE "public"."order_documents" TO "service_role";



GRANT ALL ON TABLE "public"."trip_orders" TO "anon";
GRANT ALL ON TABLE "public"."trip_orders" TO "authenticated";
GRANT ALL ON TABLE "public"."trip_orders" TO "service_role";



GRANT ALL ON TABLE "public"."orders_rs_per_km" TO "anon";
GRANT ALL ON TABLE "public"."orders_rs_per_km" TO "authenticated";
GRANT ALL ON TABLE "public"."orders_rs_per_km" TO "service_role";



GRANT ALL ON TABLE "public"."owners" TO "anon";
GRANT ALL ON TABLE "public"."owners" TO "authenticated";
GRANT ALL ON TABLE "public"."owners" TO "service_role";



GRANT ALL ON TABLE "public"."partner_quotes" TO "anon";
GRANT ALL ON TABLE "public"."partner_quotes" TO "authenticated";
GRANT ALL ON TABLE "public"."partner_quotes" TO "service_role";



GRANT ALL ON TABLE "public"."partner_shippers" TO "anon";
GRANT ALL ON TABLE "public"."partner_shippers" TO "authenticated";
GRANT ALL ON TABLE "public"."partner_shippers" TO "service_role";



GRANT ALL ON TABLE "public"."partner_tokens" TO "anon";
GRANT ALL ON TABLE "public"."partner_tokens" TO "authenticated";
GRANT ALL ON TABLE "public"."partner_tokens" TO "service_role";



GRANT ALL ON TABLE "public"."partner_users" TO "anon";
GRANT ALL ON TABLE "public"."partner_users" TO "authenticated";
GRANT ALL ON TABLE "public"."partner_users" TO "service_role";



GRANT ALL ON TABLE "public"."petrobras_diesel_prices" TO "anon";
GRANT ALL ON TABLE "public"."petrobras_diesel_prices" TO "authenticated";
GRANT ALL ON TABLE "public"."petrobras_diesel_prices" TO "service_role";



GRANT ALL ON TABLE "public"."price_table_rows" TO "anon";
GRANT ALL ON TABLE "public"."price_table_rows" TO "authenticated";
GRANT ALL ON TABLE "public"."price_table_rows" TO "service_role";



GRANT ALL ON TABLE "public"."price_tables" TO "anon";
GRANT ALL ON TABLE "public"."price_tables" TO "authenticated";
GRANT ALL ON TABLE "public"."price_tables" TO "service_role";



GRANT ALL ON TABLE "public"."pricing_parameters" TO "anon";
GRANT ALL ON TABLE "public"."pricing_parameters" TO "authenticated";
GRANT ALL ON TABLE "public"."pricing_parameters" TO "service_role";



GRANT ALL ON TABLE "public"."pricing_route_overrides" TO "anon";
GRANT ALL ON TABLE "public"."pricing_route_overrides" TO "authenticated";
GRANT ALL ON TABLE "public"."pricing_route_overrides" TO "service_role";



GRANT ALL ON TABLE "public"."pricing_rules_config" TO "anon";
GRANT ALL ON TABLE "public"."pricing_rules_config" TO "authenticated";
GRANT ALL ON TABLE "public"."pricing_rules_config" TO "service_role";



GRANT ALL ON TABLE "public"."processes" TO "anon";
GRANT ALL ON TABLE "public"."processes" TO "authenticated";
GRANT ALL ON TABLE "public"."processes" TO "service_role";



GRANT ALL ON TABLE "public"."product_dimensions" TO "anon";
GRANT ALL ON TABLE "public"."product_dimensions" TO "authenticated";
GRANT ALL ON TABLE "public"."product_dimensions" TO "service_role";



GRANT ALL ON TABLE "public"."profiles" TO "anon";
GRANT ALL ON TABLE "public"."profiles" TO "authenticated";
GRANT ALL ON TABLE "public"."profiles" TO "service_role";



GRANT UPDATE("full_name") ON TABLE "public"."profiles" TO "authenticated";



GRANT UPDATE("updated_at") ON TABLE "public"."profiles" TO "authenticated";



GRANT ALL ON TABLE "public"."quote_contracts" TO "anon";
GRANT ALL ON TABLE "public"."quote_contracts" TO "authenticated";
GRANT ALL ON TABLE "public"."quote_contracts" TO "service_role";



GRANT ALL ON TABLE "public"."quote_route_stops" TO "anon";
GRANT ALL ON TABLE "public"."quote_route_stops" TO "authenticated";
GRANT ALL ON TABLE "public"."quote_route_stops" TO "service_role";



GRANT ALL ON TABLE "public"."regulatory_updates" TO "anon";
GRANT ALL ON TABLE "public"."regulatory_updates" TO "authenticated";
GRANT ALL ON TABLE "public"."regulatory_updates" TO "service_role";



GRANT ALL ON TABLE "public"."risk_costs" TO "anon";
GRANT ALL ON TABLE "public"."risk_costs" TO "authenticated";
GRANT ALL ON TABLE "public"."risk_costs" TO "service_role";



GRANT ALL ON TABLE "public"."risk_evaluations" TO "anon";
GRANT ALL ON TABLE "public"."risk_evaluations" TO "authenticated";
GRANT ALL ON TABLE "public"."risk_evaluations" TO "service_role";



GRANT ALL ON TABLE "public"."risk_evidence" TO "anon";
GRANT ALL ON TABLE "public"."risk_evidence" TO "authenticated";
GRANT ALL ON TABLE "public"."risk_evidence" TO "service_role";



GRANT ALL ON TABLE "public"."risk_policies" TO "anon";
GRANT ALL ON TABLE "public"."risk_policies" TO "authenticated";
GRANT ALL ON TABLE "public"."risk_policies" TO "service_role";



GRANT ALL ON TABLE "public"."risk_policy_rules" TO "anon";
GRANT ALL ON TABLE "public"."risk_policy_rules" TO "authenticated";
GRANT ALL ON TABLE "public"."risk_policy_rules" TO "service_role";



GRANT ALL ON TABLE "public"."risk_services_catalog" TO "anon";
GRANT ALL ON TABLE "public"."risk_services_catalog" TO "authenticated";
GRANT ALL ON TABLE "public"."risk_services_catalog" TO "service_role";



GRANT ALL ON TABLE "public"."route_metrics_config" TO "anon";
GRANT ALL ON TABLE "public"."route_metrics_config" TO "authenticated";
GRANT ALL ON TABLE "public"."route_metrics_config" TO "service_role";



GRANT ALL ON TABLE "public"."settings" TO "anon";
GRANT ALL ON TABLE "public"."settings" TO "authenticated";
GRANT ALL ON TABLE "public"."settings" TO "service_role";



GRANT ALL ON TABLE "public"."shippers" TO "anon";
GRANT ALL ON TABLE "public"."shippers" TO "authenticated";
GRANT ALL ON TABLE "public"."shippers" TO "service_role";



GRANT ALL ON TABLE "public"."sipoc_customers" TO "anon";
GRANT ALL ON TABLE "public"."sipoc_customers" TO "authenticated";
GRANT ALL ON TABLE "public"."sipoc_customers" TO "service_role";



GRANT ALL ON TABLE "public"."sipoc_decisions" TO "anon";
GRANT ALL ON TABLE "public"."sipoc_decisions" TO "authenticated";
GRANT ALL ON TABLE "public"."sipoc_decisions" TO "service_role";



GRANT ALL ON TABLE "public"."sipoc_inputs" TO "anon";
GRANT ALL ON TABLE "public"."sipoc_inputs" TO "authenticated";
GRANT ALL ON TABLE "public"."sipoc_inputs" TO "service_role";



GRANT ALL ON TABLE "public"."sipoc_maps" TO "anon";
GRANT ALL ON TABLE "public"."sipoc_maps" TO "authenticated";
GRANT ALL ON TABLE "public"."sipoc_maps" TO "service_role";



GRANT ALL ON TABLE "public"."sipoc_outputs" TO "anon";
GRANT ALL ON TABLE "public"."sipoc_outputs" TO "authenticated";
GRANT ALL ON TABLE "public"."sipoc_outputs" TO "service_role";



GRANT ALL ON TABLE "public"."sipoc_suppliers" TO "anon";
GRANT ALL ON TABLE "public"."sipoc_suppliers" TO "authenticated";
GRANT ALL ON TABLE "public"."sipoc_suppliers" TO "service_role";



GRANT ALL ON TABLE "public"."skill_executions" TO "anon";
GRANT ALL ON TABLE "public"."skill_executions" TO "authenticated";
GRANT ALL ON TABLE "public"."skill_executions" TO "service_role";



GRANT ALL ON TABLE "public"."tac_rates" TO "anon";
GRANT ALL ON TABLE "public"."tac_rates" TO "authenticated";
GRANT ALL ON TABLE "public"."tac_rates" TO "service_role";



GRANT ALL ON TABLE "public"."tasks" TO "anon";
GRANT ALL ON TABLE "public"."tasks" TO "authenticated";
GRANT ALL ON TABLE "public"."tasks" TO "service_role";



GRANT ALL ON TABLE "public"."toll_routes" TO "anon";
GRANT ALL ON TABLE "public"."toll_routes" TO "authenticated";
GRANT ALL ON TABLE "public"."toll_routes" TO "service_role";



GRANT ALL ON TABLE "public"."trip_cost_items" TO "anon";
GRANT ALL ON TABLE "public"."trip_cost_items" TO "authenticated";
GRANT ALL ON TABLE "public"."trip_cost_items" TO "service_role";



GRANT ALL ON TABLE "public"."trip_financial_summary" TO "anon";
GRANT ALL ON TABLE "public"."trip_financial_summary" TO "authenticated";
GRANT ALL ON TABLE "public"."trip_financial_summary" TO "service_role";



GRANT ALL ON TABLE "public"."unloading_cost_rates" TO "anon";
GRANT ALL ON TABLE "public"."unloading_cost_rates" TO "authenticated";
GRANT ALL ON TABLE "public"."unloading_cost_rates" TO "service_role";



GRANT ALL ON TABLE "public"."user_roles" TO "anon";
GRANT ALL ON TABLE "public"."user_roles" TO "authenticated";
GRANT ALL ON TABLE "public"."user_roles" TO "service_role";



GRANT ALL ON TABLE "public"."v_cash_flow_summary" TO "anon";
GRANT ALL ON TABLE "public"."v_cash_flow_summary" TO "authenticated";
GRANT ALL ON TABLE "public"."v_cash_flow_summary" TO "service_role";



GRANT ALL ON TABLE "public"."v_quote_order_divergence" TO "anon";
GRANT ALL ON TABLE "public"."v_quote_order_divergence" TO "authenticated";
GRANT ALL ON TABLE "public"."v_quote_order_divergence" TO "service_role";



GRANT ALL ON TABLE "public"."v_trip_financial_details" TO "anon";
GRANT ALL ON TABLE "public"."v_trip_financial_details" TO "authenticated";
GRANT ALL ON TABLE "public"."v_trip_financial_details" TO "service_role";



GRANT ALL ON TABLE "public"."v_trip_payment_reconciliation" TO "anon";
GRANT ALL ON TABLE "public"."v_trip_payment_reconciliation" TO "authenticated";
GRANT ALL ON TABLE "public"."v_trip_payment_reconciliation" TO "service_role";



GRANT ALL ON TABLE "public"."valid_users" TO "anon";
GRANT ALL ON TABLE "public"."valid_users" TO "authenticated";
GRANT ALL ON TABLE "public"."valid_users" TO "service_role";



GRANT ALL ON TABLE "public"."vectra_manifestos" TO "anon";
GRANT ALL ON TABLE "public"."vectra_manifestos" TO "authenticated";
GRANT ALL ON TABLE "public"."vectra_manifestos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."vectra_manifestos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."vectra_manifestos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."vectra_manifestos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."vectra_motoristas_margem" TO "anon";
GRANT ALL ON TABLE "public"."vectra_motoristas_margem" TO "authenticated";
GRANT ALL ON TABLE "public"."vectra_motoristas_margem" TO "service_role";



GRANT ALL ON SEQUENCE "public"."vectra_motoristas_margem_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."vectra_motoristas_margem_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."vectra_motoristas_margem_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."vectra_rentabilidade_rotas" TO "anon";
GRANT ALL ON TABLE "public"."vectra_rentabilidade_rotas" TO "authenticated";
GRANT ALL ON TABLE "public"."vectra_rentabilidade_rotas" TO "service_role";



GRANT ALL ON SEQUENCE "public"."vectra_rentabilidade_rotas_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."vectra_rentabilidade_rotas_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."vectra_rentabilidade_rotas_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."vehicles" TO "anon";
GRANT ALL ON TABLE "public"."vehicles" TO "authenticated";
GRANT ALL ON TABLE "public"."vehicles" TO "service_role";



GRANT ALL ON TABLE "public"."vw_ntc_publish_pattern" TO "anon";
GRANT ALL ON TABLE "public"."vw_ntc_publish_pattern" TO "authenticated";
GRANT ALL ON TABLE "public"."vw_ntc_publish_pattern" TO "service_role";



GRANT ALL ON TABLE "public"."vw_ntc_scrape_history" TO "anon";
GRANT ALL ON TABLE "public"."vw_ntc_scrape_history" TO "authenticated";
GRANT ALL ON TABLE "public"."vw_ntc_scrape_history" TO "service_role";



GRANT ALL ON TABLE "public"."vw_order_risk_status" TO "anon";
GRANT ALL ON TABLE "public"."vw_order_risk_status" TO "authenticated";
GRANT ALL ON TABLE "public"."vw_order_risk_status" TO "service_role";



GRANT ALL ON TABLE "public"."vw_trip_risk_summary" TO "anon";
GRANT ALL ON TABLE "public"."vw_trip_risk_summary" TO "authenticated";
GRANT ALL ON TABLE "public"."vw_trip_risk_summary" TO "service_role";



GRANT ALL ON TABLE "public"."waiting_time_rules" TO "anon";
GRANT ALL ON TABLE "public"."waiting_time_rules" TO "authenticated";
GRANT ALL ON TABLE "public"."waiting_time_rules" TO "service_role";



GRANT ALL ON TABLE "public"."workflow_definitions" TO "anon";
GRANT ALL ON TABLE "public"."workflow_definitions" TO "authenticated";
GRANT ALL ON TABLE "public"."workflow_definitions" TO "service_role";



GRANT ALL ON TABLE "public"."workflow_event_logs" TO "anon";
GRANT ALL ON TABLE "public"."workflow_event_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."workflow_event_logs" TO "service_role";



GRANT ALL ON TABLE "public"."workflow_events" TO "anon";
GRANT ALL ON TABLE "public"."workflow_events" TO "authenticated";
GRANT ALL ON TABLE "public"."workflow_events" TO "service_role";



GRANT ALL ON TABLE "public"."workflow_transitions" TO "anon";
GRANT ALL ON TABLE "public"."workflow_transitions" TO "authenticated";
GRANT ALL ON TABLE "public"."workflow_transitions" TO "service_role";









GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."adapter_catalog" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."adapter_catalog" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."adapter_field_definitions" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."adapter_field_definitions" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_adapter_configs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_adapter_configs" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_execution_configs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_execution_configs" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."agent_specialties" TO "authenticated";
GRANT SELECT,INSERT,UPDATE ON TABLE "vectraclip"."agent_specialties" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_specialty_configs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agent_specialty_configs" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agents" TO "service_role";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."agents" TO "authenticated";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."app_users" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."app_users" TO "authenticated";



GRANT SELECT,INSERT,UPDATE ON TABLE "vectraclip"."approvals" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."approvals" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."companies" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."companies" TO "authenticated";



GRANT SELECT ON TABLE "vectraclip"."company_secrets" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."company_secrets" TO "service_role";



GRANT ALL ON TABLE "vectraclip"."goals" TO "authenticated";
GRANT ALL ON TABLE "vectraclip"."goals" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."heartbeats" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."heartbeats" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."hermes_sender_whitelist" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."hermes_sender_whitelist" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."incident_audit" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."incident_audit" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."incidents" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."incidents" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."kronos_rules" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."kronos_rules" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."llm_models" TO "service_role";
GRANT SELECT ON TABLE "vectraclip"."llm_models" TO "authenticated";



GRANT SELECT ON TABLE "vectraclip"."managed_agent_sessions" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."managed_agent_sessions" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."managed_agent_turn_logs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."managed_agent_turn_logs" TO "service_role";



GRANT SELECT,USAGE ON SEQUENCE "vectraclip"."managed_agent_turn_logs_id_seq" TO "authenticated";
GRANT SELECT,USAGE ON SEQUENCE "vectraclip"."managed_agent_turn_logs_id_seq" TO "service_role";
GRANT SELECT,USAGE ON SEQUENCE "vectraclip"."managed_agent_turn_logs_id_seq" TO "anon";



GRANT SELECT ON TABLE "vectraclip"."projects" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."projects" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."prospect_profiles" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."prospect_profiles" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."routines" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."routines" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."run_transcript_entries" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."run_transcript_entries" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."runs" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."runs" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_companies" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_companies" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_components" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_components" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_edges" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_edges" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_positions" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_positions" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_processes" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_processes" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_raci" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_raci" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."sipoc_sector_baselines" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_sector_baselines" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_sectors" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."sipoc_sectors" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."tasks" TO "service_role";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."tasks" TO "authenticated";



GRANT SELECT ON TABLE "vectraclip"."task_tree_status" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."task_tree_status" TO "service_role";



GRANT SELECT ON TABLE "vectraclip"."tasks_block_log" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."tasks_block_log" TO "service_role";



GRANT SELECT,USAGE ON SEQUENCE "vectraclip"."tasks_block_log_id_seq" TO "authenticated";
GRANT SELECT,USAGE ON SEQUENCE "vectraclip"."tasks_block_log_id_seq" TO "service_role";
GRANT SELECT,USAGE ON SEQUENCE "vectraclip"."tasks_block_log_id_seq" TO "anon";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."workflow_definitions" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."workflow_definitions" TO "service_role";



GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."workflow_steps" TO "authenticated";
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE "vectraclip"."workflow_steps" TO "service_role";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "vectraclip" GRANT SELECT ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "vectraclip" GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO "service_role";
































