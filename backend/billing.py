"""Stripe billing + usage tracking for JobSync.

Public surface:
  - PLANS: dict of plan_id -> metadata (cap, display name, price label).
  - get_plan_for_user(user): returns the plan the user should be on right now
    (i.e., 'pro' if their Stripe subscription is active, else 'free' unless
    grandfathered).
  - get_usage_this_month(user, db): count of usage events for the current
    calendar month.
  - check_and_increment_usage(user, db, event_type, job_id=None): atomically
    verify the user is under their cap and insert a UsageEvent row. Returns
    (allowed: bool, used: int, cap: int, plan: str, reason: Optional[str]).
  - create_checkout_session(user, db, success_url, cancel_url) -> Stripe URL
  - create_portal_session(user, db, return_url) -> Stripe URL
  - handle_webhook_event(event: stripe.Event, db) -> applies state changes.

Usage is counted on successful resume generation only. The cap is per
calendar month (UTC). A user is on the 'pro' plan if either:
  (a) they have a Subscription row with status in {active, trialing}, OR
  (b) they were grandfathered to pro at migration time (plan_grandfathered=TRUE).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import stripe
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Subscription, UsageEvent, User

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Plan config
# ----------------------------------------------------------------------------

PLAN_FREE = "free"
PLAN_PRO = "pro"

# Caps per plan, counted as resume-generation events per calendar month (UTC).
# Override via env vars if you ever need to A/B test or change without a deploy.
PLANS = {
    PLAN_FREE: {
        "name": "Free",
        "cap": int(os.getenv("BILLING_FREE_CAP", "3")),
        "price_label": "Free",
    },
    PLAN_PRO: {
        "name": "Pro",
        "cap": int(os.getenv("BILLING_PRO_CAP", "50")),
        "price_label": os.getenv("BILLING_PRO_PRICE_LABEL", "$9.99 / month"),
    },
}

# Event types we count toward the cap. Only one for now, but kept extensible.
COUNTED_EVENT_TYPES = ("resume_generation",)

# Stripe subscription statuses that grant pro access.
PRO_STATUSES = ("active", "trialing")


# ----------------------------------------------------------------------------
# Stripe client init
# ----------------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID_PRO = os.getenv("STRIPE_PRICE_ID_PRO")  # monthly recurring price

# When True, billing is effectively disabled: every user is treated as pro
# with no cap. Useful for local dev when Stripe isn't configured.
# We auto-enable this when STRIPE_SECRET_KEY is not set, so out-of-the-box
# local dev doesn't require Stripe.
BILLING_DISABLED = not bool(STRIPE_SECRET_KEY)

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Public site URL used to build absolute success/cancel URLs for Stripe.
PUBLIC_SITE_URL = os.getenv(
    "PUBLIC_SITE_URL",
    "https://job-app-913142543866.us-west1.run.app",
).rstrip("/")


# ----------------------------------------------------------------------------
# Result types
# ----------------------------------------------------------------------------

@dataclass
class UsageCheck:
    allowed: bool
    used: int
    cap: int
    plan: str
    reason: Optional[str] = None  # human-readable reason when not allowed

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "used": self.used,
            "cap": self.cap,
            "plan": self.plan,
            "remaining": max(0, self.cap - self.used),
            "reason": self.reason,
        }


# ----------------------------------------------------------------------------
# Plan resolution
# ----------------------------------------------------------------------------

def get_effective_plan(user: User) -> str:
    """Resolve which plan the user should be treated as right now.

    Priority:
      1. Grandfathered users stay 'pro' forever (no card required).
      2. Active Stripe subscription -> 'pro'.
      3. Otherwise 'free'.
    """
    if getattr(user, "plan_grandfathered", False):
        return PLAN_PRO
    if getattr(user, "plan", PLAN_FREE) == PLAN_PRO:
        # Double-check the subscription is still actually active; the user.plan
        # column may be stale if a webhook was missed.
        if user.subscription and user.subscription.status in PRO_STATUSES:
            return PLAN_PRO
        return PLAN_FREE
    return getattr(user, "plan", PLAN_FREE) or PLAN_FREE


def plan_cap(plan: str) -> int:
    return PLANS.get(plan, PLANS[PLAN_FREE])["cap"]


# ----------------------------------------------------------------------------
# Usage counting
# ----------------------------------------------------------------------------

def _month_start_utc(now: Optional[datetime] = None) -> datetime:
    """Return a timezone-aware UTC datetime for the 1st of the current month
    at 00:00:00. We compare against created_at which is naive UTC (matching
    the rest of the codebase, e.g. Job.created_at = datetime.utcnow)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_usage_this_month(
    user: User,
    db: Session,
    event_type: str = "resume_generation",
    now: Optional[datetime] = None,
) -> int:
    """Count of `event_type` rows for the user in the current UTC month."""
    if BILLING_DISABLED:
        return 0
    month_start = _month_start_utc(now)
    return (
        db.query(func.count(UsageEvent.id))
        .filter(
            UsageEvent.user_id == user.id,
            UsageEvent.event_type == event_type,
            UsageEvent.created_at >= month_start.replace(tzinfo=None),
        )
        .scalar()
        or 0
    )


def check_and_increment_usage(
    user: User,
    db: Session,
    event_type: str = "resume_generation",
    job_id: Optional[int] = None,
) -> UsageCheck:
    """Verify the user is under cap and insert a UsageEvent row.

    Returns a UsageCheck describing the outcome. If allowed=False, no row is
    inserted (caller should reject the request with 402). If allowed=True, a
    row is inserted in the same transaction and committed.

    Note: This is a small race window between SELECT count and INSERT. For a
    single-user app this is fine; if you ever go multi-tenant, wrap in a
    SELECT FOR UPDATE on the user row, or use a unique constraint trick.
    """
    plan = get_effective_plan(user)
    cap = plan_cap(plan)
    used = get_usage_this_month(user, db, event_type=event_type)

    if used >= cap:
        return UsageCheck(
            allowed=False,
            used=used,
            cap=cap,
            plan=plan,
            reason=(
                f"You've used all {cap} {PLANS[plan]['name']} generations this month. "
                "Upgrade to Pro for more."
            ),
        )

    if BILLING_DISABLED:
        # Don't pollute the usage_events table when Stripe isn't configured.
        return UsageCheck(allowed=True, used=used, cap=cap, plan=plan)

    event = UsageEvent(
        user_id=user.id,
        event_type=event_type,
        job_id=job_id,
        plan_at_event=plan,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return UsageCheck(allowed=True, used=used + 1, cap=cap, plan=plan)


# ----------------------------------------------------------------------------
# Stripe helpers
# ----------------------------------------------------------------------------

def ensure_stripe_customer(user: User, db: Session) -> str:
    """Return the Stripe customer id for this user, creating one if needed."""
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(
        email=user.email or None,
        name=user.name or None,
        metadata={"auth0_id": user.auth0_id, "user_id": str(user.id)},
    )
    user.stripe_customer_id = customer.id
    db.add(user)
    db.commit()
    db.refresh(user)
    return customer.id


def create_checkout_session(user: User, db: Session, return_url: Optional[str] = None) -> str:
    """Create a Stripe Checkout session for the Pro plan and return its URL."""
    if BILLING_DISABLED:
        raise RuntimeError("Billing is disabled (no STRIPE_SECRET_KEY configured).")
    if not STRIPE_PRICE_ID_PRO:
        raise RuntimeError("STRIPE_PRICE_ID_PRO is not configured.")

    customer_id = ensure_stripe_customer(user, db)
    success_url = f"{return_url or PUBLIC_SITE_URL}/?billing=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{return_url or PUBLIC_SITE_URL}/?billing=canceled"

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": STRIPE_PRICE_ID_PRO, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id), "auth0_id": user.auth0_id},
        subscription_data={
            "metadata": {"user_id": str(user.id), "auth0_id": user.auth0_id},
        },
    )
    return session.url


def create_portal_session(user: User, db: Session, return_url: Optional[str] = None) -> str:
    if BILLING_DISABLED:
        raise RuntimeError("Billing is disabled (no STRIPE_SECRET_KEY configured).")
    if not user.stripe_customer_id:
        raise RuntimeError("No Stripe customer for this user yet.")
    portal = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=return_url or PUBLIC_SITE_URL,
    )
    return portal.url


# ----------------------------------------------------------------------------
# Webhook handling
# ----------------------------------------------------------------------------

def _apply_subscription_state(sub: Subscription, stripe_sub: dict) -> None:
    """Map a Stripe subscription dict onto our Subscription row."""
    sub.stripe_subscription_id = stripe_sub.get("id")
    sub.stripe_price_id = (stripe_sub.get("items", {}).get("data", [{}])[0]
                            .get("price", {}).get("id"))
    sub.status = stripe_sub.get("status", sub.status)
    sub.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end", False))
    cps = stripe_sub.get("current_period_start")
    cpe = stripe_sub.get("current_period_end")
    if cps:
        sub.current_period_start = datetime.utcfromtimestamp(cps)
    if cpe:
        sub.current_period_end = datetime.utcfromtimestamp(cpe)
    if stripe_sub.get("canceled_at"):
        sub.canceled_at = datetime.utcfromtimestamp(stripe_sub["canceled_at"])


def _user_id_from_metadata(stripe_obj: dict, db: Session) -> Optional[User]:
    """Resolve a User from a Stripe object's metadata. Falls back to looking
    up by stripe_customer_id on the user table."""
    meta = stripe_obj.get("metadata") or {}
    user_id = meta.get("user_id")
    if user_id:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if user:
            return user
    # Fallback: customer id
    customer_id = stripe_obj.get("customer") or stripe_obj.get("id")
    if customer_id and not str(customer_id).startswith("sub_"):
        # This is a customer object (not a subscription)
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            return user
    # Subscription: look up by stripe_customer_id
    customer_id = stripe_obj.get("customer")
    if customer_id:
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            return user
    return None


def handle_webhook_event(event: dict, db: Session) -> str:
    """Apply a Stripe webhook event to our DB. Returns a short status string."""
    etype = event.get("type")
    obj = event.get("data", {}).get("object", {})

    if etype in ("customer.subscription.created", "customer.subscription.updated",
                 "customer.subscription.deleted", "customer.subscription.trial_will_end"):
        stripe_sub = obj
        customer_id = stripe_sub.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if not user:
            logger.warning(f"[stripe-webhook] No user for customer {customer_id}; ignoring {etype}")
            return "user-not-found"

        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not sub:
            sub = Subscription(user_id=user.id, stripe_customer_id=customer_id)
            db.add(sub)
        _apply_subscription_state(sub, stripe_sub)

        # Mirror status onto user.plan (but never override grandfathered users).
        is_pro = sub.status in PRO_STATUSES
        if not user.plan_grandfathered:
            user.plan = PLAN_PRO if is_pro else PLAN_FREE

        db.commit()
        logger.info(
            f"[stripe-webhook] {etype} -> user={user.id} sub_status={sub.status} plan={user.plan}"
        )
        return "ok"

    if etype in ("checkout.session.completed",):
        # Mostly informational — the subscription.* events will carry the
        # canonical state. We use this to log a successful first checkout.
        customer_id = obj.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            logger.info(f"[stripe-webhook] checkout.session.completed for user {user.id}")
        return "ok"

    if etype in ("invoice.payment_succeeded", "invoice.payment_failed"):
        # We rely on subscription.* events for state, so just log.
        logger.info(f"[stripe-webhook] {etype} received (no-op for our state)")
        return "ok"

    logger.debug(f"[stripe-webhook] Unhandled event type: {etype}")
    return "unhandled"


# ----------------------------------------------------------------------------
# Frontend-facing config
# ----------------------------------------------------------------------------

def get_public_config() -> dict:
    """Safe-to-expose config for the SPA: publishable key, plan info."""
    return {
        "billing_enabled": not BILLING_DISABLED,
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY or None,
        "price_label": PLANS[PLAN_PRO]["price_label"],
        "plans": {
            PLAN_FREE: {"name": PLANS[PLAN_FREE]["name"], "cap": PLANS[PLAN_FREE]["cap"]},
            PLAN_PRO: {"name": PLANS[PLAN_PRO]["name"], "cap": PLANS[PLAN_PRO]["cap"]},
        },
    }
