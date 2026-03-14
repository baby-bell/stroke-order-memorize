from app.core import (
    select_due_cards,
    compute_due_count,
    process_sync_results,
    requeue_position,
    schedule_review,
)


class TestSelectDueCards:
    def test_returns_all_review_cards(self):
        result = select_due_cards(
            review_kanji=["一", "二"],
            new_kanji=["三"],
            new_today_count=0,
            daily_limit=20,
        )
        assert "一" in result
        assert "二" in result

    def test_includes_new_cards_up_to_limit(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二", "三"],
            new_today_count=0,
            daily_limit=2,
        )
        assert len(result) == 2

    def test_subtracts_already_introduced_today(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二", "三"],
            new_today_count=1,
            daily_limit=2,
        )
        assert len(result) == 1

    def test_zero_limit_excludes_all_new(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二"],
            new_today_count=0,
            daily_limit=0,
        )
        assert result == []

    def test_review_cards_always_included_even_with_zero_limit(self):
        result = select_due_cards(
            review_kanji=["一"],
            new_kanji=["二"],
            new_today_count=0,
            daily_limit=0,
        )
        assert result == ["一"]

    def test_limit_higher_than_available(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二"],
            new_today_count=0,
            daily_limit=100,
        )
        assert len(result) == 2

    def test_reviews_before_new_in_output(self):
        result = select_due_cards(
            review_kanji=["一"],
            new_kanji=["二", "三"],
            new_today_count=0,
            daily_limit=20,
        )
        assert result == ["一", "二", "三"]

    def test_today_count_exceeding_limit_clamps_to_zero(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二"],
            new_today_count=5,
            daily_limit=3,
        )
        assert result == []


class TestComputeDueCount:
    def test_basic_counts(self):
        total, new = compute_due_count(
            review_count=3,
            new_available=5,
            new_today_count=0,
            daily_limit=20,
        )
        assert total == 8
        assert new == 5

    def test_caps_new_cards(self):
        total, new = compute_due_count(
            review_count=2,
            new_available=10,
            new_today_count=0,
            daily_limit=3,
        )
        assert total == 5
        assert new == 3

    def test_subtracts_already_introduced(self):
        total, new = compute_due_count(
            review_count=0,
            new_available=5,
            new_today_count=2,
            daily_limit=3,
        )
        assert total == 1
        assert new == 1

    def test_zero_limit(self):
        total, new = compute_due_count(
            review_count=1,
            new_available=5,
            new_today_count=0,
            daily_limit=0,
        )
        assert total == 1
        assert new == 0

    def test_today_count_exceeding_limit(self):
        total, new = compute_due_count(
            review_count=2,
            new_available=5,
            new_today_count=10,
            daily_limit=3,
        )
        assert total == 2
        assert new == 0


class TestProcessSyncResults:
    def test_matches_passed_ids_to_level_map(self):
        level_map = {440: ("一", 1), 441: ("二", 1)}
        result = process_sync_results(
            passed_ids=[440, 441],
            level_map=level_map,
        )
        assert result == [("一", 1), ("二", 1)]

    def test_skips_unknown_subject_ids(self):
        level_map = {440: ("一", 1)}
        result = process_sync_results(
            passed_ids=[440, 999],
            level_map=level_map,
        )
        assert result == [("一", 1)]

    def test_empty_passed_ids(self):
        level_map = {440: ("一", 1)}
        result = process_sync_results(passed_ids=[], level_map=level_map)
        assert result == []

    def test_empty_level_map(self):
        result = process_sync_results(passed_ids=[440], level_map={})
        assert result == []

    def test_duplicate_passed_ids_produces_duplicates(self):
        level_map = {440: ("一", 1)}
        result = process_sync_results(passed_ids=[440, 440], level_map=level_map)
        assert result == [("一", 1), ("一", 1)]


class TestRequeuePosition:
    def test_returns_none_for_good_rating(self):
        assert requeue_position(rating=3, queue_length=5) is None

    def test_returns_none_for_easy_rating(self):
        assert requeue_position(rating=4, queue_length=5) is None

    def test_returns_none_for_hard_rating(self):
        assert requeue_position(rating=2, queue_length=5) is None

    def test_returns_position_for_again_rating(self):
        pos = requeue_position(rating=1, queue_length=5)
        assert pos is not None
        assert 0 <= pos <= 5

    def test_position_within_bounds_small_queue(self):
        pos = requeue_position(rating=1, queue_length=1)
        assert pos is not None
        assert pos >= 0

    def test_position_zero_queue(self):
        """When queue is empty after pop, card goes at position 0 (back in)."""
        pos = requeue_position(rating=1, queue_length=0)
        assert pos == 0


from fsrs import Card, State


class TestScheduleReview:
    def test_returns_updated_card(self):
        card = Card()  # default new card
        updated = schedule_review(card, rating=3)
        assert updated.last_review is not None
        assert updated.stability is not None

    def test_good_rating_sets_future_due(self):
        card = Card()
        updated = schedule_review(card, rating=3)
        assert updated.due > card.due

    def test_again_rating_keeps_learning(self):
        card = Card()
        updated = schedule_review(card, rating=1)
        assert updated.state == State.Learning

    def test_invalid_rating_raises(self):
        import pytest

        card = Card()
        with pytest.raises(ValueError):
            schedule_review(card, rating=0)
