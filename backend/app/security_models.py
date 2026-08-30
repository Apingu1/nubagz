from datetime import datetime, UTC

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.now(UTC)


class PrivyIdentityBinding(Base):
    """One canonical Privy DID per NuBagz account.

    Social provider identities remain separate evidence records, while this table
    prevents one NuBagz account from silently accumulating accounts from multiple
    unrelated Privy identities. Recovery/rebinding will be an audited Admin flow.
    """

    __tablename__ = "privy_identity_bindings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    privy_user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user = relationship("User")
