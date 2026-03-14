import pytest
from datetime import datetime, timezone
from fsrs import Card, State
import app.db as db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSchema:
    def test_tables_created(self):
        cursor = db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor}
        assert tables == {
            "characters",
            "cards",
            "reviews",
            "sync_meta",
            "subject_cache",
        }


class TestUpsertCharacter:
    def test_inserts_new_character(self):
        db.upsert_character("一", 1, now_iso())
        row = db._conn.execute(
            "SELECT kanji, wk_level FROM characters WHERE kanji = '一'"
        ).fetchone()
        assert tuple(row) == ("一", 1)

    def test_updates_existing_character(self):
        ts1 = "2024-01-01T00:00:00+00:00"
        ts2 = "2025-01-01T00:00:00+00:00"
        db.upsert_character("一", 1, ts1)
        db.upsert_character("一", 1, ts2)
        row = db._conn.execute(
            "SELECT synced_at FROM characters WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == ts2

    def test_rejects_invalid_level(self):
        with pytest.raises(Exception):
            db.upsert_character("一", 61, now_iso())


class TestInsertCardIfNew:
    def test_inserts_card_for_new_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        row = db._conn.execute(
            "SELECT state, stability, difficulty FROM cards WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == 1  # State.Learning
        assert row[1] is None  # stability NULL
        assert row[2] is None  # difficulty NULL

    def test_does_not_overwrite_existing_card(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute("UPDATE cards SET stability = 9.5 WHERE kanji = '一'")
        db._conn.commit()
        db.insert_card_if_new("一")  # must not overwrite
        row = db._conn.execute(
            "SELECT stability FROM cards WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == 9.5


class TestGetReviewKanji:
    def test_returns_reviewed_due_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        assert "一" in db.get_review_kanji(now)

    def test_excludes_new_cards(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        now = datetime.now(timezone.utc).isoformat()
        assert db.get_review_kanji(now) == []


class TestGetNewKanji:
    def test_returns_new_due_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        now = datetime.now(timezone.utc).isoformat()
        assert "一" in db.get_new_kanji(now)

    def test_excludes_future_cards(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute(
            "UPDATE cards SET due = '2099-01-01T00:00:00+00:00' WHERE kanji = '一'"
        )
        db._conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        assert db.get_new_kanji(now) == []


class TestCountNewIntroducedToday:
    def test_counts_first_reviews_today(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_review("一", 3, now_iso())
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        assert db.count_new_introduced_today(today_start) == 1

    def test_ignores_old_reviews(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_review("一", 3, "2020-01-01T00:00:00+00:00")
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        assert db.count_new_introduced_today(today_start) == 0


class TestGetCard:
    def test_returns_fsrs_card(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        card = db.get_card("一")
        assert isinstance(card, Card)
        assert card.state == State.Learning
        assert card.stability is None
        assert card.difficulty is None
        assert card.last_review is None


class TestUpdateCard:
    def test_persists_updated_card(self):
        from fsrs import Scheduler, Rating

        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        card = db.get_card("一")
        scheduler = Scheduler()
        updated_card, _ = scheduler.review_card(card, Rating.Good)
        db.update_card("一", updated_card)
        reloaded = db.get_card("一")
        assert reloaded.stability == updated_card.stability
        assert reloaded.state == updated_card.state


class TestInsertReview:
    def test_inserts_review_row(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_review("一", 3, now_iso())
        row = db._conn.execute(
            "SELECT kanji, rating FROM reviews WHERE kanji = '一'"
        ).fetchone()
        assert tuple(row) == ("一", 3)

    def test_rejects_invalid_rating(self):
        db.upsert_character("一", 1, now_iso())
        with pytest.raises(Exception):
            db.insert_review("一", 5, now_iso())


class TestSyncMeta:
    def test_get_sync_meta_returns_none_when_absent(self):
        assert db.get_sync_meta("subjects") is None

    def test_set_and_get_sync_meta(self):
        db.set_sync_meta(
            "subjects",
            "2024-01-01T00:00:00+00:00",
            etag='"abc"',
            last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
        )
        meta = db.get_sync_meta("subjects")
        assert meta is not None
        assert meta["synced_at"] == "2024-01-01T00:00:00+00:00"
        assert meta["etag"] == '"abc"'
        assert meta["last_modified"] == "Wed, 01 Jan 2025 00:00:00 GMT"

    def test_set_sync_meta_without_etag(self):
        db.set_sync_meta("assignments", "2024-06-01T00:00:00+00:00")
        meta = db.get_sync_meta("assignments")
        assert meta is not None
        assert meta["etag"] is None
        assert meta["last_modified"] is None

    def test_set_sync_meta_overwrites_existing(self):
        db.set_sync_meta("subjects", "2024-01-01T00:00:00+00:00", etag='"old"')
        db.set_sync_meta("subjects", "2025-01-01T00:00:00+00:00", etag='"new"')
        meta = db.get_sync_meta("subjects")
        assert meta["synced_at"] == "2025-01-01T00:00:00+00:00"
        assert meta["etag"] == '"new"'

    def test_different_endpoints_stored_independently(self):
        db.set_sync_meta("subjects", "2024-01-01T00:00:00+00:00", etag='"s1"')
        db.set_sync_meta("assignments", "2024-06-01T00:00:00+00:00", etag='"a1"')
        assert db.get_sync_meta("subjects")["etag"] == '"s1"'
        assert db.get_sync_meta("assignments")["etag"] == '"a1"'


class TestGetNewKanjiOrder:
    def test_new_kanji_not_always_in_insertion_order(self):
        """New kanji should be returned in random order, not insertion order."""
        now = datetime.now(timezone.utc).isoformat()
        kanji_list = [chr(0x4E00 + i) for i in range(20)]  # 20 kanji
        for k in kanji_list:
            db.upsert_character(k, 1, now)
            db.insert_card_if_new(k)

        # Run 5 times — if order is random, at least one should differ
        results = [tuple(db.get_new_kanji(now)) for _ in range(5)]
        assert len(set(results)) > 1, "get_new_kanji returned identical order every time"


class TestSubjectCache:
    def test_upsert_and_get_cached_subjects(self):
        subjects = {440: ("一", 1), 441: ("二", 1), 500: ("山", 3)}
        db.upsert_cached_subjects(subjects)
        result = db.get_cached_subjects()
        assert result == subjects

    def test_upsert_updates_existing_subjects(self):
        db.upsert_cached_subjects({440: ("一", 1)})
        db.upsert_cached_subjects({440: ("一", 2)})  # level changed
        result = db.get_cached_subjects()
        assert result[440] == ("一", 2)

    def test_upsert_merges_with_existing(self):
        db.upsert_cached_subjects({440: ("一", 1)})
        db.upsert_cached_subjects({441: ("二", 1)})
        result = db.get_cached_subjects()
        assert 440 in result and 441 in result
