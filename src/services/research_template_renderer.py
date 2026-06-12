"""
Research Template Renderer
===========================
Renderiza templates de pesquisa em input_json para tasks de research.

Stub inicial — implementação completa pendente de PR dedicado.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_research_input(
    prospect: Dict[str, Any],
    template: Dict[str, Any],
    *,
    urls_override: Optional[List[str]] = None,
    require_human_review_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Constrói input_json para task de research baseado no template.

    Args:
        prospect: Dados do prospect (da tabela prospects).
        template: Template de pesquisa (da tabela research_templates).
        urls_override: URLs opcionais para pesquisar (override do template).
        require_human_review_override: Override para require_human_review.

    Returns:
        Dict com operation_type, input_data e metadados para task.
    """
    template_config = template.get("config_json") or {}
    research_type = template_config.get("research_type", "general")
    focus_areas = template_config.get("focus_areas", [])
    output_format = template_config.get("output_format", "structured")

    input_data: Dict[str, Any] = {
        "prospect_id": prospect.get("id"),
        "prospect_name": prospect.get("name") or prospect.get("company_name"),
        "prospect_domain": prospect.get("domain") or prospect.get("website"),
        "prospect_industry": prospect.get("industry") or prospect.get("segment"),
        "research_type": research_type,
        "focus_areas": focus_areas,
        "output_format": output_format,
    }

    if urls_override:
        input_data["urls"] = urls_override

    if require_human_review_override is not None:
        input_data["require_human_review"] = require_human_review_override

    return {
        "operation_type": "oracle-research",
        "input_data": input_data,
    }
