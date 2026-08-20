from collections import defaultdict
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, LedgerEntry, Campaign
from ..engagement_models import ReferralConversion
from ..risk_models import UserTrustProfile

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


@router.get("/validate/{code}")
def validate_referral(code: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.referral_code == code.upper(), User.is_active.is_(True)).first()
    if not user:
        return {"valid": False, "eligible": False}
    profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == user.id).first()
    eligible = not profile or profile.trust_level != "RESTRICTED"
    return {"valid": True, "eligible": eligible, "referrer": user.username if eligible else None}


@router.get("/me")
def my_referrals(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    referred = db.query(User).filter(User.referred_by_id == user.id).order_by(User.created_at.desc()).all()
    referred_ids = [u.id for u in referred]
    conversions = db.query(ReferralConversion).filter(ReferralConversion.referrer_id == user.id).order_by(ReferralConversion.created_at.desc()).all()
    paid = [c for c in conversions if c.status == "PAID"]
    redirected = [c for c in conversions if c.status == "REDIRECTED"]
    converted_user_ids = {c.referred_user_id for c in paid}

    entries = db.query(LedgerEntry).filter(LedgerEntry.user_id == user.id, LedgerEntry.entry_type == "REFERRAL_SHARE").all()
    earnings = defaultdict(Decimal)
    for entry in entries:
        earnings[entry.asset_symbol] += Decimal(entry.amount)

    by_person: dict[int, list[ReferralConversion]] = defaultdict(list)
    for conversion in conversions:
        by_person[conversion.referred_user_id].append(conversion)

    people = []
    for person in referred[:50]:
        person_conversions = by_person.get(person.id, [])
        paid_for_person = [c for c in person_conversions if c.status == "PAID"]
        people.append({
            "username": person.username,
            "joined_at": person.created_at.isoformat(),
            "bag_score": person.bag_score,
            "converted": bool(paid_for_person),
            "paid_conversions": len(paid_for_person),
            "redirected_conversions": len([c for c in person_conversions if c.status == "REDIRECTED"]),
            "last_conversion_at": person_conversions[0].created_at.isoformat() if person_conversions else None,
        })

    events = []
    for conversion in conversions[:50]:
        campaign = db.get(Campaign, conversion.campaign_id)
        referred_user = db.get(User, conversion.referred_user_id)
        events.append({
            "id": conversion.id,
            "referred_username": referred_user.username if referred_user else f"User #{conversion.referred_user_id}",
            "campaign": campaign.title if campaign else f"Bag #{conversion.campaign_id}",
            "asset": conversion.asset_symbol,
            "allocated_amount": str(conversion.allocated_amount),
            "paid_amount": str(conversion.paid_amount),
            "status": conversion.status,
            "reason": conversion.reason,
            "created_at": conversion.created_at.isoformat(),
        })

    total_people = len(referred)
    return {
        "referral_code": user.referral_code,
        "referral_path": f"/register?ref={user.referral_code}",
        "referred_users": total_people,
        "converted_users": len(converted_user_ids),
        "pending_users": max(0, total_people - len(converted_user_ids)),
        "completed_campaign_conversions": len(paid),
        "redirected_conversions": len(redirected),
        "conversion_rate_pct": str((Decimal(len(converted_user_ids)) / Decimal(total_people) * Decimal("100")) if total_people else Decimal("0")),
        "earnings": [{"asset": asset, "amount": str(value)} for asset, value in sorted(earnings.items())],
        "people": people,
        "events": events,
        "rule": "No reward is paid for a signup. Referral earnings are created only when a referred user completes a campaign with a pre-funded referral allocation.",
        "abuse_rule": "If a referrer is restricted for anti-farming review at settlement, that campaign's referral allocation is redirected to the community treasury instead of being paid to the referrer.",
    }
