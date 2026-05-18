"""W13 MVP — Calculadora de cubagem e capacidade veicular.

Resolve órfão P0 confirmado pelo hardcode-orphan-auditor (2026-05-18):
`src/m3_tools.py:11,23` importa daqui há meses mas `src/services/freight/`
NÃO EXISTIA. Todo dispatch CMA dos tools `calculate_cbm` e
`infer_vehicle_capacity` falhava silenciosamente com ImportError.

Foco MVP (auditor H3 endereçado via migration 20260518230000):
- cubagem real (volume × densidade configurável por company)
- peso taxado = max(real, cubagem)
- capacidade veicular via lookup hardcoded MÍNIMO (vehicle_types_catalog
  é dívida — VEC futura quando houver UI pra cadastrar frota)

NÃO É ESCOPO desta versão (vai pra PRs futuros W13.x):
- Cálculo de tarifa (depende de price_tables ANTT/NTC — ver auditor relatório)
- Lookup de pedágio real (depende de coords origem/destino)
- Imposto / gross-up (depende de regime tributário por company)
- Múltiplos modais (aéreo, marítimo) — só rodoviário no MVP
"""

from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("freight.calculator")


# ─────────────────────────────────────────────────────────────────────────────
# Cubagem
# ─────────────────────────────────────────────────────────────────────────────

class CubagePackage(BaseModel):
    """Volume + peso por tipo de embalagem. Aceita quantidade pra evitar
    repetir a mesma linha N vezes."""
    quantity: int = Field(ge=1, description="Quantidade de pacotes idênticos")
    length_m: float = Field(gt=0, description="Comprimento em metros")
    width_m: float = Field(gt=0, description="Largura em metros")
    height_m: float = Field(gt=0, description="Altura em metros")
    weight_kg: float = Field(ge=0, description="Peso unitário (kg) — total = quantity × weight_kg")

    @field_validator("length_m", "width_m", "height_m")
    @classmethod
    def _reject_unrealistic_dimensions(cls, v: float) -> float:
        # Defensive — caller errou unidade (passou cm em vez de m)
        if v > 20:
            raise ValueError(f"dimensão {v}m parece estar em cm — passe em METROS")
        return v


class CubageRequest(BaseModel):
    """Payload pra calculate_freight_cubage. Se cubage_density_kg_m3 NULL,
    lê da company (requer company_id). Senão usa override."""
    packages: List[CubagePackage] = Field(min_length=1)
    cubage_density_kg_m3: Optional[int] = Field(
        default=None, gt=0, le=2000,
        description="Override de densidade. NULL = lê company.cubage_density_kg_m3 (default 300).",
    )
    company_id: Optional[str] = Field(
        default=None,
        description="UUID company pra resolver densidade quando override é None.",
    )


class CubageResult(BaseModel):
    total_volume_m3: float
    total_actual_weight_kg: float
    total_taxable_weight_kg: float
    cubage_density_used_kg_m3: int
    success: bool = True


def _resolve_density(req: CubageRequest) -> int:
    """Resolve densidade na ordem: req.cubage_density_kg_m3 → company → default 300.

    Auditor H3: nunca hardcodar 300 inline — sempre passar pela cadeia.
    """
    if req.cubage_density_kg_m3 is not None:
        return req.cubage_density_kg_m3

    if req.company_id:
        try:
            from src.api import supabase
            if supabase:
                res = (
                    supabase.table("companies")
                    .select("cubage_density_kg_m3")
                    .eq("company_id", req.company_id)
                    .limit(1)
                    .execute()
                )
                if res.data:
                    val = res.data[0].get("cubage_density_kg_m3")
                    if val:
                        return int(val)
        except Exception as e:
            logger.warning(
                "_resolve_density: lookup company=%s falhou (%s) — fallback 300",
                req.company_id, e,
            )

    return 300  # NTC&L ABNT rodoviário pesado


def calculate_freight_cubage(req: CubageRequest) -> CubageResult:
    """Calcula peso taxado por densidade. Fórmula:
        volume_pacote = L × W × H
        volume_total = Σ (quantidade × volume_pacote)
        peso_cubado = volume_total × densidade
        peso_taxado = max(peso_real_total, peso_cubado)
    """
    density = _resolve_density(req)

    total_volume = 0.0
    total_weight = 0.0
    for pkg in req.packages:
        vol = pkg.length_m * pkg.width_m * pkg.height_m
        total_volume += pkg.quantity * vol
        total_weight += pkg.quantity * pkg.weight_kg

    cubic_weight = total_volume * density
    taxable_weight = max(total_weight, cubic_weight)

    return CubageResult(
        total_volume_m3=round(total_volume, 4),
        total_actual_weight_kg=round(total_weight, 2),
        total_taxable_weight_kg=round(taxable_weight, 2),
        cubage_density_used_kg_m3=density,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Capacidade veicular (MVP — lookup mínimo, dívida vehicle_types_catalog)
# ─────────────────────────────────────────────────────────────────────────────

# DÍVIDA: hardcode aprovado P2 pelo hardcode-auditor (2026-05-18) APENAS
# como bridge MVP. Quando UI /admin/fleet existir, migrar pra tabela
# vectraclip.vehicle_types (slug PK, max_payload_kg, max_volume_m3, axes_count).
# VEC futura. Por ora 6 tipos cobrem 95% dos casos rodoviários PT-BR.
_VEHICLE_TYPES_MVP = {
    "vuc":              {"max_payload_kg": 1500,  "max_volume_m3": 8,   "axes_count": 2, "description": "VUC (Veículo Urbano de Carga)"},
    "3_4":              {"max_payload_kg": 3500,  "max_volume_m3": 18,  "axes_count": 2, "description": "Caminhão 3/4 (Toco)"},
    "toco":             {"max_payload_kg": 6000,  "max_volume_m3": 30,  "axes_count": 2, "description": "Caminhão Toco"},
    "truck":            {"max_payload_kg": 14000, "max_volume_m3": 50,  "axes_count": 3, "description": "Truck (Trucado)"},
    "carreta_simples":  {"max_payload_kg": 25000, "max_volume_m3": 80,  "axes_count": 5, "description": "Carreta Simples"},
    "carreta_ls":       {"max_payload_kg": 30000, "max_volume_m3": 100, "axes_count": 6, "description": "Carreta LS / Bitrem"},
}


class VehicleCapacityRequest(BaseModel):
    vehicle_type_slug: str = Field(
        description=f"Slug do tipo de veículo. MVP aceita: {', '.join(_VEHICLE_TYPES_MVP.keys())}",
    )


class VehicleCapacityResult(BaseModel):
    vehicle_type: str
    description: str
    max_payload_kg: int
    max_volume_m3: int
    axes_count: int
    success: bool = True


def calculate_vehicle_capacity(req: VehicleCapacityRequest) -> VehicleCapacityResult:
    """Lookup MVP de capacidade veicular. Auditor H6 endereçado: raise
    explícito quando slug inválido (não silenciar com default)."""
    slug = req.vehicle_type_slug.strip().lower()
    if slug not in _VEHICLE_TYPES_MVP:
        valid = ", ".join(sorted(_VEHICLE_TYPES_MVP.keys()))
        raise ValueError(
            f"vehicle_type_slug={slug!r} desconhecido. MVP aceita: {valid}. "
            f"Cadastro de novos tipos depende de vectraclip.vehicle_types (VEC futura)."
        )

    data = _VEHICLE_TYPES_MVP[slug]
    return VehicleCapacityResult(
        vehicle_type=slug,
        description=data["description"],
        max_payload_kg=data["max_payload_kg"],
        max_volume_m3=data["max_volume_m3"],
        axes_count=data["axes_count"],
    )
