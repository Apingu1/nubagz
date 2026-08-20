from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.orm import Session
from .models import LedgerEntry


# Only these entries consume the verified inventory allocated to a funded Bag.
# Other products (for example a later fixed revenue-share distribution) may keep
# campaign_id for attribution, but must never reduce the campaign's reward pool.
CAMPAIGN_SETTLEMENT_ENTRY_TYPES = {
    "CAMPAIGN_REWARD",
    "BUILDER_SHARE",
    "PLATFORM_SHARE",
    "REFERRAL_SHARE",
    "COMMUNITY_SHARE",
}


def campaign_distributed_total(db: Session, campaign_id: int) -> Decimal:
    amount = db.query(func.coalesce(func.sum(LedgerEntry.amount), 0)).filter(
        LedgerEntry.campaign_id == campaign_id,
        LedgerEntry.entry_type.in_(CAMPAIGN_SETTLEMENT_ENTRY_TYPES),
    ).scalar() or Decimal("0")
    return Decimal(amount)
