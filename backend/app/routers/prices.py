from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import require_admin
from ..models import User
from ..economy_models import AssetPriceSnapshot

router = APIRouter(prefix="/api/prices", tags=["prices"])


class PriceSnapshotIn(BaseModel):
    asset: str = Field(min_length=1, max_length=24)
    price_gbp: Decimal = Field(gt=0)
    source: str = Field(default="MANUAL", max_length=64)


@router.get("/latest")
def latest_prices(assets: str | None = Query(default=None), db: Session = Depends(get_db)):
    wanted = {a.strip().upper() for a in assets.split(",") if a.strip()} if assets else None
    q = db.query(AssetPriceSnapshot).order_by(AssetPriceSnapshot.asset_symbol.asc(), AssetPriceSnapshot.captured_at.desc(), AssetPriceSnapshot.id.desc())
    rows = q.all()
    latest = {}
    for row in rows:
        symbol = row.asset_symbol.upper()
        if wanted is not None and symbol not in wanted:
            continue
        if symbol not in latest:
            latest[symbol] = {
                "asset": symbol,
                "price_gbp": str(row.price_gbp),
                "source": row.source,
                "captured_at": row.captured_at.isoformat(),
            }
    return list(latest.values())


@router.post("/snapshot")
def add_price_snapshot(data: PriceSnapshotIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = AssetPriceSnapshot(asset_symbol=data.asset.upper(), price_gbp=data.price_gbp, source=data.source)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"asset": row.asset_symbol, "price_gbp": str(row.price_gbp), "source": row.source, "captured_at": row.captured_at.isoformat()}
