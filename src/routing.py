from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import EmailOperationalContext

INFORMATIONAL_TOPIC_HINTS = {
    "fysa",
    "for awareness",
    "awareness",
    "weekly update",
    "status update",
    "briefing",
    "briefing attached",
    "meeting notes",
    "minutes",
    "distribution list",
    "cc-only",
    "cc only",
}

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


def determine_routing(
    ctx: EmailOperationalContext,
    *,
    sender_affinity_hit: bool = False,
    thread_affinity_hit: bool = False,
    confidence_boost_hit: bool = False,
    operational_memory_hit: bool = False,
) -> RoutingDecision:
    confidence = float(ctx.confidence)
    high_confidence = confidence >= 0.8
    medium_confidence = 0.5 <= confidence < 0.8
    low_confidence = confidence < 0.5
    topics = {t.strip().lower() for t in (ctx.topics or []) if t and t.strip()}
    informational_signal = bool(topics & INFORMATIONAL_TOPIC_HINTS)
    has_action_summary = bool((ctx.action_summary or "").strip())
    clear_action = bool(ctx.clear_action_for_user)
    affinity_hit = bool(sender_affinity_hit or thread_affinity_hit)
    operational_memory_signal = bool(operational_memory_hit or affinity_hit)
    no_clear_action_required = not (ctx.action_required or ctx.follow_up_required or ctx.waiting_on_me or clear_action)
    if ctx.waiting_on_me and has_action_summary:
        return RoutingDecision("KEEP", "Inbox", "deterministic", "waiting_on_me:direct_tasking")
    if ctx.follow_up_required and clear_action and has_action_summary:
        return RoutingDecision("KEEP", "Inbox", "deterministic", "follow_up_required")
    if ctx.action_required and clear_action and has_action_summary:
        return RoutingDecision("KEEP", "Inbox", "deterministic", "action_required:clear_action")

    if ctx.action_required and (not clear_action or not has_action_summary):
        return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", "action_required_but_vague")

    if no_clear_action_required and operational_memory_signal and affinity_hit and (ctx.operational_class in {"CUSTOMER", "PROJECT"}):
        if ctx.operational_class == "CUSTOMER" and ctx.customer_or_org:
            return RoutingDecision("MOVE", f"AI Sorted/Customers/{normalize_name(ctx.customer_or_org)}", "deterministic", "operational_memory_affinity_override")
        if ctx.operational_class == "PROJECT" and ctx.project:
            return RoutingDecision("MOVE", f"AI Sorted/Projects/{normalize_name(ctx.project)}", "deterministic", "operational_memory_affinity_override")

    if no_clear_action_required and operational_memory_signal and confidence_boost_hit:
        if ctx.operational_class == "CUSTOMER" and ctx.customer_or_org:
            return RoutingDecision("MOVE", f"AI Sorted/Customers/{normalize_name(ctx.customer_or_org)}", "deterministic", "confidence_boost_operational_override")
        if ctx.operational_class == "PROJECT" and ctx.project:
            return RoutingDecision("MOVE", f"AI Sorted/Projects/{normalize_name(ctx.project)}", "deterministic", "confidence_boost_operational_override")

    if low_confidence and not (informational_signal and operational_memory_signal):
        return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", "low_confidence_non_action")

    if ctx.operational_class == "CUSTOMER" and ctx.customer_or_org:
        customer = normalize_name(ctx.customer_or_org)
        rule = "customer_affinity_prefer_folder" if affinity_hit else ("customer_informational_prefer_folder" if informational_signal or medium_confidence or high_confidence else "customer_no_action:normalized_org")
        return RoutingDecision("MOVE", f"AI Sorted/Customers/{customer}", "deterministic", rule)

    if ctx.operational_class == "PROJECT" and ctx.project:
        if medium_confidence:
            return RoutingDecision("MOVE", f"AI Sorted/Projects/{normalize_name(ctx.project)}", "deterministic", "project_medium_confidence_prefer_folder")
        if high_confidence:
            return RoutingDecision("MOVE", f"AI Sorted/Projects/{normalize_name(ctx.project)}", "deterministic", "project_no_action")
        return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", "weak_project_inference")

    if ctx.operational_class == "TRAVEL":
        return RoutingDecision("MOVE", "AI Sorted/Travel", "deterministic", "travel")
    if ctx.operational_class == "CALENDAR":
        return RoutingDecision("MOVE", "AI Sorted/Calendar", "deterministic", "calendar")
    if ctx.operational_class == "FINANCE":
        return RoutingDecision("MOVE", "AI Sorted/Finance", "deterministic", "finance")
    if ctx.operational_class in {"NEWSLETTER", "AUTOMATION", "SALES_SPAM"} and ctx.confidence >= 0.9:
        return RoutingDecision("MOVE", "AI Sorted/Delete", "deterministic", "low_value_high_confidence")
    reason = "fallback_needs_review:insufficient_signals"
    if operational_memory_signal:
        reason = "needs_review:operational_memory_insufficient_no_customer_or_project_affinity"
    return RoutingDecision("MOVE", "AI Sorted/Needs Review", "deterministic", reason)
