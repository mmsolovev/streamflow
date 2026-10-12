"""Auth/user DTOs."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: Optional[str] = None
    display_name: Optional[str] = None
    is_streamer: bool = False
    is_admin: bool = False