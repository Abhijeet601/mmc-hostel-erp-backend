from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import NoticeCategory


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    username: str


class AdminMeResponse(BaseModel):
    username: str


class NoticeResponse(BaseModel):
    id: int
    title: str
    description: str
    publish_to: NoticeCategory
    is_active: bool
    link: str | None
    file_url: str | None
    file_name: str | None
    published: bool
    pinned: bool
    publish_date: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryItem(BaseModel):
    value: NoticeCategory
    label: str
