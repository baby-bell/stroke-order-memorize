from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SyncMeta:
    """Schema for entries in `sync_meta` table."""
    synced_at: datetime
    etag: str | None
    """ETag returned from Wanikani endpoint."""
    last_modified: str | None


@dataclass(frozen=True)
class ResponseMeta:
    etag: str | None
    last_modified: str | None
