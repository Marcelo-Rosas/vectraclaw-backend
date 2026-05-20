-- Negociação parada 7+ dias → follow-up WhatsApp via template Meta followup_vectra.
-- Dispatcher: followup-dispatcher (channel=meta) → notification-hub → Graph API.

ALTER TABLE public.commercial_followup_rules
  DROP CONSTRAINT IF EXISTS commercial_followup_rules_trigger_anchor_check;

ALTER TABLE public.commercial_followup_rules
  ADD CONSTRAINT commercial_followup_rules_trigger_anchor_check
  CHECK (
    trigger_anchor = ANY (
      ARRAY[
        'proposal_sent_at'::text,
        'estimated_loading_date'::text,
        'updated_at'::text
      ]
    )
  );

INSERT INTO public.commercial_followup_rules (
  name,
  active,
  quote_stage,
  trigger_after_minutes,
  channel,
  template_key,
  stop_on_reply,
  stop_on_stage_change,
  max_attempts,
  priority,
  trigger_anchor,
  offset_minutes,
  requires_estimated_loading_date,
  strategy_key
)
VALUES (
  'negociacao_stale_7d_meta',
  true,
  'negociacao',
  10080,
  'meta',
  'followup_vectra',
  true,
  true,
  1,
  5,
  'updated_at',
  10080,
  false,
  'reactivation'
)
ON CONFLICT (name) DO UPDATE SET
  active = EXCLUDED.active,
  quote_stage = EXCLUDED.quote_stage,
  trigger_after_minutes = EXCLUDED.trigger_after_minutes,
  channel = EXCLUDED.channel,
  template_key = EXCLUDED.template_key,
  stop_on_reply = EXCLUDED.stop_on_reply,
  stop_on_stage_change = EXCLUDED.stop_on_stage_change,
  max_attempts = EXCLUDED.max_attempts,
  priority = EXCLUDED.priority,
  trigger_anchor = EXCLUDED.trigger_anchor,
  offset_minutes = EXCLUDED.offset_minutes,
  requires_estimated_loading_date = EXCLUDED.requires_estimated_loading_date,
  strategy_key = EXCLUDED.strategy_key,
  updated_at = now();
