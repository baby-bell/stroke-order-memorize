from dataclasses import dataclass


@dataclass
class SyncMeta:
    synced_at: str
    etag: str | None
    last_modified: str | None


@dataclass
class ResponseMeta:
    etag: str | None
    last_modified: str | None
