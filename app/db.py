import sqlite3
from datetime import datetime

from fsrs import Card, State

from app.models import SyncMeta

_SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    kanji       TEXT NOT NULL PRIMARY KEY,
    wk_level    INT  NOT NULL CHECK (wk_level BETWEEN 1 AND 60),
    synced_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    kanji       TEXT NOT NULL PRIMARY KEY REFERENCES characters(kanji),
    state       INT  NOT NULL DEFAULT 1 CHECK (state IN (1, 2, 3)),
    step        INT,
    stability   REAL,
    difficulty  REAL,
    due         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    last_review TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER NOT NULL PRIMARY KEY,
    kanji       TEXT    NOT NULL REFERENCES characters(kanji),
    rating      INT     NOT NULL CHECK (rating IN (1, 2, 3, 4)),
    reviewed_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_meta (
    endpoint        TEXT NOT NULL PRIMARY KEY,
    synced_at       TEXT NOT NULL,
    etag            TEXT,
    last_modified   TEXT
);

CREATE TABLE IF NOT EXISTS subject_cache (
    id          INTEGER NOT NULL PRIMARY KEY,
    characters  TEXT NOT NULL,
    level       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str = "stroke-memorize.db") -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_character(self, kanji: str, wk_level: int, synced_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO characters (kanji, wk_level, synced_at)
                VALUES (?, ?, ?)
                ON CONFLICT(kanji) DO UPDATE SET
                    wk_level  = excluded.wk_level,
                    synced_at = excluded.synced_at
                """,
                (kanji, wk_level, synced_at.isoformat()),
            )

    def insert_card_if_new(self, kanji: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO cards (kanji) VALUES (?)",
                (kanji,),
            )

    def get_review_kanji(self, now: datetime) -> list[str]:
        """Return kanji with due <= now that have been reviewed before."""
        rows = self.conn.execute(
            "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NOT NULL",
            (now.isoformat(),),
        ).fetchall()
        return [row["kanji"] for row in rows]

    def get_new_kanji(self, now: datetime) -> list[str]:
        """Return kanji with due <= now that have never been reviewed."""
        rows = self.conn.execute(
            "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL ORDER BY RANDOM()",
            (now.isoformat(),),
        ).fetchall()
        return [row["kanji"] for row in rows]

    def count_review_due(self, now: datetime) -> int:
        """Count review cards due by the given time."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NOT NULL",
            (now.isoformat(),),
        ).fetchone()
        return row[0]

    def count_new_due(self, now: datetime) -> int:
        """Count new cards due by the given time."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NULL",
            (now.isoformat(),),
        ).fetchone()
        return row[0]

    def count_new_introduced_today(self, today_start: datetime) -> int:
        """Count kanji whose first-ever review happened on or after today_start."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT kanji FROM reviews
                GROUP BY kanji
                HAVING MIN(reviewed_at) >= ?
            )
            """,
            (today_start.isoformat(),),
        ).fetchone()
        return row[0]

    def get_card(self, kanji: str) -> Card:
        row = self.conn.execute(
            "SELECT * FROM cards WHERE kanji = ?",
            (kanji,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No card found for kanji: {kanji!r}")
        return Card(
            state=State(row["state"]),
            step=row["step"],
            stability=row["stability"],
            difficulty=row["difficulty"],
            due=datetime.fromisoformat(row["due"]),
            last_review=(
                datetime.fromisoformat(row["last_review"])
                if row["last_review"]
                else None
            ),
        )

    def update_card(self, kanji: str, card: Card) -> None:
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE cards
                SET state = ?, step = ?, stability = ?, difficulty = ?, due = ?, last_review = ?
                WHERE kanji = ?
                """,
                (
                    card.state.value,
                    card.step,
                    card.stability,
                    card.difficulty,
                    card.due.isoformat(),
                    card.last_review.isoformat() if card.last_review else None,
                    kanji,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"No card found for kanji: {kanji!r}")

    def insert_review(self, kanji: str, rating: int, reviewed_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO reviews (kanji, rating, reviewed_at) VALUES (?, ?, ?)",
                (kanji, rating, reviewed_at.isoformat()),
            )

    def get_sync_meta(self, endpoint: str) -> SyncMeta | None:
        row = self.conn.execute(
            "SELECT synced_at, etag, last_modified FROM sync_meta WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
        if row is None:
            return None
        return SyncMeta(
            synced_at=datetime.fromisoformat(row["synced_at"]),
            etag=row["etag"],
            last_modified=row["last_modified"],
        )

    def set_sync_meta(
        self,
        endpoint: str,
        synced_at: datetime,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_meta (endpoint, synced_at, etag, last_modified)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                    synced_at     = excluded.synced_at,
                    etag          = excluded.etag,
                    last_modified = excluded.last_modified
                """,
                (endpoint, synced_at.isoformat(), etag, last_modified),
            )

    def get_stats(self) -> dict:
        """Return aggregate statistics for the stats page."""
        learned = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE last_review IS NOT NULL"
        ).fetchone()[0]
        unlearned = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE last_review IS NULL"
        ).fetchone()[0]
        total_reviews = self.conn.execute(
            "SELECT COUNT(*) FROM reviews"
        ).fetchone()[0]

        # Estimate sessions by grouping reviews with <30 min gaps.
        # A new session starts when reviewed_at is >30 min after the previous review.
        rows = self.conn.execute(
            "SELECT reviewed_at FROM reviews ORDER BY reviewed_at"
        ).fetchall()
        session_count = 0
        session_lengths: list[int] = []  # reviews per session
        if rows:
            session_count = 1
            cur_len = 1
            prev = datetime.fromisoformat(rows[0]["reviewed_at"])
            for row in rows[1:]:
                t = datetime.fromisoformat(row["reviewed_at"])
                if (t - prev).total_seconds() > 1800:
                    session_lengths.append(cur_len)
                    session_count += 1
                    cur_len = 0
                cur_len += 1
                prev = t
            session_lengths.append(cur_len)
        avg_session = (
            round(sum(session_lengths) / len(session_lengths), 1)
            if session_lengths
            else 0
        )

        return {
            "learned": learned,
            "unlearned": unlearned,
            "total_reviews": total_reviews,
            "session_count": session_count,
            "avg_session_reviews": avg_session,
        }

    def get_cached_subjects(self) -> dict[int, tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT id, characters, level FROM subject_cache"
        ).fetchall()
        return {row["id"]: (row["characters"], row["level"]) for row in rows}

    def get_setting(self, key: str, default: str) -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def upsert_cached_subjects(self, subjects: dict[int, tuple[str, int]]) -> None:
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO subject_cache (id, characters, level)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    characters = excluded.characters,
                    level      = excluded.level
                """,
                [(sid, chars, level) for sid, (chars, level) in subjects.items()],
            )
