def build_tools_prompt(
    tools_enabled: dict | None = None, notifications: dict | None = None
) -> str:
    tools = tools_enabled or {}
    notifications_cfg = notifications or {}
    use_default_phone = bool(notifications_cfg.get("use_default_phone", False))
    has_saved_phone = bool(str(notifications_cfg.get("default_phone", "")).strip())
    if not bool(tools.get("schedule_viewing", True)):
        return (
            "Scheduling tools are disabled. "
            "Do not offer slots, do not ask for booking details, and do not try to schedule viewings. "
            "Only use project information tools to answer development questions naturally."
        )

    sms_instruction = (
        "Before calling send_sms_confirmation, repeat the phone number and get explicit user confirmation. "
    )
    if use_default_phone and has_saved_phone:
        sms_instruction = (
            "A default notification phone is configured. "
            "Use that saved number for both schedule_viewing_tool and send_sms_confirmation. "
            "Do not ask the user for a phone number unless they ask to use a different one. "
        )

    return (
        "Use tools only when needed. "
        "You are scheduling for one development only. "
        "For any factual detail about the development, units, or pricing, call get_development_details_tool first. "
        "Confirm details before scheduling. "
        "Only offer one-hour slots between 09:00 and 20:00. "
        "After schedule_viewing_tool returns, clearly tell the user whether the calendar event was created or skipped. "
        "If calendar creation failed, explain that booking was not completed and ask to retry. "
        f"{sms_instruction}"
        "After successful scheduling, ask for permission to send SMS confirmation and then call send_sms_confirmation when the user agrees. "
        "Offer two available times when possible."
    )
