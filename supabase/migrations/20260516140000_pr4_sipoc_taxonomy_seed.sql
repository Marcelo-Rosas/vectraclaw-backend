-- =============================================================================
-- PR4 — Fase A: Seed inicial do marketplace SIPOC (18 templates em 3 verticais)
--
-- Referência: docs/ARCHITECTURE-TO-BE.md Seção 1.6 (SIPOC Marketplace P1).
--
-- 1. Adiciona UNIQUE constraint em (vertical, category, activity_name)
--    pra prevenir duplicação acidental no futuro.
--
-- 2. Insere 18 templates iniciais (idempotente via ON CONFLICT DO NOTHING):
--    - Logística: 6 templates (cotação, captação, follow-up, roteirização,
--      tracking, CT-e)
--    - Financeiro: 6 templates (conciliação, aprovação, cobrança,
--      reconciliação, fechamento, fluxo de caixa)
--    - Fitness: 6 templates (leads Instagram, aula experimental, conversão,
--      onboarding, renovação, churn risk)
--
-- 5W2H seguindo padrão consultivo (objetivo de cada campo):
--   what: o que a atividade faz
--   who: cargo/papel responsável
--   when: gatilho ou cadência
--   where: sistema/local onde acontece
--   why: razão de negócio
--   how: passo-a-passo resumido
--   how_much: custo atual + risco quantificado (alimenta diagnóstico Athena)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. UNIQUE constraint (preserva integridade de marketplace)
-- -----------------------------------------------------------------------------

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'sipoc_taxonomy_global_vertical_category_activity_name_uniq'
      AND table_schema = 'vectraclip'
  ) THEN
    ALTER TABLE vectraclip.sipoc_taxonomy_global
      ADD CONSTRAINT sipoc_taxonomy_global_vertical_category_activity_name_uniq
      UNIQUE (vertical, category, activity_name);
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. Seed dos 18 templates iniciais
-- -----------------------------------------------------------------------------

INSERT INTO vectraclip.sipoc_taxonomy_global
  (vertical, category, activity_name, default_5w2h, suggested_operation_type, description)
VALUES

-- ──────────── LOGÍSTICA ────────────
('logistica', 'Comercial', 'Cotação de Frete',
 '{"what":"Cotar frete para nova OS com 3+ transportadoras","who":"Operador comercial","when":"Imediatamente após confirmação de OS","where":"Sistemas das transportadoras + CFN","why":"Garantir melhor preço/SLA e margem","how":"Submete OS aos brokers → recebe cotações → compara → aprova","how_much":"Margem comercial: 8-15%; tempo manual: 15-40min/cotação"}'::jsonb,
 'freight-quotation',
 'Atividade central do funil comercial de logística. Alta frequência, alta variabilidade de preços.'),

('logistica', 'Comercial', 'Captação de Embarcadores',
 '{"what":"Identificar novos embarcadores potenciais e iniciar contato","who":"SDR / Comercial","when":"Diário (volume alvo por SDR)","where":"LinkedIn, Apollo, e-mail","why":"Pipeline de novos clientes B2B","how":"Pesquisa ICP → enrich (Apollo) → e-mail inicial → follow-up","how_much":"CAC alvo: R$ 2-4k por embarcador; tempo: 30-60min/lead qualificado"}'::jsonb,
 'email_lead',
 'Prospecção outbound B2B com SDR. Híbrida (humano + agentes pra enrichment e templates de mensagem).'),

('logistica', 'Comercial', 'Follow-up de Cotações Pendentes',
 '{"what":"Reativar cotações enviadas há +3 dias sem resposta","who":"Comercial","when":"D+3, D+7, D+14 após cotação","where":"E-mail + WhatsApp","why":"Recuperar oportunidades em conversão","how":"Lista cotações pendentes → e-mail personalizado → registro de resposta","how_much":"Conversão pós follow-up: 15-25%; tempo: 5min/follow-up"}'::jsonb,
 'email_lead',
 'Cadência automatizável. Hoje feito ad-hoc ou esquecido — gargalo comum.'),

('logistica', 'Operação', 'Roteirização de Entregas',
 '{"what":"Calcular rota ótima multi-stop pra entregas do dia","who":"Operador logístico","when":"Manhã do dia da rota","where":"QUALP / Google Maps","why":"Reduzir custo combustível + tempo motorista","how":"Lista entregas → input pro otimizador → ajuste manual → impressão da rota","how_much":"Economia potencial: 10-20% km rodados; tempo manual: 30-60min/dia"}'::jsonb,
 'route-cost-calculation',
 'Algoritmo de roteirização (QUALP/similares). Saída direta pra motorista. Automação pura possível.'),

('logistica', 'Operação', 'Tracking de Carga em Trânsito',
 '{"what":"Monitorar posição/status de cargas ativas e alertar atrasos","who":"Operação / SAC","when":"Contínuo (cargas em trânsito)","where":"Rastreador GPS + transportadora API","why":"Visibilidade pro cliente + early warning de problemas","how":"Pull periódico de status → comparar com ETA → alertar se desvio","how_much":"Insatisfação por falta de info: 30%+ reclamações SAC; tempo monitor: contínuo"}'::jsonb,
 'oracle-research',
 'Atividade ideal pra agent híbrido — automação total se API da transportadora estiver íntegra; humano só em exceções.'),

('logistica', 'Documentação', 'Emissão de CT-e',
 '{"what":"Emitir Conhecimento de Transporte Eletrônico pra cada OS","who":"Faturamento","when":"Antes do embarque","where":"Sistema fiscal + SEFAZ","why":"Obrigação fiscal + nota pro embarcador","how":"Recebe dados da OS → preenche XML → assina → envia SEFAZ → autoriza","how_much":"Custo retrabalho rejeição: R$ 50-200/CT-e; tempo: 10-20min/doc"}'::jsonb,
 NULL,
 'Atividade fiscal regulada (SEFAZ). Automação parcial possível (preenchimento), mas requer human-in-the-loop pra validação.'),

-- ──────────── FINANCEIRO ────────────
('financeiro', 'Contas a Pagar', 'Conciliação Bancária Mensal',
 '{"what":"Cruzar OFX bancário com lançamentos do planner","who":"Analista Financeiro","when":"Primeiro dia útil do mês seguinte","where":"Sistema do planner financeiro","why":"Detectar divergências de categorização e duplicatas","how":"OFX export + planner CSV → cruza por valor+data → relatório de gaps","how_much":"Risco: erros de classificação fiscal; Custo manual: 4-6h/mês"}'::jsonb,
 'conciliacao-backlog',
 'Atividade padrão de fechamento financeiro mensal. Mapeada em consultorias de logística e PME.'),

('financeiro', 'Contas a Pagar', 'Aprovação de Pagamentos',
 '{"what":"Aprovar lote de pagamentos a fornecedores","who":"CFO / Diretor Financeiro","when":"Semanal (sextas) ou sob demanda","where":"Internet banking + sistema interno","why":"Controle de saída de caixa + governance","how":"Lista pagamentos → revisão → assinatura digital → execução","how_much":"Risco fraude se sem segregação: alto; tempo: 30-60min/semana"}'::jsonb,
 NULL,
 'Híbrida: agent prepara lote + valida fornecedores; humano aprova assinatura final.'),

('financeiro', 'Contas a Receber', 'Cobrança de Inadimplentes',
 '{"what":"Comunicar clientes em atraso e propor regularização","who":"Cobrança","when":"D+5, D+15, D+30 após vencimento","where":"E-mail + WhatsApp + telefone","why":"Reduzir DSO + recuperar receita","how":"Lista vencidos → mensagem por canal preferido → registrar resposta","how_much":"Recuperação D+30: 60-80%; D+90: 30-50%; tempo manual: 10-20min/cliente"}'::jsonb,
 'email_lead',
 'Cadência outbound altamente automatizável. Híbrida com escalada pro humano em casos complexos.'),

('financeiro', 'Contas a Receber', 'Reconciliação de Recebimentos',
 '{"what":"Identificar e baixar títulos a partir do OFX/extrato bancário","who":"Analista Financeiro","when":"Diário","where":"OFX bancário + sistema de cobrança","why":"Atualizar status de títulos + manter DRE em dia","how":"Import OFX → match com títulos abertos → baixar","how_much":"Risco título não baixado: cobrança duplicada; tempo: 30-60min/dia"}'::jsonb,
 'conciliacao-backlog',
 'Automação total possível. Match por valor + data + descrição. Reduz tempo de 60min pra 5min de revisão.'),

('financeiro', 'Análise', 'Fechamento Contábil Mensal',
 '{"what":"Consolidar lançamentos + ajustes + provisões do mês","who":"Contador / Controller","when":"Primeira semana do mês seguinte","where":"Sistema contábil","why":"DRE oficial + base pra impostos + dashboard","how":"Reconciliar contas → ajustes → provisões → fechar período","how_much":"Risco retrabalho: alto se conciliação tiver gaps; tempo: 8-16h/mês"}'::jsonb,
 'financial-audit',
 'Atividade audit-grade. Agent acelera reconciliação + lista pendências; fechamento final é humano.'),

('financeiro', 'Análise', 'Dashboard de Fluxo de Caixa',
 '{"what":"Atualizar projeção de caixa 30/60/90 dias","who":"Controller","when":"Semanal","where":"Excel ou BI tool","why":"Visibilidade pra decisões de investimento/captação","how":"Pull dados a pagar + receber → ajustes manuais → publicar","how_much":"Custo decisão sem visibilidade: alto (oportunidade perdida); tempo: 2-4h/semana"}'::jsonb,
 'oracle-research',
 'Agent puxa dados estruturados + alerta desvios. Humano interpreta cenários.'),

-- ──────────── FITNESS ────────────
('fitness', 'Comercial', 'Captação de Leads via Instagram',
 '{"what":"Identificar e iniciar conversa com leads vindos de Instagram","who":"SDR / Recepção","when":"Contínuo (resposta a interações)","where":"Instagram DM + WhatsApp","why":"Conversão de seguidores em aulas experimentais","how":"Monitor menções/comentários → DM personalizada → qualificação → agendar","how_much":"Conversão DM → aula exp: 20-35%; tempo manual: 3-5min/lead"}'::jsonb,
 'email_lead',
 'Híbrida: agent monitora + envia mensagem inicial; humano fecha qualificação. Apollo + Instagram scraping aplicável.'),

('fitness', 'Comercial', 'Agendamento de Aula Experimental',
 '{"what":"Marcar dia/hora de primeira aula com lead qualificado","who":"Recepção","when":"Após qualificação do lead","where":"Sistema de agenda + WhatsApp","why":"Conversão da intenção em compromisso","how":"Verifica disponibilidade → propõe 2-3 horários → confirma + lembra","how_much":"No-show rate sem lembrete: 30-40%; com lembrete: 10-15%; tempo: 5-10min/agendamento"}'::jsonb,
 NULL,
 'Híbrida: agent gerencia agenda + lembretes; humano só em casos não-padrão.'),

('fitness', 'Comercial', 'Conversão de Aula Experimental em Matrícula',
 '{"what":"Acompanhar lead pós-aula e fechar matrícula","who":"Comercial / Professor","when":"Imediato (pós-aula) + D+1 + D+3","where":"WhatsApp + presencial","why":"Maximizar conversão (alvo: 40-60%)","how":"Pós-aula: pergunta direta → planos/promos → fechamento","how_much":"Conversão média mercado: 40-55%; tempo: 15-30min/lead engajado"}'::jsonb,
 NULL,
 'Atividade relacional, difícil de automatizar 100%. Agent prepara argumentos + monitora intenções; fechamento é humano.'),

('fitness', 'Operação', 'Onboarding de Novo Aluno',
 '{"what":"Coletar dados, preferências e definir treino inicial","who":"Professor + Recepção","when":"Primeira semana pós-matrícula","where":"Sistema interno + presencial","why":"Reduzir churn dos primeiros 30 dias","how":"Anamnese → avaliação física → treino inicial → cadastro app","how_much":"Churn 30d sem onboarding: 25-35%; com onboarding: 10-15%; tempo: 60-90min/aluno"}'::jsonb,
 NULL,
 'Híbrida: agent gera questionário pré-aula + agenda follow-up; humano executa avaliação física.'),

('fitness', 'Retenção', 'Renovação de Matrícula',
 '{"what":"Comunicar vencimento + propor renovação com benefícios","who":"Comercial","when":"D-15 e D-3 antes do vencimento","where":"WhatsApp + e-mail","why":"Manter LTV (lifetime value) de aluno ativo","how":"Lista vencendo → mensagem com promo → confirmar pagamento","how_much":"Taxa renovação ativa: 70-85%; passiva: 40-50%; tempo: 5-10min/aluno"}'::jsonb,
 'email_lead',
 'Cadência automatizável. Agent envia mensagem + processa renovação; humano só em escalações.'),

('fitness', 'Retenção', 'Análise de Churn Risk',
 '{"what":"Identificar alunos com risco de cancelar antes que aconteça","who":"Gerente / Comercial","when":"Semanal","where":"Sistema de frequência + dashboard","why":"Intervenção antecipada antes do cancelamento","how":"Analisa frequência caindo → outros sinais → ação personalizada","how_much":"Redução churn possível: 15-30%; tempo análise: 1-2h/semana"}'::jsonb,
 'oracle-research',
 'Automação total da análise + alerta. Ação de retenção pode ser híbrida (mensagem automatizada ou contato humano).')

ON CONFLICT (vertical, category, activity_name) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 3. Comment de arquivo (auditoria)
-- -----------------------------------------------------------------------------

COMMENT ON TABLE vectraclip.sipoc_taxonomy_global IS
  'Marketplace SIPOC — catálogo global de atividades por vertical/setor. Seed inicial via migration 20260516140000_pr4_sipoc_taxonomy_seed.sql com 18 templates (logística + financeiro + fitness). UNIQUE em (vertical, category, activity_name).';
