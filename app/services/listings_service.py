from typing import Dict, List

from app.services.config_service import load_config


def search_listings(location: str, budget: int, bedrooms: int) -> List[Dict]:
    config = load_config()
    development = dict(config.get("development", {}))
    if not development:
        development = {
            "id": "DEV-LA-001",
            "name": "Sunset Terrace Residences",
            "city": "Los Angeles, CA",
            "address": "1200 Sunset Blvd, Los Angeles, CA",
            "starting_price": 850000,
            "description": "A new residential development with curated amenities.",
            "amenities": [],
        }

    return [development]
