import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/", response_model=list[AccountRead])
async def list_accounts(db: AsyncSession = Depends(get_db)) -> list[Account]:
    result = await db.execute(select(Account))
    return list(result.scalars().all())


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.post("/", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    db: AsyncSession = Depends(get_db),
) -> Account:
    account = Account(**payload.model_dump())
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    db: AsyncSession = Depends(get_db),
) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Account not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)

    await db.flush()
    await db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(account)
