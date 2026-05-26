from src.models import EmailOperationalContext
from src.operational_memory import OperationalMemory
from src.routing import determine_routing


def make_ctx(**kwargs):
    base = dict(
        operational_class="PROJECT",
        customer_or_org=None,
        project=None,
        needs_user_attention=False,
        action_required=False,
        follow_up_required=False,
        action_summary=None,
        clear_action_for_user=False,
        should_leave_in_inbox=False,
        urgency="LOW",
        waiting_on_me=False,
        waiting_on_external=False,
        deadline_detected=None,
        confidence=0.45,
        reason="seed",
        topics=[],
    )
    base.update(kwargs)
    return EmailOperationalContext(**base)


def test_repeated_melco_emails_strengthen_affinity(tmp_path):
    store = OperationalMemory(tmp_path / "memory.db")
    for i in range(3):
        ctx = make_ctx(operational_class="CUSTOMER", customer_or_org="Melco Resorts", confidence=0.78)
        store.store_outcome(
            message_id=f"m{i}",
            sender="ops@melco.com",
            subject="Melco weekly update",
            body_preview="fysa melco status",
            participants="ops@melco.com|lewis@x.com",
            ctx=ctx,
            target_folder="AI Sorted/Customers/Melco",
            source="deterministic",
        )
    cold = make_ctx(operational_class="UNKNOWN", confidence=0.35)
    affinity = store.score(sender="ops@melco.com", subject="Re: Melco weekly update", body_preview="fysa", participants="ops@melco.com|lewis@x.com", ctx=cold)
    assert affinity.sender_affinity_hit is True
    assert affinity.normalized_org == "Melco"
    assert affinity.boosted_confidence > cold.confidence


def test_recurring_taiwan_threads_route_to_project(tmp_path):
    store = OperationalMemory(tmp_path / "memory.db")
    for i in range(3):
        ctx = make_ctx(project="Taiwan MND", confidence=0.7)
        store.store_outcome(
            message_id=f"t{i}",
            sender="pm@lnic.com.au",
            subject="Taiwan MND coordination",
            body_preview="Taiwan MND sync",
            participants="pm@lnic.com.au|lewis@x.com",
            ctx=ctx,
            target_folder="AI Sorted/Projects/Taiwan_MND",
            source="deterministic",
        )
    cold = make_ctx(operational_class="UNKNOWN", confidence=0.4)
    affinity = store.score(sender="pm@lnic.com.au", subject="Re: Taiwan MND coordination", body_preview="status", participants="pm@lnic.com.au|lewis@x.com", ctx=cold)
    enriched = make_ctx(operational_class="PROJECT", project=affinity.normalized_project, confidence=affinity.boosted_confidence)
    d = determine_routing(enriched)
    assert affinity.thread_affinity_hit is True
    assert d.target_folder == "AI Sorted/Projects/Taiwan_MND"


def test_informational_known_sender_avoids_needs_review(tmp_path):
    store = OperationalMemory(tmp_path / "memory.db")
    seed = make_ctx(operational_class="CUSTOMER", customer_or_org="LNIC Pty Ltd", confidence=0.82)
    store.store_outcome(
        message_id="a1",
        sender="briefings@lnic.com.au",
        subject="LNIC briefing attached",
        body_preview="fysa weekly update",
        participants="briefings@lnic.com.au|lewis@x.com",
        ctx=seed,
        target_folder="AI Sorted/Customers/LNIC",
        source="deterministic",
    )
    cold = make_ctx(operational_class="UNKNOWN", confidence=0.35, topics=["fysa"])
    affinity = store.score(sender="briefings@lnic.com.au", subject="LNIC briefing attached", body_preview="fysa", participants="briefings@lnic.com.au|lewis@x.com", ctx=cold)
    enriched = make_ctx(operational_class="CUSTOMER", customer_or_org=affinity.normalized_org, confidence=affinity.boosted_confidence, topics=["fysa"])
    d = determine_routing(enriched)
    assert d.target_folder != "AI Sorted/Needs Review"


def test_unrelated_mail_does_not_overfit(tmp_path):
    store = OperationalMemory(tmp_path / "memory.db")
    seed = make_ctx(operational_class="CUSTOMER", customer_or_org="Melco", confidence=0.9)
    store.store_outcome(
        message_id="z1",
        sender="ops@melco.com",
        subject="Melco status",
        body_preview="melco status",
        participants="ops@melco.com|lewis@x.com",
        ctx=seed,
        target_folder="AI Sorted/Customers/Melco",
        source="deterministic",
    )
    cold = make_ctx(operational_class="UNKNOWN", confidence=0.3)
    affinity = store.score(sender="someone@unknown.org", subject="Random newsletter", body_preview="crypto sale", participants="someone@unknown.org|lewis@x.com", ctx=cold)
    assert affinity.sender_affinity_hit is False
    assert affinity.thread_affinity_hit is False
    assert affinity.boosted_confidence <= 0.37
