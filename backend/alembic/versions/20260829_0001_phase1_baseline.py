"""Phase 1 schema baseline/bootstrap.

Revision ID: 20260829_0001
Revises: None
"""
from alembic import op

from app.db import Base
from app import challenge_models, economy_models, engagement_models, integration_models, marketplace_models, models, risk_models, security_models, trust_models  # noqa: F401

revision = "20260829_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing Phase 1 databases already contain these tables; create_all is
    # intentionally non-destructive and only bootstraps missing tables on fresh
    # deployments. The following revision performs explicit V2 alterations.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # The baseline never destroys an existing NuBagz database.
    pass
