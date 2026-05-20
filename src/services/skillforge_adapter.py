"""Skillforge adapter — bridge to skills-ia-empresariales (PRD Skills Library v2 PR M).

Wraps the external SkillForge library (local-first Python skills) for VectraClaw
task dispatch. Does NOT vendor the full repo; optional install via requirements.txt.

Skill ID mapping (slug → upstream module):
  sf-lector-documental          → lector_inteligente_documental
  sf-radar-anomalias            → radar_anomalias
  sf-forjador-informes          → forjador_informes
  sf-memoria-contextual-cliente → memoria_contextual_cliente
  sf-pulso-riesgo               → pulso_riesgo
  sf-buscador-privado-aumentado → buscador_privado_aumentado
  sf-enrutador-inteligente      → enrutador_inteligente
  sf-voz-marca-inteligente      → voz_marca_inteligente
  sf-verificador-normativo      → verificador_normativo
  sf-puerta-aprobacion-humana   → puerta_aprobacion_humana

Operation types use prefix ``skillforge:`` (e.g. ``skillforge:sf-radar-anomalias``).
"""

from __future__ import annotations

import dataclasses
import logging
import os
from statistics import mean, pstdev
from typing import Any, Callable, Dict, Optional, Type

logger = logging.getLogger("SkillforgeAdapter")

OPERATION_PREFIX = "skillforge:"


@dataclasses.dataclass(frozen=True)
class SkillSpec:
    """Registry entry for one Skillforge skill."""

    skill_id: str
    display_name: str
    module_name: str
    solicitud_attr: str
    eval_attr: str
    domain: str = "knowledge"


SKILL_REGISTRY: Dict[str, SkillSpec] = {
    "sf-lector-documental": SkillSpec(
        "sf-lector-documental",
        "Lector Inteligente Documental",
        "lector_inteligente_documental",
        "SolicitudLecturaDocumental",
        "evaluar_lector_inteligente_documental",
        "knowledge",
    ),
    "sf-radar-anomalias": SkillSpec(
        "sf-radar-anomalias",
        "Radar de Anomalias",
        "radar_anomalias",
        "SolicitudRadarAnomalias",
        "evaluar_radar_anomalias",
        "knowledge",
    ),
    "sf-forjador-informes": SkillSpec(
        "sf-forjador-informes",
        "Forjador de Informes",
        "forjador_informes",
        "SolicitudForjadorInformes",
        "evaluar_forjador_informes",
        "intelligence",
    ),
    "sf-memoria-contextual-cliente": SkillSpec(
        "sf-memoria-contextual-cliente",
        "Memoria Contextual de Cliente",
        "memoria_contextual_cliente",
        "SolicitudMemoriaCliente",
        "evaluar_memoria_contextual_cliente",
        "crm",
    ),
    "sf-pulso-riesgo": SkillSpec(
        "sf-pulso-riesgo",
        "Pulso de Riesgo",
        "pulso_riesgo",
        "SolicitudPulsoRiesgo",
        "evaluar_pulso_riesgo",
        "intelligence",
    ),
    "sf-buscador-privado-aumentado": SkillSpec(
        "sf-buscador-privado-aumentado",
        "Buscador Privado Aumentado",
        "buscador_privado_aumentado",
        "SolicitudBusquedaPrivada",
        "evaluar_buscador_privado_aumentado",
        "knowledge",
    ),
    "sf-enrutador-inteligente": SkillSpec(
        "sf-enrutador-inteligente",
        "Enrutador Inteligente",
        "enrutador_inteligente",
        "SolicitudEnrutamiento",
        "evaluar_enrutador_inteligente",
        "automation",
    ),
    "sf-voz-marca-inteligente": SkillSpec(
        "sf-voz-marca-inteligente",
        "Voz de Marca Inteligente",
        "voz_marca_inteligente",
        "SolicitudVozMarca",
        "evaluar_voz_marca_inteligente",
        "communication",
    ),
    "sf-verificador-normativo": SkillSpec(
        "sf-verificador-normativo",
        "Verificador Normativo",
        "verificador_normativo",
        "SolicitudVerificacionNormativa",
        "evaluar_verificador_normativo",
        "knowledge",
    ),
    "sf-puerta-aprobacion-humana": SkillSpec(
        "sf-puerta-aprobacion-humana",
        "Puerta de Aprobacion Humana",
        "puerta_aprobacion_humana",
        "SolicitudAprobacion",
        "evaluar_puerta_aprobacion_humana",
        "automation",
    ),
}


def skillforge_enabled() -> bool:
    """Feature flag — set SKILLFORGE_ENABLED=0 to skip daemon dispatch."""
    return os.getenv("SKILLFORGE_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def is_skillforge_operation(operation_type: Optional[str]) -> bool:
    return bool(operation_type and operation_type.startswith(OPERATION_PREFIX))


def operation_type_for_skill(skill_id: str) -> str:
    """Canonical operation_type id for catalog + tasks."""
    return f"{OPERATION_PREFIX}{skill_id}"


def skill_id_from_operation_type(operation_type: str) -> str:
    """Strip ``skillforge:`` prefix; pass through bare sf-* slugs."""
    if operation_type.startswith(OPERATION_PREFIX):
        return operation_type[len(OPERATION_PREFIX) :]
    return operation_type


def list_skill_ids() -> list[str]:
    return list(SKILL_REGISTRY.keys())


def _merge_task_input(task: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build skill input dict from task payload + optional overrides."""
    base: Dict[str, Any] = {}
    input_json = task.get("input_json")
    if isinstance(input_json, dict):
        base.update(input_json)
    elif isinstance(input_json, str) and input_json.strip():
        base["texto_documento"] = input_json
        base["texto"] = input_json

    desc = (task.get("description") or "").strip()
    if desc and "texto_documento" not in base and "texto" not in base:
        base.setdefault("texto_documento", desc)

    base.setdefault("accion", task.get("operation_type") or "executar")
    base.setdefault("descripcion", task.get("title") or "")
    base.setdefault("solicitante", str(task.get("company_id") or "vectraclaw"))
    base.setdefault("contexto", {"task_id": task.get("id")})

    if extra:
        base.update(extra)
    return base


def _resultado_to_dict(resultado: Any) -> Dict[str, Any]:
    if dataclasses.is_dataclass(resultado):
        return dataclasses.asdict(resultado)
    if isinstance(resultado, dict):
        return resultado
    return {"raw": str(resultado)}


def _build_solicitud(solicitud_cls: Type[Any], payload: Dict[str, Any]) -> Any:
    field_names = {f.name for f in dataclasses.fields(solicitud_cls)}
    kwargs = {k: v for k, v in payload.items() if k in field_names}
    for f in dataclasses.fields(solicitud_cls):
        if f.name not in kwargs and f.default is not dataclasses.MISSING:
            continue
        if f.name not in kwargs and f.default_factory is not dataclasses.MISSING:  # type: ignore[attr-defined]
            continue
    return solicitud_cls(**kwargs)


def _load_skill_module(spec: SkillSpec) -> Any:
    """Import skill module from installed skills-ia-empresariales package."""
    return __import__(
        f"skillforge.skills.{spec.module_name}",
        fromlist=[spec.eval_attr, spec.solicitud_attr],
    )


def _try_load_skillforge_eval(spec: SkillSpec) -> Optional[Callable[..., Any]]:
    """Lazy import eval function; None if package missing."""
    try:
        mod = _load_skill_module(spec)
        return getattr(mod, spec.eval_attr)
    except ImportError as exc:
        logger.debug("skillforge package unavailable for %s: %s", spec.skill_id, exc)
        return None


def _local_fallback_run(spec: SkillSpec, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Local-first minimal execution when upstream package is not installed."""
    if spec.skill_id == "sf-radar-anomalias":
        serie = payload.get("serie") or []
        if not isinstance(serie, list):
            serie = []
        serie_f = [float(x) for x in serie if x is not None]
        if len(serie_f) < 3:
            return {
                "nombre_skill": spec.module_name,
                "estado": "error",
                "salida": {"mensaje": "Serie insuficiente: se requieren al menos 3 valores"},
                "trazas": ["local_fallback", "serie_insuficiente"],
                "advertencias": [],
            }
        media = mean(serie_f)
        desv = pstdev(serie_f)
        umbral = float(payload.get("umbral_desviaciones") or 2.0)
        anomalias = []
        if desv > 0:
            for idx, valor in enumerate(serie_f):
                z = abs((valor - media) / desv)
                if z >= umbral:
                    anomalias.append({"indice": idx, "valor": valor, "z_score": round(z, 4)})
        return {
            "nombre_skill": spec.module_name,
            "estado": "ok",
            "salida": {
                "mensaje": "Radar de anomalias (local fallback)",
                "media": round(media, 4),
                "desviacion": round(desv, 4),
                "total_anomalias": len(anomalias),
                "anomalias": anomalias,
            },
            "trazas": ["local_fallback", "deteccion_finalizada"],
            "advertencias": [] if anomalias else ["no se detectaron anomalias con el umbral actual"],
        }

    if spec.skill_id == "sf-lector-documental":
        texto = (payload.get("texto_documento") or payload.get("texto") or "").strip()
        if not texto:
            return {
                "nombre_skill": spec.module_name,
                "estado": "error",
                "salida": {"mensaje": "Documento vacio"},
                "trazas": ["local_fallback"],
                "advertencias": [],
            }
        bloques = [b.strip() for b in texto.split("\n\n") if b.strip()]
        resumen = [f"S{i}: {b.splitlines()[0][:120]}" for i, b in enumerate(bloques[:10], 1)]
        return {
            "nombre_skill": spec.module_name,
            "estado": "ok",
            "salida": {
                "mensaje": "Lectura documental (local fallback)",
                "total_secciones": len(bloques[:10]),
                "resumen_secciones": resumen,
            },
            "trazas": ["local_fallback"],
            "advertencias": [],
        }

    return {
        "nombre_skill": spec.module_name,
        "estado": "advertencia",
        "salida": {
            "mensaje": (
                "Skillforge package not installed — stub only. "
                "pip install skills-ia-empresariales from GitHub."
            ),
            "skill_id": spec.skill_id,
        },
        "trazas": ["local_fallback", "stub"],
        "advertencias": ["WARN: install skills-ia-empresariales for full local-first modules"],
    }


def run_skill(skill_id: str, input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a Skillforge skill by catalog slug (``sf-*``).

    Returns a JSON-serializable envelope:
        {ok, skill_id, mode, result|error}
    """
    payload = dict(input or {})
    spec = SKILL_REGISTRY.get(skill_id)
    if not spec:
        return {
            "ok": False,
            "skill_id": skill_id,
            "mode": "none",
            "error": f"unknown skill_id: {skill_id}",
            "known_skills": list_skill_ids(),
        }

    eval_fn = _try_load_skillforge_eval(spec)
    mode = "skillforge"

    try:
        if eval_fn is not None:
            mod = _load_skill_module(spec)
            solicitud_cls = getattr(mod, spec.solicitud_attr)
            entrada = _build_solicitud(solicitud_cls, payload)
            resultado = eval_fn(entrada)
            result_dict = _resultado_to_dict(resultado)
            ok = result_dict.get("estado") == "ok"
            return {
                "ok": ok,
                "skill_id": skill_id,
                "mode": mode,
                "result": result_dict,
            }

        mode = "local_fallback"
        result_dict = _local_fallback_run(spec, payload)
        ok = result_dict.get("estado") == "ok"
        return {
            "ok": ok,
            "skill_id": skill_id,
            "mode": mode,
            "result": result_dict,
        }
    except Exception as exc:
        logger.exception("run_skill failed skill_id=%s", skill_id)
        return {
            "ok": False,
            "skill_id": skill_id,
            "mode": mode,
            "error": str(exc),
        }


def run_skill_for_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve skill from task.operation_type and merge task fields into input."""
    op_type = task.get("operation_type") or ""
    skill_id = skill_id_from_operation_type(op_type)
    payload = _merge_task_input(task)
    out = run_skill(skill_id, payload)
    out["operation_type"] = op_type
    out["task_id"] = task.get("id")
    return out
