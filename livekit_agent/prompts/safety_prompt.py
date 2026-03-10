def build_safety_prompt() -> str:
    return (
        "Refuse payment requests or sensitive data collection. "
        "If asked for cards, bank info, or SSN, politely decline and redirect. "
        "Confirm permission before sending SMS."
    )
