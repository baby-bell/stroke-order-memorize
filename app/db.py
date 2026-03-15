import sqlite3
from datetime import datetime

from fsrs import Card, State

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

    def upsert_character(self, kanji: str, wk_level: int, synced_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO characters (kanji, wk_level, synced_at)
            VALUES (?, ?, ?)
            ON CONFLICT(kanji) DO UPDATE SET
                wk_level  = excluded.wk_level,
                synced_at = excluded.synced_at
            """,
            (kanji, wk_level, synced_at),
        )
        self.conn.commit()

    def insert_card_if_new(self, kanji: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO cards (kanji) VALUES (?)",
            (kanji,),
        )
        self.conn.commit()

    def get_review_kanji(self, now: str) -> list[str]:
        """Return kanji with due <= now that have been reviewed before."""
        rows = self.conn.execute(
            "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NOT NULL",
            (now,),
        ).fetchall()
        return [row["kanji"] for row in rows]

    def get_new_kanji(self, now: str) -> list[str]:
        """Return kanji with due <= now that have never been reviewed."""
        rows = self.conn.execute(
            "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL ORDER BY RANDOM()",
            (now,),
        ).fetchall()
        return [row["kanji"] for row in rows]

    def count_review_due(self, now: str) -> int:
        """Count review cards due by the given time."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NOT NULL",
            (now,),
        ).fetchone()
        return row[0]

    def count_new_due(self, now: str) -> int:
        """Count new cards due by the given time."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NULL",
            (now,),
        ).fetchone()
        return row[0]

    def count_new_introduced_today(self, today_start: str) -> int:
        """Count kanji whose first-ever review happened on or after today_start."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT kanji FROM reviews
                GROUP BY kanji
                HAVING MIN(reviewed_at) >= ?
            )
            """,
            (today_start,),
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
                datetime.fromisoformat(row["last_review"]) if row["last_review"] else None
            ),
        )

    def update_card(self, kanji: str, card: Card) -> None:
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
        self.conn.commit()

    def insert_review(self, kanji: str, rating: int, reviewed_at: str) -> None:
        self.conn.execute(
            "INSERT INTO reviews (kanji, rating, reviewed_at) VALUES (?, ?, ?)",
            (kanji, rating, reviewed_at),
        )
        self.conn.commit()

    def get_sync_meta(self, endpoint: str) -> dict | None:
        row = self.conn.execute(
            "SELECT synced_at, etag, last_modified FROM sync_meta WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
        if row is None:
            return None
        return {
            "synced_at": row["synced_at"],
            "etag": row["etag"],
            "last_modified": row["last_modified"],
        }

    def set_sync_meta(
        self,
        endpoint: str,
        synced_at: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_meta (endpoint, synced_at, etag, last_modified)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                synced_at     = excluded.synced_at,
                etag          = excluded.etag,
                last_modified = excluded.last_modified
            """,
            (endpoint, synced_at, etag, last_modified),
        )
        self.conn.commit()

    def get_cached_subjects(self) -> dict[int, tuple[str, int]]:
        rows = self.conn.execute("SELECT id, characters, level FROM subject_cache").fetchall()
        return {row["id"]: (row["characters"], row["level"]) for row in rows}

    def upsert_cached_subjects(self, subjects: dict[int, tuple[str, int]]) -> None:
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
        self.conn.commit()
