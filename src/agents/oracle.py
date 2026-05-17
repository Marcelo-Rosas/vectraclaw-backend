import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from src.services.gemini_client import DEFAULT_MODEL, generate, stream_generate, extract_metadata, get_client
from src.services.llm_cost import calc_llm_cost

logger = logging.getLogger("Oracle")

# ─────────────────────────────────────────────────────────────────────────────
# Perfis de usuário
# ─────────────────────────────────────────────────────────────────────────────
_PROFILE_LABELS = {
    "beginner": "Iniciante (nunca fez SIPOC/5W2H antes)",
    "advanced": "Analista/Intermediário (conhece BPM)",
    "pmo": "PMO/Especialista (usa SIPOC no dia a dia)",
}

_PROFILE_GUIDANCE = {
    "beginner": (
        "Use linguagem simples, sem jargão. Explique cada conceito brevemente. "
        "Dê exemplos concretos do domínio. Seja encorajador e paciente."
    ),
    "advanced": (
        "Seja direto e objetivo. Pode usar termos técnicos (BPM, SIPOC, 5W2H). "
        "Foque em insights e precisão."
    ),
    "pmo": (
        "Seja extremamente conciso. Use notação formal. "
        "Pergunte apenas o essencial. Priorize automação e gaps."
    ),
}

_STAGE_LABELS = {
    "mapping_suppliers": "S — Suppliers (Fornecedores)",
    "mapping_inputs": "I — Inputs (Insumos/Entradas)",
    "mapping_activities": "P — Process (Atividades/Processo)",
    "activity_5w2h": "5W2H da Atividade",
    "mapping_outputs": "O — Outputs (Saídas/Entregas)",
    "mapping_customers": "C — Customers (Clientes/Destinos)",
    "automation_analysis": "Análise de Automação",
}

_SIPOC_TYPE_LABELS = {
    "supplier": "fornecedor",
    "input": "insumo/entrada",
    "activity": "atividade",
    "output": "saída/entrega",
    "customer": "cliente/destinatário",
}

_W2H_LABELS = {
    "what": "O Quê? (What)",
    "why": "Por Quê? (Why)",
    "who": "Quem? (Who)",
    "where": "Onde? (Where)",
    "when": "Quando? (When)",
    "how": "Como? (How)",
    "howMuch": "Quanto Custa? (How Much)",
}


def _build_system_prompt(domain: str, user_profile: str) -> str:
    profile_label = _PROFILE_LABELS.get(user_profile, _PROFILE_LABELS["advanced"])
    profile_guidance = _PROFILE_GUIDANCE.get(user_profile, _PROFILE_GUIDANCE["advanced"])
    return (
        f"Você é o Oracle, consultor especialista em SIPOC e identificação de oportunidades de automação "
        f"na Vectra.\n\n"
        f"Domínio atual: **{domain}**\n"
        f"Perfil do usuário: {profile_label}\n\n"
        f"Instruções de comportamento:\n"
        f"- {profile_guidance}\n"
        f"- Responda sempre em PT-BR\n"
        f"- Use markdown básico (**negrito**, *itálico*, listas com -)\n"
        f"- Respostas curtas: máximo 4-5 linhas por mensagem\n"
        f"- Dê exemplos específicos do domínio '{domain}' sempre que possível\n"
        f"- Nunca invente dados que o usuário não forneceu\n"
        f"- Se o usuário der meta-comentário (dúvida, correção, revisão), responda sem salvar como dado\n"
    )


def build_oracle_prompt(payload: dict) -> tuple[str, str]:
    """
    Retorna (system_prompt, user_prompt) baseado no evento recebido.
    event: stage_intro | component_ack | w2h_question | w2h_analysis | meta_input
    """
    event = payload.get("event", "meta_input")
    stage = payload.get("stage", "")
    user_profile = payload.get("user_profile", "advanced")
    domain = payload.get("domain", "Processo")
    user_message = payload.get("user_message", "")
    context = payload.get("context") or {}

    system = _build_system_prompt(domain, user_profile)
    stage_label = _STAGE_LABELS.get(stage, stage)

    if event == "stage_intro":
        comp_type = context.get("component_type", "")
        type_label = _SIPOC_TYPE_LABELS.get(comp_type, comp_type)
        user_prompt = (
            f"Apresente a etapa '{stage_label}' do SIPOC de forma didática.\n"
            f"- Explique o que são {type_label}s no contexto de '{domain}' (1-2 frases)\n"
            f"- Dê 2-3 exemplos típicos para esse domínio\n"
            f"- Termine pedindo o primeiro item\n"
            f"Seja natural e conversacional."
        )

    elif event == "component_ack":
        comp_type = context.get("component_type", "supplier")
        value = context.get("value", user_message)
        type_label = _SIPOC_TYPE_LABELS.get(comp_type, comp_type)
        user_prompt = (
            f"O usuário adicionou '{value}' como {type_label} no SIPOC de '{domain}'.\n"
            f"- Confirme o registro em 1 frase\n"
            f"- Se relevante, adicione 1 insight sobre esse {type_label} para '{domain}'\n"
            f"- Instrua: mais itens ou 'próximo' para avançar\n"
            f"Máximo 3 linhas."
        )

    elif event == "w2h_question":
        field = context.get("w2h_field", "what")
        activity = context.get("activity_name", "atividade")
        field_label = _W2H_LABELS.get(field, field)
        previous = context.get("previous_answers") or {}
        answered = {_W2H_LABELS.get(k, k): v for k, v in previous.items() if v}

        context_block = ""
        if answered:
            rows = "\n".join(f"- {k}: {v}" for k, v in answered.items())
            context_block = (
                f"\nRespostas já coletadas para esta atividade:\n{rows}\n"
                f"O exemplo deve ser COERENTE com as respostas acima — "
                f"se 'Onde' = 'pasta física', NÃO cite sistemas no exemplo; "
                f"se 'Onde' = 'sistema X', use esse sistema. "
                f"O mesmo vale para canal de entrada, executor, frequência etc.\n"
            )

        user_prompt = (
            f"Faça a pergunta '{field_label}' do 5W2H para a atividade '{activity}' no domínio '{domain}'.\n"
            f"- Formule a pergunta de forma clara e específica\n"
            f"- Dê 1 exemplo prático do setor coerente com o contexto\n"
            f"{context_block}"
            f"Máximo 3 linhas."
        )

    elif event == "w2h_analysis":
        activity = context.get("activity_name", "atividade")
        w2h_data = context.get("w2h_data", {})
        rows = "\n".join(f"- {k}: {v}" for k, v in w2h_data.items() if v)
        user_prompt = (
            f"Analise os dados 5W2H da atividade '{activity}' no domínio '{domain}' "
            f"usando a Vectra Rubric v1 (Repetitividade +40, Volume +15, Criticidade $+15, "
            f"Ambiguidade -20, Aprovação Física -10).\n\n"
            f"Dados:\n{rows}\n\n"
            f"Retorne em markdown:\n"
            f"1. **Score de Automação: X/100** — justificativa em 1 linha\n"
            f"2. **Padrão Lógico:** SIMPLE|SPLIT|LOOP-FOR-EACH|WAIT-EVENT|SUBFLOW|MANUAL\n"
            f"3. **Sugestão:** como automatizar (1 frase)\n"
            f"Máximo 5 linhas."
        )

    elif event == "meta_input":
        user_prompt = (
            f"O usuário enviou durante o mapeamento SIPOC de '{domain}' (estágio: {stage_label}):\n\n"
            f"'{user_message}'\n\n"
            f"Interprete a intenção real (dúvida, revisão, correção, ou outra meta-comunicação) "
            f"e responda de forma útil. Não trate como dado SIPOC. Máximo 3 linhas."
        )

    else:
        user_prompt = (
            f"Contexto: SIPOC de '{domain}', estágio '{stage_label}'.\n"
            f"Mensagem: '{user_message}'\nResponda brevemente (máximo 3 linhas)."
        )

    return system, user_prompt


async def stream_oracle_chat(payload: dict) -> AsyncIterator[str]:
    """Constrói prompt Oracle e gera resposta via Gemini em streaming."""
    system, user_prompt = build_oracle_prompt(payload)
    logger.info(
        "oracle.stream_chat event=%s stage=%s domain=%s",
        payload.get("event"), payload.get("stage"), payload.get("domain"),
    )
    async for chunk in stream_generate(DEFAULT_MODEL, user_prompt, system_instruction=system):
        yield chunk


# ─────────────────────────────────────────────────────────────────────────────
# Fase 2 — Daemon Oracle: execute_specialty + handlers
# ─────────────────────────────────────────────────────────────────────────────

# F2 do GSD ampliado (2026-05-17): `ORACLE_DEFAULT_MODEL` hardcoded aposentado.
# Modelo agora vem 100% do catalog via cadeia: input_json > agent_specialty_configs.values >
# agent_shared_config.values > agent_specialties.config_schema.defaults.
# Histórico antigo (`_GEMINI_FLASH_COST_PER_TOKEN` $0.075/$0.30 per 1M desalinhado
# do `model="gemini-2.5-pro"` real → cost ~16x sub-estimado) resolvido por
# catalog-driven via `src/services/llm_cost.py:calc_llm_cost`.

_VECTRA_CONTEXT = (
    "Contexto da empresa: Vectra Cargo é uma transportadora brasileira de modal EXCLUSIVAMENTE RODOVIÁRIO. "
    "Não opera aéreo, marítimo, ferroviário ou intermodal. "
    "Atua com frota própria e terceirizada no transporte de cargas em território nacional. "
    "Ao analisar processos da Vectra, considere apenas o modal rodoviário e desconsidere "
    "referências a outros modais."
)


def _resolve_model(input_data: Dict[str, Any]) -> str:
    """Resolve model_id via cadeia catalog (Regra de Ouro #2 NO HARDCODE).

    Idêntico ao helper de athena.py. Cadeia:
        1. input_data["model_id"]
        2. input_data["_resolved_config"]["model_id"] (agent_specialty_configs.values)
        3. input_data["_resolved_shared"]["model_id"] (agent_shared_config.values)
        4. input_data["_resolved_specialty"].defaults["model_id"] (config_schema default)

    Raise ValueError se nada resolver.
    """
    from src.services.specialty_resolver import resolve_value

    specialty = input_data.get("_resolved_specialty")
    specialty_defaults = specialty.defaults if specialty else {}

    model = resolve_value(
        "model_id",
        payload=input_data,
        config_values=input_data.get("_resolved_config") or {},
        shared_values=input_data.get("_resolved_shared") or {},
        specialty_defaults=specialty_defaults,
    )
    if not model:
        raise ValueError(
            "Oracle: model_id não resolvido pela cadeia catalog. "
            "Configure 'model_id' em agent_specialty_configs.values "
            "(via UI /admin/agents/{id}/specialty-config) ou em "
            "agent_shared_config.values, ou defina default em "
            "agent_specialties.config_schema."
        )
    return str(model)


async def _handle_extract(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    ctx = input_data.get("_company_context") or _VECTRA_CONTEXT
    system = (
        f"{ctx}\n\n"
        "Você é um extrator de dados estruturados. "
        "Extraia os dados solicitados e retorne exclusivamente JSON válido, sem texto extra."
    )
    text, metadata = await generate(
        _resolve_model(input_data), prompt,
        system_instruction=system,
        response_mime_type="application/json",
    )
    try:
        structured = json.loads(text)
    except Exception:
        structured = {"raw": text}

    # CRM via oracle-extract + prospect_profile: desativado — persistência unificada em oracle-research
    # (evita duplicar linhas / contratos divergentes; ver persist_prospect_from_oracle_research).

    return {
        "report_markdown": f"```json\n{text}\n```",
        "structured_data": structured,
        "metadata": metadata,
    }


async def _handle_summarize(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    ctx = input_data.get("_company_context") or _VECTRA_CONTEXT
    system = (
        f"{ctx}\n\n"
        "Você é um especialista em síntese. "
        "Produza um sumário claro e objetivo em PT-BR usando markdown."
    )
    text, metadata = await generate(_resolve_model(input_data), prompt, system_instruction=system)
    return {"report_markdown": text, "structured_data": None, "metadata": metadata}


async def _handle_rag(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    docs = input_data.get("documents") or []
    context = "\n\n---\n\n".join(d.get("content", "") for d in docs if d.get("content"))
    full_prompt = f"Contexto:\n{context}\n\nPergunta:\n{prompt}" if context else prompt
    ctx = input_data.get("_company_context") or _VECTRA_CONTEXT
    system = (
        f"{ctx}\n\n"
        "Você é um assistente RAG. Responda com base no contexto fornecido. "
        "Se a resposta não estiver no contexto, diga explicitamente. Responda em PT-BR."
    )
    text, metadata = await generate(_resolve_model(input_data), full_prompt, system_instruction=system)
    return {"report_markdown": text, "structured_data": None, "metadata": metadata}


_INLINE_SIZE_LIMIT = 4 * 1024 * 1024  # 4 MB — Gemini inline bytes cap


def _vision_json_to_markdown(data: Any, depth: int = 0) -> str:
    """Convert oracle-vision JSON output into readable Markdown."""
    lines: list[str] = []

    if isinstance(data, dict):
        if "vagas" in data and isinstance(data["vagas"], list):
            header = data.get("titulo") or data.get("empresa") or data.get("perfil") or ""
            if header:
                lines.append(f"## {header}\n")
            for i, vaga in enumerate(data["vagas"], 1):
                if isinstance(vaga, dict):
                    title = vaga.get("titulo") or vaga.get("cargo") or vaga.get("title") or f"Vaga {i}"
                    lines.append(f"### Vaga {i}: {title}\n")
                    for k, v in vaga.items():
                        if k in ("titulo", "cargo", "title"):
                            continue
                        label = k.replace("_", " ").capitalize()
                        if isinstance(v, list):
                            lines.append(f"**{label}:**")
                            for item in v:
                                lines.append(f"- {item}")
                            lines.append("")
                        elif v is not None and v != "":
                            lines.append(f"* **{label}:** {v}")
                    lines.append("")
            for k, v in data.items():
                if k == "vagas" or not v:
                    continue
                lines.append(f"**{k.replace('_', ' ').capitalize()}:** {v}\n")
        else:
            h = "#" * min(depth + 2, 6)
            for k, v in data.items():
                label = k.replace("_", " ").capitalize()
                if isinstance(v, list):
                    lines.append(f"**{label}:**")
                    for item in v:
                        if isinstance(item, dict):
                            lines.append(_vision_json_to_markdown(item, depth + 1))
                        elif item is not None:
                            lines.append(f"- {item}")
                    lines.append("")
                elif isinstance(v, dict):
                    lines.append(f"{h} {label}\n")
                    lines.append(_vision_json_to_markdown(v, depth + 1))
                elif v is not None and v != "":
                    lines.append(f"* **{label}:** {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                lines.append(_vision_json_to_markdown(item, depth))
            elif item is not None:
                lines.append(f"- {item}")

    return "\n".join(lines)


async def _handle_vision(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    from google.genai import types as _gt
    import mimetypes as _mt

    docs = input_data.get("documents") or []
    contents: list = []
    client = get_client()

    for doc in docs:
        if doc.get("data") and doc.get("mime_type"):
            contents.append(
                _gt.Part.from_bytes(
                    data=base64.b64decode(doc["data"]),
                    mime_type=doc["mime_type"],
                )
            )
        elif doc.get("path"):
            _path = doc["path"]
            _mime = doc.get("mime_type") or _mt.guess_type(_path)[0] or "image/png"
            _size = os.path.getsize(_path)
            if _size > _INLINE_SIZE_LIMIT:
                logger.info("vision: uploading %s (%d MB) via Files API", os.path.basename(_path), _size // (1024 * 1024))
                uploaded = await client.aio.files.upload(
                    file=_path,
                    config=_gt.UploadFileConfig(mimeType=_mime, displayName=os.path.basename(_path)),
                )
                contents.append(_gt.Part.from_uri(uri=uploaded.uri, mime_type=_mime))
            else:
                with open(_path, "rb") as _f:
                    contents.append(_gt.Part.from_bytes(data=_f.read(), mime_type=_mime))
        elif doc.get("uri"):
            contents.append(
                _gt.Part.from_uri(
                    uri=doc["uri"],
                    mime_type=doc.get("mime_type", "application/pdf"),
                )
            )
    contents.append(prompt)

    ctx = input_data.get("_company_context") or _VECTRA_CONTEXT
    t0 = time.monotonic()
    response = await client.aio.models.generate_content(
        model=_resolve_model(input_data),
        contents=contents,
        config=_gt.GenerateContentConfig(
            system_instruction=f"{ctx}\n\nAnalise os documentos e responda em PT-BR.",
            thinking_config=_gt.ThinkingConfig(thinking_budget=0),
        ),
    )
    metadata = extract_metadata(response, int((time.monotonic() - t0) * 1000))

    raw_text = response.text or ""
    structured_data = None
    report_markdown = raw_text

    # Detect JSON response (code block or bare JSON) and convert to Markdown
    _block = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text.strip())
    _candidate = _block.group(1).strip() if _block else (raw_text.strip() if raw_text.strip()[:1] in ("{", "[") else None)
    if _candidate:
        try:
            parsed = json.loads(_candidate)
            structured_data = parsed
            report_markdown = _vision_json_to_markdown(parsed)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "report_markdown": report_markdown,
        "structured_data": structured_data,
        "metadata": metadata,
    }


def _normalize_research_output_format(value: Any) -> str:
    s = (str(value or "markdown")).strip().lower()
    if s in ("markdown", "json", "both"):
        return s
    return "markdown"


async def _extract_company_profile(report_markdown: str, model: str) -> Optional[Dict[str, Any]]:
    """Compat: extrai perfil enxuto. Preferir _extract_prospect_bundle em fluxos novos.

    F2 GSD: param `model` obrigatório (catalog-driven).
    """
    bundle = await _extract_prospect_bundle(report_markdown, [], model=model)
    return bundle


async def _extract_prospect_bundle(
    report_markdown: str,
    submitted_urls: List[str],
    *,
    model: str,
) -> Optional[Dict[str, Any]]:
    """
    Extrai o máximo possível para `prospect_profiles` + fontes + e-mail (Seção 7).
    Um único JSON reduz custo e mantém consistência.
    """
    if not report_markdown or len(report_markdown) < 200:
        return None
    url_block = ""
    if submitted_urls:
        url_block = (
            "URLs enviadas pelo usuário (avalie cada uma: acessível no relatório? bloqueio/login? "
            "resuma em 1–2 frases o que foi possível inferir):\n"
            + "\n".join(f"- {u}" for u in submitted_urls[:20])
            + "\n\n"
        )
    try:
        extraction_prompt = (
            "Você recebe um relatório de pesquisa B2B em PT-BR. "
            "Retorne APENAS um JSON válido (sem markdown) com a estrutura:\n"
            "{\n"
            '  "nome_razao_social": string|null,\n'
            '  "cnpj": string|null,\n'
            '  "website": string|null,\n'
            '  "setor": string|null,\n'
            '  "cidade": string|null,\n'
            '  "estado": string|null (sigla UF),\n'
            '  "logradouro": string|null,\n'
            '  "cep": string|null,\n'
            '  "telefone": string|null,\n'
            '  "email_contato": string|null,\n'
            '  "decisores": array de {nome, cargo, linkedin, instagram, email, fonte},\n'
            '  "fontes_analisadas": array de {url, alcancada: boolean, resumo: string, bloqueio_motivo: string|null},\n'
            '  "outreach_email": { "assunto": string, "corpo_texto": string }\n'
            "}\n"
            "Regras:\n"
            "- Preencha o máximo possível a partir do relatório; use null quando não houver dado.\n"
            "- Para cada URL em fontes_analisadas, use também o bloco de URLs enviadas (se houver).\n"
            "- outreach_email: redija e-mail profissional em PT-BR com base na Seção 7 / síntese comercial "
            "do relatório (dor, decisor, gancho). assunto curto; corpo_texto com saudação, 2–4 parágrafos e CTA suave.\n"
            f"{url_block}"
            f"RELATÓRIO:\n{report_markdown[:12000]}"
        )
        text, _meta = await generate(
            model=model,
            prompt=extraction_prompt,
            response_mime_type="application/json",
        )
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("_extract_prospect_bundle failed: %s", e)
        return None


_RESEARCH_SECTIONS_MAX_CHARS = 120_000


async def _extract_research_sections(report_markdown: str, *, model: str) -> Optional[Dict[str, Any]]:
    """
    Segunda passagem: extrai do relatório um JSON rico (SIPOC, scores, mídias, artigos, abordagem).
    Usado quando input_json.output_format é json ou both.
    """
    if not report_markdown or len(report_markdown) < 200:
        return None
    body = report_markdown[:_RESEARCH_SECTIONS_MAX_CHARS]
    try:
        extraction_prompt = (
            "Você recebe um relatório de pesquisa comercial/B2B em PT-BR. "
            "Extraia a informação em JSON válido APENAS (sem markdown fora do JSON). "
            "Estrutura obrigatória (use null ou listas vazias quando não houver dado):\n"
            "- perfil_empresa: objeto com resumo, segmento, porte_aproximado, localizacao, pontos_chave (array de strings)\n"
            "- decisores: array de {nome, cargo, linkedin, email, fonte, relevancia}\n"
            "- sipoc_processos: array de {nome_processo, fornecedores, entradas, atividades, saidas, clientes, observacoes}\n"
            "- oportunidades_automacao: array de {contexto, score_0_100, justificativa, padrao_logico}\n"
            "- linkedin_ads: array de {titulo, texto_ou_resumo, fonte}\n"
            "- artigos_e_temas: array de {titulo, tema, resumo, fonte}\n"
            "- sintese_abordagem_comercial: string com tom consultivo (2–6 parágrafos curtos ou lista numerada)\n"
            "- fontes_consultadas: array de strings (URLs ou títulos citados no relatório)\n\n"
            f"RELATÓRIO:\n{body}"
        )
        text, _meta = await generate(
            model=model,
            prompt=extraction_prompt,
            response_mime_type="application/json",
        )
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("_extract_research_sections failed: %s", e)
        return None


async def enrich_research_structured_output(
    report_markdown: str,
    structured_profile: Optional[Dict[str, Any]],
    input_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Quando output_format é json ou both, acrescenta research_sections ao structured_data
    (mantém campos CRM do perfil para prospect_profiles e UI legada).
    """
    fmt = _normalize_research_output_format(input_data.get("output_format"))
    if fmt == "markdown":
        return structured_profile
    if not report_markdown or len(report_markdown) < 200:
        return structured_profile
    sections = await _extract_research_sections(report_markdown, model=_resolve_model(input_data))
    if not sections:
        return structured_profile
    merged: Dict[str, Any] = {}
    if isinstance(structured_profile, dict):
        merged.update(structured_profile)
    merged["research_sections"] = sections
    return merged


async def _save_prospect_profile(
    supabase: Any,
    company_id: str,
    task_id: Optional[str],
    raw_research: str,
    profile: Dict[str, Any],
    *,
    storage_refs: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Upsert em prospect_profiles por (company_id, source_task_id) quando task_id existe.
    Preenche colunas do schema + artifacts (fontes, e-mail, refs Storage).
    """
    try:
        endereco: Optional[Dict] = None
        if (
            profile.get("cidade")
            or profile.get("estado")
            or profile.get("logradouro")
            or profile.get("cep")
        ):
            endereco = {
                k: profile.get(k)
                for k in ("logradouro", "cidade", "estado", "cep")
                if profile.get(k)
            }

        prof = {k: v for k, v in profile.items() if k != "research_sections"}
        fontes = prof.pop("fontes_analisadas", None)
        outreach = prof.pop("outreach_email", None)

        artifacts: Dict[str, Any] = {}
        if fontes is not None:
            artifacts["fontes_analisadas"] = fontes
        if outreach is not None:
            artifacts["outreach_email"] = outreach
        if storage_refs:
            artifacts["storage"] = storage_refs

        row: Dict[str, Any] = {
            "company_id": company_id,
            "nome_razao_social": prof.get("nome_razao_social"),
            "cnpj": prof.get("cnpj"),
            "website": prof.get("website"),
            "setor": prof.get("setor"),
            "endereco": endereco,
            "telefone": prof.get("telefone"),
            "email_contato": prof.get("email_contato"),
            "decisores": prof.get("decisores") if prof.get("decisores") is not None else [],
            "source_task_id": task_id,
            "raw_research": raw_research[:50000],
            "enriched_at": datetime.now(timezone.utc).isoformat(),
        }
        if artifacts:
            row["artifacts"] = artifacts

        row = {k: v for k, v in row.items() if v is not None}

        if task_id:
            existing = (
                supabase.table("prospect_profiles")
                .select("id")
                .eq("company_id", company_id)
                .eq("source_task_id", task_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                rid = existing.data[0]["id"]
                supabase.table("prospect_profiles").update(row).eq("id", rid).execute()
                logger.info("prospect_profile updated company_id=%s task=%s id=%s", company_id, task_id, rid)
            else:
                supabase.table("prospect_profiles").insert(row).execute()
                logger.info("prospect_profile inserted company_id=%s task=%s", company_id, task_id)
        else:
            supabase.table("prospect_profiles").insert(row).execute()
            logger.info("prospect_profile inserted (no task id) company_id=%s", company_id)
    except Exception as e:
        logger.warning("_save_prospect_profile failed: %s", e)


async def persist_prospect_from_oracle_research(
    supabase: Any,
    company_id: str,
    task_id: Optional[str],
    report_markdown: str,
    input_data: Dict[str, Any],
    citations: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Playwright (opcional) + extração JSON + merge citações + upsert prospect_profiles.
    Retorna structured_data para output_json da task.
    """
    from src.services.prospect_research_capture import (
        capture_social_pages_to_storage,
        collect_document_urls,
    )

    if not company_id:
        return {}

    urls = collect_document_urls(input_data.get("documents"))
    storage_refs: List[Dict[str, Any]] = []
    if supabase and task_id and len((report_markdown or "").strip()) >= 20:
        storage_refs = await capture_social_pages_to_storage(
            supabase, company_id=company_id, task_id=task_id, urls=urls
        )

    bundle = await _extract_prospect_bundle(report_markdown, urls, model=_resolve_model(input_data)) or {}
    structured = await enrich_research_structured_output(
        report_markdown, bundle, input_data
    )
    if not isinstance(structured, dict):
        structured = {}

    fa = list(structured.get("fontes_analisadas") or [])
    seen = {str(x.get("url", "")) for x in fa if isinstance(x, dict)}
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        uri = str(c.get("uri") or "")
        if uri and uri not in seen:
            fa.append(
                {
                    "url": uri,
                    "alcancada": True,
                    "resumo": str(c.get("title") or "")[:500],
                    "bloqueio_motivo": None,
                }
            )
            seen.add(uri)
    structured["fontes_analisadas"] = fa

    if supabase and len((report_markdown or "").strip()) >= 20:
        await _save_prospect_profile(
            supabase,
            company_id,
            task_id,
            report_markdown,
            structured,
            storage_refs=storage_refs or None,
        )
    return structured


async def _handle_research_sync(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synchronous fallback for oracle-research using gemini-2.5-pro + google_search + url_context.
    Used when the Deep Research Interactions API is unavailable.
    """
    from google.genai import types as _gt

    client = get_client()
    ctx = input_data.get("_company_context") or _VECTRA_CONTEXT
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id")
    company_id = input_data.get("_company_id")

    # Include URLs in prompt so url_context tool can fetch them (aceita url ou uri)
    docs = input_data.get("documents") or []
    url_lines: list[str] = []
    for d in docs:
        if isinstance(d, dict):
            u = d.get("uri") or d.get("url")
            if u:
                url_lines.append(str(u))
    enriched_prompt = prompt
    if url_lines:
        enriched_prompt = (
            "Fontes primárias a consultar (use url_context):\n"
            + "\n".join(f"- {u}" for u in url_lines)
            + f"\n\n{prompt}"
        )

    # Pre-capture LinkedIn/Instagram via authenticated Playwright session and inject
    # the extracted text as grounded context so Gemini sees real page content
    # even when url_context is blocked by login walls.
    try:
        from src.services.prospect_research_capture import (
            capture_social_pages_for_context,
            collect_document_urls,
        )
        captured = await capture_social_pages_for_context(
            urls=collect_document_urls(docs)
        )
        pages_with_content = [c for c in captured if c.get("content")]
        if pages_with_content:
            social_block = "\n\n".join(
                f"=== Conteúdo autenticado de {c['url']} ===\n{c['content']}"
                for c in pages_with_content
            )
            enriched_prompt = (
                "CONTEÚDO CAPTURADO VIA SESSÃO AUTENTICADA (LinkedIn/Instagram):\n"
                "Use estas informações como fonte primária — são dados reais das páginas.\n\n"
                + social_block
                + "\n\n---\n\n"
                + enriched_prompt
            )
            logger.info(
                "_handle_research_sync: %d páginas sociais injetadas no prompt (%d chars)",
                len(pages_with_content),
                sum(len(c["content"]) for c in pages_with_content),
            )
    except Exception as _cap_err:
        logger.warning("_handle_research_sync: playwright pre-capture falhou: %s", _cap_err)

    # F2 GSD: model vem do catalog (specialty_config.model_id) — antes era literal "gemini-2.5-pro".
    resolved_model = _resolve_model(input_data)
    t0 = time.monotonic()
    response = await client.aio.models.generate_content(
        model=resolved_model,
        contents=[enriched_prompt],
        config=_gt.GenerateContentConfig(
            system_instruction=(
                f"{ctx}\n\n"
                "Você é um pesquisador especialista em inteligência empresarial para o setor de transporte e logística no Brasil. "
                "Produza um relatório completo e estruturado em PT-BR com todas as seções solicitadas. "
                "Use google_search e url_context para buscar dados atualizados. "
                "Se uma URL retornar erro (ex: login obrigatório), use google_search para encontrar as informações equivalentes."
            ),
            tools=[
                _gt.Tool(google_search=_gt.GoogleSearch()),
                _gt.Tool(url_context=_gt.UrlContext()),
            ],
            thinking_config=_gt.ThinkingConfig(thinking_budget=4096),
        ),
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    metadata = extract_metadata(response, duration_ms)
    metadata["model_used"] = resolved_model  # F2: telemetria honesta (era literal antes)
    metadata["backend"] = "sync_fallback"
    metadata["research_output_format"] = _normalize_research_output_format(input_data.get("output_format"))
    report_text = response.text or ""

    # Extract citations from grounding metadata + contagem de searches
    # (search_count = nº de queries Google executadas, base do billing
    # Search Grounding $0.035/command Gemini 2.5).
    citations: list = []
    search_count = 0
    for candidate in (response.candidates or []):
        gm = getattr(candidate, "grounding_metadata", None)
        if gm:
            for chunk in (getattr(gm, "grounding_chunks", []) or []):
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    citations.append({
                        "title": getattr(web, "title", ""),
                        "uri": web.uri,
                    })
            # web_search_queries[] é a métrica de billing real
            search_count += len(getattr(gm, "web_search_queries", []) or [])
    metadata["search_count"] = search_count

    structured_data = await persist_prospect_from_oracle_research(
        supabase,
        company_id,
        task_id,
        report_text,
        input_data,
        citations,
    )

    return {
        "report_markdown": report_text,
        "structured_data": structured_data,
        "citations": citations,
        "metadata": metadata,
    }


async def _handle_research(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    # Try Deep Research (background Interactions API) first
    try:
        from src.services.gemini_interactions import start_research, DEEP_RESEARCH_AGENT
        interaction_id = await start_research(prompt, documents=input_data.get("documents"))
        return {
            "report_markdown": None,
            "structured_data": None,
            "metadata": {
                "interaction_id": interaction_id,
                "status": "in_progress",
                "model_used": DEEP_RESEARCH_AGENT,
                "tokens": {},
                "duration_ms": 0,
                "research_output_format": _normalize_research_output_format(input_data.get("output_format")),
            },
            "citations": None,
            "_status_override": "in_progress",
        }
    except Exception as e:
        logger.warning(
            "deep_research unavailable (%s: %s) — falling back to gemini-2.5-pro + google_search",
            type(e).__name__, e,
        )

    # Fallback: synchronous research with Google Search + URL Context tools
    return await _handle_research_sync(prompt, input_data)


_SPECIALTY_DISPATCH = {
    "oracle-extract": _handle_extract,
    "oracle-summarize": _handle_summarize,
    "oracle-rag": _handle_rag,
    "oracle-vision": _handle_vision,
    "oracle-research": _handle_research,
}


async def _get_company_context(supabase: Any, company_id: str) -> str:
    """Busca context_json da empresa. Fallback para _VECTRA_CONTEXT se não houver."""
    if not supabase or not company_id:
        return _VECTRA_CONTEXT
    try:
        res = (
            supabase.table("companies")
            .select("name,context_json")
            .eq("company_id", company_id)
            .maybe_single()
            .execute()
        )
        if res.data and res.data.get("context_json"):
            ctx = res.data["context_json"]
            name = res.data.get("name", "empresa")
            summary = (ctx.get("research_summary") or "")[:1200]
            if summary:
                return f"Empresa: {name}\nPerfil operacional (pesquisa automática):\n{summary}"
    except Exception as e:
        logger.warning("_get_company_context failed: %s", e)
    return _VECTRA_CONTEXT


async def execute_specialty(task: Dict[str, Any], supabase: Any) -> Dict[str, Any]:
    """
    Entry point para o daemon. Despacha para o handler correto e retorna
    {output_json, cost_usd, status_override} para o daemon processar.
    """
    op = task.get("operation_type", "")
    input_data: Dict[str, Any] = task.get("input_json") or {}
    prompt = (
        input_data.get("prompt")
        or task.get("description")
        or task.get("title")
        or ""
    ).strip()

    logger.info("oracle.execute_specialty op=%s task=%s", op, task.get("id"))

    if not prompt:
        return {
            "output_json": {
                "error_detail": {"code": "missing_fields", "message": "input_json.prompt, description ou title é obrigatório"}
            },
            "cost_usd": 0.0,
            "status_override": None,
        }

    company_context = await _get_company_context(supabase, task.get("company_id", ""))
    # F2 GSD: PROPAGA _resolved_* (config/shared/specialty) populados pelo daemon.
    # Antes, esses campos eram descartados aqui e os handlers usavam
    # ORACLE_DEFAULT_MODEL hardcoded — agent_specialty_configs.values era placebo.
    enriched_input = {
        **input_data,
        "_company_context": company_context,
        "_supabase": supabase,
        "_company_id": task.get("company_id"),
        "_task_id": task.get("id"),
        "_resolved_config": task.get("_resolved_config") or {},
        "_resolved_shared": task.get("_resolved_shared") or {},
        "_resolved_specialty": task.get("_resolved_specialty"),
    }

    handler = _SPECIALTY_DISPATCH.get(op, _handle_summarize)
    try:
        result = await handler(prompt, enriched_input)
    except Exception as exc:
        logger.error("oracle.execute_specialty handler error op=%s: %s", op, exc, exc_info=True)
        return {
            "output_json": {
                "error_detail": {"code": "execution_error", "message": str(exc)}
            },
            "cost_usd": 0.0,
            "status_override": None,
        }

    # Cost-aware multi-modelo (fix smoke #189 + Opção C 2026-05-17):
    # - `model_used` da metadata = qual modelo o handler realmente rodou
    #   (Flash, Pro, ou Deep Research). Cada um tem preço próprio em llm_models.
    # - `search_count` = nº de Google Search queries que o grounding executou.
    #   Cobrado separadamente ($0.035/command Gemini 2.5). Capturado em
    #   _handle_research_sync via web_search_queries da grounding_metadata.
    metadata_out = result.get("metadata") or {}
    tokens = metadata_out.get("tokens", {})
    # F2 GSD: fallback chain `metadata.model_used > _resolve_model(input_data)` —
    # handler já resolveu via catalog em _handle_research_sync, mas se ele falhar
    # antes de setar metadata.model_used, ainda há resolução pela mesma cadeia.
    try:
        model_used = metadata_out.get("model_used") or _resolve_model(input_data)
    except ValueError:
        # Nada resolvido (sem config). Cost vira 0 fail-safe (em vez de raise pós-execução).
        model_used = ""
    n_requests = int(metadata_out.get("search_count") or 0)
    cost_usd = calc_llm_cost(supabase, model_used, tokens, n_requests=n_requests) if model_used else 0.0
    require_review = bool(input_data.get("require_human_review"))

    logger.info(
        "oracle.execute_specialty done op=%s tokens=%s cost=%.6f review=%s",
        op, tokens.get("total", 0), cost_usd, require_review,
    )

    out_meta: Dict[str, Any] = dict(result.get("metadata") or {})
    if op == "oracle-research":
        out_meta["research_output_format"] = _normalize_research_output_format(input_data.get("output_format"))

    return {
        "output_json": {
            "report_markdown": result.get("report_markdown"),
            "structured_data": result.get("structured_data"),
            "metadata": out_meta,
            "citations": result.get("citations"),
        },
        "cost_usd": cost_usd,
        "status_override": result.get("_status_override") or ("review" if require_review else None),
    }
