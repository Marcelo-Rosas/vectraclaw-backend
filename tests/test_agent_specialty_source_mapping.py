"""Mapeamento source DB (§2.1) ↔ Zod Clip (internal|skillforge|...)."""
from src.models import (
    AgentSpecialty,
    specialty_source_db_to_zod,
    specialty_source_zod_to_db,
)


def test_seed_maps_to_internal():
    assert specialty_source_db_to_zod("seed") == "internal"
    assert specialty_source_zod_to_db("internal") == "seed"


def test_skillforge_slug_maps_from_import_csv():
    assert specialty_source_db_to_zod("import_csv", "sf-radar-anomalias") == "skillforge"
    assert specialty_source_db_to_zod("import_csv", "oracle-research") == "import_csv"


def test_agent_specialty_to_zod_dict_emits_internal():
    row = AgentSpecialty(
        id="test-spec",
        name="Test",
        slug="test-spec",
        domain="knowledge",
        compatible_roles=["operator"],
        source="seed",
    )
    assert row.to_zod_dict()["source"] == "internal"
