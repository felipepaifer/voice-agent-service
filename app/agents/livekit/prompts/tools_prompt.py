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
        "If user intent is to schedule a viewing, prioritize booking flow and do not provide development details unless the user explicitly asks for them. "
        "Only call get_development_details_tool when the user asks about pricing, amenities, location, or unit details. "
        "For scheduling intent, follow this strict order: confirm date -> check_availability_tool -> propose slots -> confirm caller name exactly -> schedule_viewing_tool. "
        "When a caller asks for times on a day, call check_availability_tool for that exact date before proposing any slot. "
        "Only suggest times that appear in check_availability_tool results; never invent or assume availability. "
        "If check_availability_tool returns no slots, say the day is fully booked and ask for another date. "
        "Only offer one-hour slots between 09:00 and 20:00. "
        "Never alter the caller's provided name. If unsure, ask the caller to repeat and confirm before scheduling. "
        "After schedule_viewing_tool returns, clearly tell the user whether the calendar event was created or skipped. "
        "If calendar creation failed, explain that booking was not completed and ask to retry. "
        "You may briefly describe your next step in one natural, human sentence. "
        "Do not mention tools, APIs, payloads, templates, or technical processing. "
        "Do not ask the caller to provide or compose SMS message text. "
        "When calling send_sms_confirmation, always provide a short confirmation SMS message in the message argument. "
        "Use natural examples like: 'Let me quickly check that for you.' or 'I'm sending your confirmation text now.' "
        f"{sms_instruction}"
        "After successful scheduling, ask for permission to send SMS confirmation and then call send_sms_confirmation when the user agrees. "
        "When SMS is approved, say 'I'm sending your confirmation text now.' and call send_sms_confirmation immediately in the same turn. "
        "Offer two available times when possible."
    )
