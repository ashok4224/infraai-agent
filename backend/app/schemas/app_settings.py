from pydantic import BaseModel
from typing import Optional


class AppSettingResponse(BaseModel):
    key: str
    value: str
    category: str
    description: Optional[str] = None
    is_secret: str

    class Config:
        from_attributes = True


class AppSettingUpdate(BaseModel):
    value: str


class AppSettingsBulkUpdate(BaseModel):
    settings: dict[str, str]  # key → value


class SMTPTestRequest(BaseModel):
    to_email: str
