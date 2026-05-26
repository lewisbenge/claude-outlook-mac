from src.models import EmailOperationalContext
from src.routing import determine_routing


def ctx(**kwargs):
    base = dict(
        operational_class="UNKNOWN",
        customer_or_org=None,
        project=None,
        needs_user_attention=False,
        action_required=False,
        follow_up_required=False,
        action_summary=None,
        urgency="LOW",
        waiting_on_me=False,
        waiting_on_external=False,
        deadline_detected=None,
        confidence=0.95,
        reason="t",
        topics=[],
    )
    base.update(kwargs)
    return EmailOperationalContext(**base)


def test_travel_routing():
    d = determine_routing(ctx(operational_class="TRAVEL"))
    assert d.target_folder == "AI Sorted/Travel"


def test_customer_routing():
    d = determine_routing(ctx(operational_class="CUSTOMER", customer_or_org="LNIC Pty Ltd"))
    assert d.target_folder == "AI Sorted/Customers/LNIC"


def test_project_routing():
    d = determine_routing(ctx(operational_class="PROJECT", project="Taiwan MND"))
    assert d.target_folder == "AI Sorted/Projects/Taiwan_MND"


def test_action_request_kept_inbox():
    d = determine_routing(ctx(waiting_on_me=True, operational_class="PROJECT", project="ASPI"))
    assert d.target_folder == "Inbox"


def test_unknown_non_action_to_needs_review():
    d = determine_routing(ctx(confidence=0.5))
    assert d.target_folder == "AI Sorted/Needs Review"


def test_newsletter_high_confidence_delete_folder():
    d = determine_routing(ctx(operational_class="NEWSLETTER", confidence=0.92))
    assert d.target_folder == "AI Sorted/Delete"


def test_org_domain_alias_normalization():
    d = determine_routing(ctx(operational_class="CUSTOMER", customer_or_org="https://www.melco-resorts.com"))
    assert d.target_folder == "AI Sorted/Customers/Melco"


def test_weak_project_inference_to_needs_review():
    d = determine_routing(ctx(operational_class="PROJECT", project="ASPI Alpha", confidence=0.6))
    assert d.target_folder == "AI Sorted/Needs Review"
    assert d.matched_rule == "weak_project_inference"


def test_weak_action_inference_prefers_needs_review():
    d = determine_routing(ctx(action_required=True, confidence=0.6))
    assert d.target_folder == "AI Sorted/Needs Review"
    assert d.matched_rule == "weak_action_inference"
