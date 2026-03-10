from app.models.agent_persona import AgentPersona
from app.models.agent_settings import AgentSettings
from app.models.agent_tools import AgentTools


DEFAULT_AGENT_SETTINGS = AgentSettings(
    id=None,
    system_prompt=(
        "You are a real estate scheduling assistant on a phone call. "
        "Use short sentences. Acknowledge, confirm, and verify. "
        "Never ask for or accept payment info, SSNs, or bank details. "
        "Before sending SMS, ask: 'Can I text you a confirmation?'"
    ),
    persona=AgentPersona(
        id=None,
        name="Alex",
        greeting="Hi, this is Alex with Riverside Realty. How can I help?",
        voice="Rachel",
    ),
    tools=AgentTools(
        id=None,
        search_listings=True,
        check_availability=True,
        schedule_viewing=True,
        google_calendar_mcp=True,
        send_sms_confirmation=True,
    ),
    development={
        "id": "DEV-LA-001",
        "name": "Sunset Terrace Residences",
        "city": "Los Angeles, CA",
        "address": "1200 Sunset Blvd, Los Angeles, CA",
        "starting_price": 850000,
        "description": "A new residential development with curated amenities.",
        "amenities": [
            "Rooftop deck",
            "Fitness center",
            "Coworking lounge",
            "Resident parking",
        ],
    },
    scheduling={
        "timezone": "America/Los_Angeles",
        "start_hour": 9,
        "end_hour": 20,
        "slot_minutes": 60,
    },
    notifications={
        "default_phone": "",
        "use_default_phone": False,
        "require_phone_confirmation": True,
    },
)

DEFAULT_CONFIG = DEFAULT_AGENT_SETTINGS.to_dict()
