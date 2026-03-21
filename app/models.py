from dataclasses import dataclass


@dataclass(frozen=True)
class SyncMeta:
    synced_at: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class ResponseMeta:
    etag: str | None
    last_modified: str | None
