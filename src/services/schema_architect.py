"""Schema Architect — geração/revisão de JSON de config para especialidades NAVI.

Portado de docs/vectra-cargo-navi-schema-architect (Vertex AI Studio / Gemini).
Usa GEMINI_API_KEY via src.services.gemini_client (Regra de Ouro #1: não hardcode).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.services.gemini_client import DEFAULT_MODEL, generate

logger = logging.getLogger("SchemaArchitect")

SCHEMA_ARCHITECT_MODEL = DEFAULT_MODEL

SYSTEM_INSTRUCTION = """
Persona: Você é o Arquiteto Senior de Sistemas da Vectra Cargo. Sua especialidade é desenhar estruturas de dados JSON para microserviços e agentes de IA (NAVI).

Tarefa:
1. Se o usuário fornecer apenas um nome de especialidade (ex: "Responsável pelo Disparo de E-mails"), analise as responsabilidades implícitas e gere um Schema JSON de Configuração completo e robusto.
2. Se o usuário fornecer um Schema existente junto com a especialidade, revise-o criticamente em busca de:
   - Campos faltando essenciais para a operação.
   - Tipos de dados errados.
   - Falta de aderência aos padrões da Vectra Cargo.

Padrões da Vectra Cargo (MUITO IMPORTANTE):
- As chaves do JSON devem estar sempre em português.
- Use sempre o padrão snake_case para as chaves (ex: politica_envio, tentativas_maximas).
- Estruture em objetos aninhados lógicos (ex: agrupar configs de provedor, segurança, etc).

Regras Específicas para "Disparo de E-mails" (se aplicável):
- O schema deve sempre incluir objetos para: provedor, template, politica_envio, seguranca e rastreamento.

Formato de Saída:
- Comece com uma breve explicação ou análise (seja cordial e profissional, como um Arquiteto Senior).
- Forneça o JSON resultante OBRIGATORIAMENTE dentro de um bloco de código markdown formatado assim:
```json
{ ... }
```
- Se estiver revisando, aponte claramente o que foi alterado ou sugerido antes de mostrar o JSON final.
""".strip()

CATALOG_SYSTEM_INSTRUCTION = """
Persona: Você é o Arquiteto Senior de Sistemas da Vectra Cargo. Você projeta arrays JSON de
definição de campos (field definitions) para catálogos admin da plataforma VectraClip/NAVI.

Tarefa:
1. Se não houver schema existente: gere um array JSON completo de definições de campo para o item do catálogo.
2. Se houver schema existente: revise criticamente (campos faltando, tipos errados, ordem, required).

Regras Vectra Cargo para catálogos admin:
- A saída DEVE ser um array JSON (lista de objetos campo), não um objeto de valores de runtime.
- Use camelCase nas chaves dos objetos (fieldKey, fieldLabel, key, label, etc.) conforme o catálogo indicado.
- Labels e descrições em português brasileiro.
- Tipos de campo válidos: text, textarea, number, boolean, secret, select, multiselect, url, file_upload.
- Inclua sortOrder quando o catálogo usar fieldKey/fieldLabel (perfis adapter, MCP).

Formato de Saída:
- Breve análise em português.
- O array JSON final OBRIGATORIAMENTE em bloco markdown:
```json
[ ... ]
```
""".strip()


def _build_catalog_prompt(
    name: str,
    catalog_label: str,
    shape_hint: str,
    existing: str,
    description: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    ctx = [f'Catálogo: "{catalog_label}".', f'Item: "{name}".', f"Formato esperado: {shape_hint}"]
    if description:
        ctx.append(f"Descrição: {description}")
    if extra:
        ctx.append(f"Metadados: {extra}")
    header = "\n".join(ctx)
    if existing:
        return (
            f"{header}\n\n"
            "Revise o schema de campos abaixo e devolva o array JSON corrigido:\n\n"
            f"```json\n{existing}\n```"
        )
    return f"{header}\n\nGere o array JSON de definição de campos para este item do catálogo."


async def generate_or_review_schema(
    specialty: str,
    existing_schema: Optional[str] = None,
    *,
    catalog_context: Optional[Dict[str, Any]] = None,
    model: str = SCHEMA_ARCHITECT_MODEL,
) -> tuple[str, dict]:
    """
    Gera ou revisa schema JSON de configuração para uma especialidade.

    Returns:
        (texto_markdown, metadata_gemini)
    """
    name = (specialty or "").strip()
    if not name:
        raise ValueError("specialty_required")

    existing = (existing_schema or "").strip()
    if catalog_context:
        prompt = _build_catalog_prompt(
            name=catalog_context.get("name") or name,
            catalog_label=str(catalog_context.get("catalogLabel") or catalog_context.get("catalog_type") or ""),
            shape_hint=str(catalog_context.get("shapeHint") or ""),
            existing=existing,
            description=str(catalog_context.get("description") or ""),
            extra=catalog_context.get("extra") if isinstance(catalog_context.get("extra"), dict) else None,
        )
        system = CATALOG_SYSTEM_INSTRUCTION
    elif existing:
        prompt = (
            f'Por favor, revise o seguinte schema JSON para a especialidade "{name}". '
            "Aplique os padrões da Vectra Cargo e sugira melhorias:\n\n"
            f"```json\n{existing}\n```"
        )
        system = SYSTEM_INSTRUCTION
    else:
        prompt = (
            f'Gere um schema JSON de configuração completo e padronizado para a especialidade: "{name}".'
        )
        system = SYSTEM_INSTRUCTION

    text, meta = await generate(
        model,
        prompt,
        system_instruction=system,
    )
    if not (text or "").strip():
        text = "Nenhuma resposta gerada pelo modelo."
    logger.info(
        "schema_architect specialty=%r review=%s model=%s",
        name,
        bool(existing),
        model,
    )
    return text, meta
