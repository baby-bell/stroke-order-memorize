import pytest
from datetime import datetime, timezone
from fsrs import Card, State
import app.db as db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSchema:
    def test_tables_created(self):
        cursor = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor}
        assert tables == {"characters", "cards", "reviews", "sync_meta", "subject_cache"}


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
        assert row[0] == 1       # State.Learning
        assert row[1] is None    # stability NULL
        assert row[2] is None    # difficulty NULL

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


class TestGetDueKanji:
    def test_returns_due_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        # New cards are due immediately (due DEFAULT = now)
        due = db.get_due_kanji()
        assert "一" in due

    def test_excludes_future_cards(self):
        db.upsert_character("二", 1, now_iso())
        db.insert_card_if_new("二")
        db._conn.execute(
            "UPDATE cards SET due = '2099-01-01T00:00:00+00:00' WHERE kanji = '二'"
        )
        db._conn.commit()
        due = db.get_due_kanji()
        assert "二" not in due


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


class TestDueCount:
    def test_returns_count_of_due_cards(self):
        for kanji in ["一", "二"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        total, new = db.due_count()
        assert total == 2
        assert new == 2


class TestNewCardLimit:
    def test_new_cards_limited_to_daily_max(self):
        db.set_new_cards_per_day(2)
        for kanji in ["一", "二", "三", "四", "五"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        due = db.get_due_kanji()
        assert len(due) == 2

    def test_review_cards_always_included(self):
        db.set_new_cards_per_day(0)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        # Simulate a reviewed card: set last_review so it's not "new"
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        due = db.get_due_kanji()
        assert "一" in due

    def test_zero_limit_excludes_all_new_cards(self):
        db.set_new_cards_per_day(0)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        due = db.get_due_kanji()
        assert due == []

    def test_introduced_today_counts_toward_limit(self):
        db.set_new_cards_per_day(2)
        for kanji in ["一", "二", "三"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        # Simulate reviewing "一" today (its first-ever review)
        db.insert_review("一", 3, now_iso())
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        # "一" was introduced today, so only 1 new slot remains
        due = db.get_due_kanji()
        new_in_due = [k for k in due if k != "一"]
        assert len(new_in_due) == 1

    def test_limit_higher_than_available_new_cards(self):
        db.set_new_cards_per_day(100)
        for kanji in ["一", "二"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        due = db.get_due_kanji()
        assert len(due) == 2


class TestDueCountWithLimit:
    def test_returns_tuple_of_total_and_new(self):
        db.set_new_cards_per_day(20)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        result = db.due_count()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_counts_respect_new_card_limit(self):
        db.set_new_cards_per_day(1)
        for kanji in ["一", "二", "三"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        total, new = db.due_count()
        assert total == 1
        assert new == 1

    def test_counts_include_review_cards(self):
        db.set_new_cards_per_day(0)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        total, new = db.due_count()
        assert total == 1
        assert new == 0


class TestSyncMeta:
    def test_get_sync_meta_returns_none_when_absent(self):
        assert db.get_sync_meta("subjects") is None

    def test_set_and_get_sync_meta(self):
        db.set_sync_meta("subjects", "2024-01-01T00:00:00+00:00", etag='"abc"', last_modified="Wed, 01 Jan 2025 00:00:00 GMT")
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


class TestSubjectCache:
    def test_has_cached_subjects_false_when_empty(self):
        assert db.has_cached_subjects() is False

    def test_upsert_and_get_cached_subjects(self):
        subjects = {440: ("一", 1), 441: ("二", 1), 500: ("山", 3)}
        db.upsert_cached_subjects(subjects)
        result = db.get_cached_subjects()
        assert result == subjects

    def test_has_cached_subjects_true_after_upsert(self):
        db.upsert_cached_subjects({440: ("一", 1)})
        assert db.has_cached_subjects() is True

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
