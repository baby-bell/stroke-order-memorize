from app.core import select_due_cards


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
