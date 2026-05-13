from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.kraken import sync_kraken
from app.services.market_data import update_holdings_prices

router = APIRouter(prefix="/kraken", tags=["kraken"])


@router.post("/sync")
async def sync_kraken_endpoint(db: AsyncSession = Depends(get_db)):
    """Sync trades from Kraken API, recompute crypto holdings, and refresh prices."""
    result = await sync_kraken(db)
    await db.commit()
    # Refresh prices so the new holdings have current market data immediately
    updated = await update_holdings_prices(db)
    await db.commit()
    result["prices_updated"] = updated
    return result
