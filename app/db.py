import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fsrs import Card, State

_conn: Optional[sqlite3.Connection] = None

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
"""


def init(path: str = "stroke-memorize.db") -> None:
    global _conn
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.executescript(_SCHEMA)
    _conn.commit()


def upsert_character(kanji: str, wk_level: int, synced_at: str) -> None:
    _conn.execute(
        """
        INSERT INTO characters (kanji, wk_level, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(kanji) DO UPDATE SET
            wk_level  = excluded.wk_level,
            synced_at = excluded.synced_at
        """,
        (kanji, wk_level, synced_at),
    )
    _conn.commit()


def insert_card_if_new(kanji: str) -> None:
    _conn.execute(
        "INSERT OR IGNORE INTO cards (kanji) VALUES (?)",
        (kanji,),
    )
    _conn.commit()


def get_due_kanji() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ?",
        (now,),
    ).fetchall()
    return [row["kanji"] for row in rows]


def due_count() -> int:
    now = datetime.now(timezone.utc).isoformat()
    row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ?",
        (now,),
    ).fetchone()
    return row[0]


def get_card(kanji: str) -> Card:
    row = _conn.execute(
        "SELECT * FROM cards WHERE kanji = ?",
        (kanji,),
    ).fetchone()
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


def update_card(kanji: str, card: Card) -> None:
    _conn.execute(
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
    _conn.commit()


def insert_review(kanji: str, rating: int, reviewed_at: str) -> None:
    _conn.execute(
        "INSERT INTO reviews (kanji, rating, reviewed_at) VALUES (?, ?, ?)",
        (kanji, rating, reviewed_at),
    )
    _conn.commit()
