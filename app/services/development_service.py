from typing import Any, Dict

from app.services.config_service import load_config


def _safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _pricing_summary(development: Dict[str, Any]) -> Dict[str, Any]:
    units = _safe_dict(development.get("units"))
    by_unit: dict[str, dict[str, Any]] = {}
    starting_prices: list[float] = []

    for key, unit_data in units.items():
        details = _safe_dict(unit_data)
        starting_price = details.get("starting_price")
        avg_price = details.get("average_price")
        item = {
            "type": details.get("type", key),
            "starting_price": starting_price,
            "average_price": avg_price,
            "area_sqft_range": details.get("area_sqft_range"),
            "bedrooms": details.get("bedrooms"),
            "bathrooms": details.get("bathrooms"),
        }
        by_unit[key] = item
        if isinstance(starting_price, (int, float)):
            starting_prices.append(float(starting_price))

    summary: Dict[str, Any] = {
        "starting_price": development.get("starting_price"),
        "by_unit": by_unit,
    }
    if starting_prices:
        summary["starting_price_range"] = {
            "min": min(starting_prices),
            "max": max(starting_prices),
        }
    return summary


def get_development_details(section: str = "overview") -> Dict[str, Any]:
    config = load_config()
    development = _safe_dict(config.get("development"))
    normalized_section = (section or "overview").strip().lower()

    overview = {
        "id": development.get("id"),
        "name": development.get("name"),
        "developer": development.get("developer"),
        "city": development.get("city"),
        "address": development.get("address"),
        "description": development.get("description"),
        "story": development.get("story"),
        "stage": development.get("stage"),
        "launch_date": development.get("launch_date"),
        "expected_completion": development.get("expected_completion"),
        "total_units": development.get("total_units"),
        "floors": development.get("floors"),
    }
    pricing = _pricing_summary(development)
    amenities = {
        "amenities": _safe_list(development.get("amenities")),
        "building_features": _safe_list(development.get("building_features")),
    }
    location = {
        "city": development.get("city"),
        "address": development.get("address"),
        "neighborhood": development.get("neighborhood"),
        "nearby": _safe_list(development.get("nearby")),
    }

    sections = {
        "overview": overview,
        "pricing": pricing,
        "amenities": amenities,
        "location": location,
        "all": {
            "overview": overview,
            "pricing": pricing,
            "amenities": amenities,
            "location": location,
        },
    }
    if normalized_section not in sections:
        return {
            "status": "invalid_section",
            "available_sections": list(sections.keys()),
        }
    return sections[normalized_section]
