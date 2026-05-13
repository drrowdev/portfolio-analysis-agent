import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class UserSetting(TimestampMixin, Base):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(String(500))
