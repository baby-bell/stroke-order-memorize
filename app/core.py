"""Functional core — pure business logic with no I/O."""


def select_due_cards(
    review_kanji: list[str],
    new_kanji: list[str],
    new_today_count: int,
    daily_limit: int,
) -> list[str]:
    """Select which cards to study: all review cards + new cards up to daily cap."""
    remaining_slots = max(0, daily_limit - new_today_count)
    return review_kanji + new_kanji[:remaining_slots]
