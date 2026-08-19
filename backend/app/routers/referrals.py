from collections import defaultdict
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Enrollment, LedgerEntry

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


@router.get("/me")
def my_referrals(db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    referred=db.query(User).filter(User.referred_by_id==user.id).order_by(User.created_at.desc()).all()
    referred_ids=[u.id for u in referred]
    conversions=0
    if referred_ids:
        conversions=db.query(func.count(Enrollment.id)).filter(Enrollment.user_id.in_(referred_ids),Enrollment.status=="COMPLETED").scalar() or 0
    entries=db.query(LedgerEntry).filter(LedgerEntry.user_id==user.id,LedgerEntry.entry_type=="REFERRAL_SHARE").all()
    earnings=defaultdict(Decimal)
    for e in entries: earnings[e.asset_symbol]+=Decimal(e.amount)
    return {
        "referral_code":user.referral_code,
        "referral_path":f"/register?ref={user.referral_code}",
        "referred_users":len(referred),
        "completed_campaign_conversions":int(conversions),
        "earnings":[{"asset":a,"amount":str(v)} for a,v in sorted(earnings.items())],
        "people":[{"username":u.username,"joined_at":u.created_at.isoformat(),"bag_score":u.bag_score} for u in referred[:50]],
        "rule":"Referral rewards come from a campaign's pre-funded referral allocation. NuBagz does not pay cash merely for account creation.",
    }
