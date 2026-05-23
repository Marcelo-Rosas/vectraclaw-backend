"""Atualiza external_name de sessões Instagram sem nome (Graph API User Profile).

Uso (dev):
  python scripts/backfill_instagram_session_names.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from src.api import supabase
    from src.api_routes.connectors import _find_instagram_config_by_account_id
    from src.services.instagram_profile import resolve_instagram_user_profile

    if not supabase:
        print("supabase indisponivel")
        return 1

    res = (
        supabase.table("connector_sessions")
        .select("id,connector_id,external_id,external_name,external_meta,company_id")
        .eq("channel", "instagram")
        .is_("external_name", "null")
        .limit(200)
        .execute()
    )
    rows = res.data or []
    print(f"sessoes instagram sem external_name: {len(rows)}")

    updated = 0
    for row in rows:
        cfg = _find_instagram_config_by_account_id(str(row.get("connector_id") or ""))
        if not cfg:
            continue
        profile = resolve_instagram_user_profile(
            str(row.get("external_id") or ""),
            access_token=str(cfg.get("access_token") or ""),
            api_version=str(cfg.get("api_version") or "v21.0"),
        )
        if not profile or not profile.get("display"):
            continue
        meta = dict(row.get("external_meta") or {})
        if profile.get("username"):
            meta["username"] = profile["username"]
        if profile.get("name"):
            meta["ig_name"] = profile["name"]
        supabase.table("connector_sessions").update(
            {"external_name": profile["display"], "external_meta": meta}
        ).eq("id", row["id"]).execute()
        updated += 1
        print(f"  ok {row['id'][:8]} -> {profile['display']}")

    print(f"atualizadas: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
