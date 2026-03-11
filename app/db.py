import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fsrs import Card, State

_conn: Optional[sqlite3.Connection] = None
_new_cards_per_day: int = 20


def set_new_cards_per_day(n: int) -> None:
    global _new_cards_per_day
    if not isinstance(n, int) or n < 0:
        raise ValueError(f"NEW_CARDS_PER_DAY must be a non-negative integer, got {n!r}")
    _new_cards_per_day = n

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


def _new_introduced_today() -> int:
    """Count kanji whose first-ever review happened today (UTC)."""
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    row = _conn.execute(
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


def get_due_kanji() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    # Review cards: always included
    review_rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NOT NULL",
        (now,),
    ).fetchall()
    review_kanji = [row["kanji"] for row in review_rows]

    # New cards: limited by daily cap
    remaining_slots = max(0, _new_cards_per_day - _new_introduced_today())
    new_rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL LIMIT ?",
        (now, remaining_slots),
    ).fetchall()
    new_kanji = [row["kanji"] for row in new_rows]

    return review_kanji + new_kanji


def due_count() -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    review_row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NOT NULL",
        (now,),
    ).fetchone()
    review_count = review_row[0]

    remaining_slots = max(0, _new_cards_per_day - _new_introduced_today())
    new_row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NULL",
        (now,),
    ).fetchone()
    new_count = min(new_row[0], remaining_slots)

    return (review_count + new_count, new_count)


def get_card(kanji: str) -> Card:
    row = _conn.execute(
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


def update_card(kanji: str, card: Card) -> None:
    cursor = _conn.execute(
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
    _conn.commit()


def insert_review(kanji: str, rating: int, reviewed_at: str) -> None:
    _conn.execute(
        "INSERT INTO reviews (kanji, rating, reviewed_at) VALUES (?, ?, ?)",
        (kanji, rating, reviewed_at),
    )
    _conn.commit()
