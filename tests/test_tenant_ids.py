"""Mapeamento company row → id público da API (multi-tenant fase 1)."""
from src.tenant_ids import company_row_public_id


def test_company_row_public_id_prefers_company_id():
    assert company_row_public_id({"company_id": "a", "id": "b"}) == "a"


def test_company_row_public_id_falls_back_to_id():
    assert company_row_public_id({"id": "legacy-only"}) == "legacy-only"


def test_company_row_public_id_none():
    assert company_row_public_id(None) is None
    assert company_row_public_id({}) is None
