#!/usr/bin/env python3
"""Seed procurement preferences for the demo personas the frontend switches between.

Run against a live API:  python scripts/seed_personas.py [API_BASE]
Defaults to http://localhost:8000. Idempotent — POST /api/preferences upserts.
"""

import sys

import httpx

PERSONAS = {
    "demo-user": {
        "interested_categories": ["automotive", "energy", "logistics", "manufacturing", "technology"],
        "interested_signals": ["supplier_risk", "tariff", "logistics_disruption", "m_and_a", "regulatory"],
    },
    "auto-buyer": {
        "interested_categories": ["automotive", "manufacturing"],
        "interested_suppliers": ["bosch", "continental", "zf"],
        "interested_regions": ["germany", "poland", "china"],
        "interested_signals": ["supplier_risk", "m_and_a", "tariff"],
    },
    "energy-buyer": {
        "interested_categories": ["energy"],
        "interested_regions": ["europe", "usa", "china"],
        "interested_signals": ["tariff", "regulatory", "logistics_disruption"],
    },
}


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    with httpx.Client(base_url=base, timeout=30.0) as client:
        for user_id, prefs in PERSONAS.items():
            resp = client.post("/api/preferences", json={"user_id": user_id, **prefs})
            resp.raise_for_status()
            print(f"seeded {user_id}: {resp.status_code}")


if __name__ == "__main__":
    main()
