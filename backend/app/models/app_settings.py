"""Key-value app settings stored in the database — configurable from the UI."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False, default="")
    category = Column(String(50), nullable=False, default="general")
    description = Column(String(255), nullable=True)
    is_secret = Column(String(5), nullable=False, default="false")   # "true"/"false"
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
