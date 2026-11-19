from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BrowserFrame(BaseModel):
    captured_at: datetime
    page_url: str = Field(max_length=4096)
    media_type: Literal["image/jpeg", "image/png"]
    source: Literal["live", "checkpoint"] = "live"
    image_base64: str = Field(max_length=1_400_000, repr=False)


class BrowserPreview(BaseModel):
    job_id: str
    status: str
    frame: BrowserFrame | None = None
