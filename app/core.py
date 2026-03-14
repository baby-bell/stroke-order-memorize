"""Functional core — pure business logic with no I/O."""

import random

from fsrs import Card, Rating, Scheduler


def select_due_cards(
    review_kanji: list[str],
    new_kanji: list[str],
    new_today_count: int,
    daily_limit: int,
) -> list[str]:
    """Select which cards to study: all review cards + new cards up to daily cap."""
    remaining_slots = max(0, daily_limit - new_today_count)
    return review_kanji + new_kanji[:remaining_slots]


def compute_due_count(
    review_count: int,
    new_available: int,
    new_today_count: int,
    daily_limit: int,
) -> tuple[int, int]:
    """Compute (total_due, new_due) given raw counts and daily cap."""
    remaining_slots = max(0, daily_limit - new_today_count)
    new_count = min(new_available, remaining_slots)
    return (review_count + new_count, new_count)


def process_sync_results(
    passed_ids: list[int],
    level_map: dict[int, tuple[str, int]],
) -> list[tuple[str, int]]:
    """Filter passed assignment IDs against the subject level map.

    Returns [(kanji, level), ...] for IDs found in level_map.
    """
    return [level_map[sid] for sid in passed_ids if sid in level_map]


def requeue_position(rating: int, queue_length: int) -> int | None:
    """Return the index to re-insert a card at, or None if no requeue needed.

    Only "Again" (rating=1) triggers a requeue. The card is placed
    a few positions ahead so it's not immediate but comes back soon.
    """
    if rating != 1:
        return None
    if queue_length <= 1:
        return 0
    # Place 2-4 cards from front, capped at queue length
    offset = min(random.randint(2, 4), queue_length)
    return offset


def schedule_review(card: Card, rating: int) -> Card:
    """Apply an FSRS review and return the updated card.

    rating must be 1-4 (Again, Hard, Good, Easy). Raises ValueError otherwise.
    """
    updated_card, _ = Scheduler().review_card(card, Rating(rating))
    return updated_card
