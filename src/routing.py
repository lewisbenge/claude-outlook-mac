from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import EmailOperationalContext

ORG_NORMALIZATION = {
    "lnic pty ltd": "LNIC",
    "lnic": "LNIC",
    "melco resorts": "Melco",
    "melco resorts & entertainment": "Melco",
    "melco": "Melco",
    "lnic.com.au": "LNIC",
    "melco-resorts.com": "Melco",
}


@dataclass
class RoutingDecision:
    action: str
    target_folder: str
    routing_source: str
    matched_rule: str


def normalize_name(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    if key in ORG_NORMALIZATION:
        return ORG_NORMALIZATION[key]
    key = re.sub(r"^https?://", "", key)
    key = key.replace("www.", "")
    if key in ORG_NORMALIZATION:
        return ORG_NORMALIZATION[key]
    value = re.sub(r"[^A-Za-z0-9_ -]", "", value).strip()
    return value.replace(" ", "_")


def determine_routing(ctx: EmailOperationalContext) -> RoutingDecision:
    has_action_summary = bool((ctx.action_summary or "").strip())
    clear_action = bool(ctx.clear_action_for_user)
    if ctx.waiting_on_me and has_action_summary:
        return RoutingDecision("KEEP", "Inbox", "deterministic", "waiting_on_me:direct_tasking")
    if ctx.follow_up_required and clear_action and has_action_summary:
        return RoutingDecision("KEEP", "Inbox", "deterministic", "follow_up_required")
    if ctx.action_required and clear_action and has_action_summary:
        return RoutingDecision("KEEP", "Inbox", "deterministic", "action_required:clear_action")

    if ctx.action_required and (not clear_action or not has_action_summary):
        return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", "action_required_but_vague")
    if ctx.confidence < 0.5:
        return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", "low_confidence_non_action")

    if ctx.operational_class == "CUSTOMER" and ctx.customer_or_org:
        customer = normalize_name(ctx.customer_or_org)
        return RoutingDecision("MOVE", f"AI Sorted/Customers/{customer}", "deterministic", "customer_no_action:normalized_org")

    if ctx.operational_class == "PROJECT" and ctx.project:
        if ctx.confidence < 0.75:
            return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", "weak_project_inference")
        return RoutingDecision("MOVE", f"AI Sorted/Projects/{normalize_name(ctx.project)}", "deterministic", "project_no_action")

    if ctx.operational_class == "TRAVEL":
        return RoutingDecision("MOVE", "AI Sorted/Travel", "deterministic", "travel")
    if ctx.operational_class == "CALENDAR":
        return RoutingDecision("MOVE", "AI Sorted/Calendar", "deterministic", "calendar")
    if ctx.operational_class == "FINANCE":
        return RoutingDecision("MOVE", "AI Sorted/Finance", "deterministic", "finance")
    if ctx.operational_class in {"NEWSLETTER", "AUTOMATION", "SALES_SPAM"} and ctx.confidence >= 0.9:
        return RoutingDecision("MOVE", "AI Sorted/Delete", "deterministic", "low_value_high_confidence")
    return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", "fallback_needs_review:insufficient_signals")
