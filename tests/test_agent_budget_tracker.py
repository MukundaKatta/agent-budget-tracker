"""Tests for agent-budget-tracker."""

from __future__ import annotations

import pytest

from agent_budget_tracker import (
    BudgetCategory,
    BudgetEntry,
    BudgetExceededError,
    BudgetTracker,
)

# ---------------------------------------------------------------------------
# BudgetCategory
# ---------------------------------------------------------------------------


def test_category_values():
    assert BudgetCategory.TOKENS_IN.value == "tokens_in"
    assert BudgetCategory.TOKENS_OUT.value == "tokens_out"
    assert BudgetCategory.USD_COST.value == "usd_cost"
    assert BudgetCategory.API_CALLS.value == "api_calls"
    assert BudgetCategory.CUSTOM.value == "custom"


def test_category_is_str():
    assert isinstance(BudgetCategory.TOKENS_IN, str)


# ---------------------------------------------------------------------------
# BudgetExceededError
# ---------------------------------------------------------------------------


def test_budget_exceeded_error_attrs():
    err = BudgetExceededError(
        BudgetCategory.USD_COST, limit=1.0, current=0.9, attempted=0.2
    )
    assert err.category == BudgetCategory.USD_COST
    assert err.limit == 1.0
    assert err.current == 0.9
    assert err.attempted == 0.2


def test_budget_exceeded_error_message():
    err = BudgetExceededError(
        BudgetCategory.USD_COST, limit=1.0, current=0.9, attempted=0.2
    )
    msg = str(err)
    assert "usd_cost" in msg
    assert "1.0" in msg


def test_budget_exceeded_error_string_category():
    err = BudgetExceededError("my_cat", limit=5.0, current=4.0, attempted=2.0)
    assert err.category == "my_cat"
    assert "my_cat" in str(err)


# ---------------------------------------------------------------------------
# BudgetEntry
# ---------------------------------------------------------------------------


def test_entry_minimal():
    e = BudgetEntry(category=BudgetCategory.TOKENS_IN, amount=100.0)
    assert e.category == BudgetCategory.TOKENS_IN
    assert e.amount == 100.0
    assert e.description == ""
    assert e.created_at == 0.0


def test_entry_to_dict():
    e = BudgetEntry(
        category=BudgetCategory.USD_COST,
        amount=0.05,
        description="turn 1",
        created_at=1000.0,
    )
    d = e.to_dict()
    assert d["category"] == "usd_cost"
    assert d["amount"] == 0.05
    assert d["description"] == "turn 1"
    assert d["created_at"] == 1000.0


def test_entry_from_dict_round_trip():
    e = BudgetEntry(
        category=BudgetCategory.API_CALLS,
        amount=3.0,
        description="batch",
        created_at=999.0,
    )
    restored = BudgetEntry.from_dict(e.to_dict())
    assert restored.category == e.category
    assert restored.amount == e.amount
    assert restored.description == e.description
    assert restored.created_at == e.created_at


def test_entry_from_dict_unknown_category():
    d = {"category": "my_custom_cat", "amount": 7.0}
    e = BudgetEntry.from_dict(d)
    assert e.category == "my_custom_cat"
    assert e.amount == 7.0


def test_entry_repr():
    e = BudgetEntry(category=BudgetCategory.TOKENS_OUT, amount=42.0)
    r = repr(e)
    assert "tokens_out" in r
    assert "42.0" in r


# ---------------------------------------------------------------------------
# BudgetTracker — basic recording
# ---------------------------------------------------------------------------


def _make_clock(start: float = 0.0):
    """Returns a deterministic clock that ticks by 1 each call."""
    t = [start]

    def clock() -> float:
        val = t[0]
        t[0] += 1.0
        return val

    return clock


def test_record_returns_entry():
    tracker = BudgetTracker(clock=_make_clock())
    entry = tracker.record(BudgetCategory.TOKENS_IN, 500)
    assert isinstance(entry, BudgetEntry)
    assert entry.amount == 500


def test_record_negative_raises():
    tracker = BudgetTracker()
    with pytest.raises(ValueError):
        tracker.record(BudgetCategory.TOKENS_IN, -1)


def test_record_zero_ok():
    tracker = BudgetTracker()
    entry = tracker.record(BudgetCategory.TOKENS_IN, 0)
    assert entry.amount == 0.0


def test_record_with_description():
    tracker = BudgetTracker()
    entry = tracker.record(BudgetCategory.USD_COST, 0.01, description="turn 1")
    assert entry.description == "turn 1"


def test_record_string_category():
    tracker = BudgetTracker()
    entry = tracker.record("my_metric", 5.0)
    assert entry.amount == 5.0


def test_record_uses_clock():
    tracker = BudgetTracker(clock=_make_clock(100.0))
    e = tracker.record(BudgetCategory.TOKENS_IN, 1)
    assert e.created_at == 100.0


def test_len():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 1)
    tracker.record(BudgetCategory.TOKENS_OUT, 2)
    assert len(tracker) == 2


# ---------------------------------------------------------------------------
# BudgetTracker — total / remaining / is_over_budget
# ---------------------------------------------------------------------------


def test_total_single_category():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 100)
    tracker.record(BudgetCategory.TOKENS_IN, 200)
    assert tracker.total(BudgetCategory.TOKENS_IN) == pytest.approx(300.0)


def test_total_all_categories():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 100)
    tracker.record(BudgetCategory.USD_COST, 0.05)
    assert tracker.total() == pytest.approx(100.05)


def test_total_empty():
    tracker = BudgetTracker()
    assert tracker.total() == 0.0
    assert tracker.total(BudgetCategory.TOKENS_IN) == 0.0


def test_remaining_no_limit():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.USD_COST, 0.50)
    assert tracker.remaining(BudgetCategory.USD_COST) is None


def test_remaining_with_limit():
    tracker = BudgetTracker(limits={BudgetCategory.USD_COST: 1.0})
    tracker.record(BudgetCategory.USD_COST, 0.30)
    assert tracker.remaining(BudgetCategory.USD_COST) == pytest.approx(0.70)


def test_remaining_string_category():
    tracker = BudgetTracker(limits={"my_metric": 10.0})
    tracker.record("my_metric", 4.0)
    assert tracker.remaining("my_metric") == pytest.approx(6.0)


def test_is_over_budget_false():
    tracker = BudgetTracker(limits={BudgetCategory.USD_COST: 1.0})
    tracker.record(BudgetCategory.USD_COST, 0.50)
    assert not tracker.is_over_budget()
    assert not tracker.is_over_budget(BudgetCategory.USD_COST)


def test_is_over_budget_no_limit():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 999_999)
    assert not tracker.is_over_budget()
    assert not tracker.is_over_budget(BudgetCategory.TOKENS_IN)


# ---------------------------------------------------------------------------
# BudgetTracker — limit enforcement
# ---------------------------------------------------------------------------


def test_limit_raises_on_exceed():
    tracker = BudgetTracker(limits={BudgetCategory.USD_COST: 1.0})
    tracker.record(BudgetCategory.USD_COST, 0.80)
    with pytest.raises(BudgetExceededError) as exc_info:
        tracker.record(BudgetCategory.USD_COST, 0.30)
    err = exc_info.value
    assert err.limit == pytest.approx(1.0)
    assert err.current == pytest.approx(0.80)
    assert err.attempted == pytest.approx(0.30)


def test_limit_exact_boundary_allowed():
    tracker = BudgetTracker(limits={BudgetCategory.API_CALLS: 5.0})
    for _ in range(5):
        tracker.record(BudgetCategory.API_CALLS, 1.0)
    assert tracker.total(BudgetCategory.API_CALLS) == pytest.approx(5.0)


def test_limit_cap_mode():
    tracker = BudgetTracker(
        limits={BudgetCategory.TOKENS_IN: 100.0}, raise_on_exceed=False
    )
    tracker.record(BudgetCategory.TOKENS_IN, 80.0)
    entry = tracker.record(BudgetCategory.TOKENS_IN, 50.0)
    # Capped to 20 remaining
    assert entry.amount == pytest.approx(20.0)
    assert tracker.total(BudgetCategory.TOKENS_IN) == pytest.approx(100.0)


def test_limit_cap_mode_already_at_limit():
    tracker = BudgetTracker(
        limits={BudgetCategory.TOKENS_IN: 50.0}, raise_on_exceed=False
    )
    tracker.record(BudgetCategory.TOKENS_IN, 50.0)
    entry = tracker.record(BudgetCategory.TOKENS_IN, 10.0)
    assert entry.amount == pytest.approx(0.0)


def test_limit_for():
    tracker = BudgetTracker(limits={BudgetCategory.USD_COST: 2.50})
    assert tracker.limit_for(BudgetCategory.USD_COST) == pytest.approx(2.50)
    assert tracker.limit_for(BudgetCategory.TOKENS_IN) is None


# ---------------------------------------------------------------------------
# BudgetTracker — entries / summary
# ---------------------------------------------------------------------------


def test_entries_all():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 10)
    tracker.record(BudgetCategory.TOKENS_OUT, 5)
    all_entries = tracker.entries()
    assert len(all_entries) == 2


def test_entries_filtered():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 10)
    tracker.record(BudgetCategory.TOKENS_OUT, 5)
    tracker.record(BudgetCategory.TOKENS_IN, 20)
    in_entries = tracker.entries(BudgetCategory.TOKENS_IN)
    assert len(in_entries) == 2
    assert all(e.category == BudgetCategory.TOKENS_IN for e in in_entries)


def test_summary():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 100)
    tracker.record(BudgetCategory.TOKENS_OUT, 50)
    tracker.record(BudgetCategory.USD_COST, 0.02)
    tracker.record(BudgetCategory.TOKENS_IN, 200)
    s = tracker.summary()
    assert s["tokens_in"] == pytest.approx(300.0)
    assert s["tokens_out"] == pytest.approx(50.0)
    assert s["usd_cost"] == pytest.approx(0.02)


def test_summary_empty():
    tracker = BudgetTracker()
    assert tracker.summary() == {}


# ---------------------------------------------------------------------------
# BudgetTracker — clear / reset
# ---------------------------------------------------------------------------


def test_clear_removes_entries():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 100)
    tracker.clear()
    assert len(tracker) == 0
    assert tracker.total() == 0.0


def test_clear_preserves_limits():
    tracker = BudgetTracker(limits={BudgetCategory.USD_COST: 1.0})
    tracker.record(BudgetCategory.USD_COST, 0.80)
    tracker.clear()
    assert tracker.limit_for(BudgetCategory.USD_COST) == pytest.approx(1.0)
    # Can record again up to the limit
    tracker.record(BudgetCategory.USD_COST, 0.90)
    assert tracker.total(BudgetCategory.USD_COST) == pytest.approx(0.90)


# ---------------------------------------------------------------------------
# BudgetTracker — serialisation round-trip
# ---------------------------------------------------------------------------


def test_to_dict_from_dict_round_trip():
    tracker = BudgetTracker(
        limits={BudgetCategory.USD_COST: 5.0, BudgetCategory.API_CALLS: 100.0},
        raise_on_exceed=False,
        clock=_make_clock(),
    )
    tracker.record(BudgetCategory.USD_COST, 0.25, description="turn 1")
    tracker.record(BudgetCategory.API_CALLS, 1.0)

    d = tracker.to_dict()
    restored = BudgetTracker.from_dict(d, clock=_make_clock())

    assert restored.total(BudgetCategory.USD_COST) == pytest.approx(0.25)
    assert restored.total(BudgetCategory.API_CALLS) == pytest.approx(1.0)
    assert restored.limit_for(BudgetCategory.USD_COST) == pytest.approx(5.0)
    assert len(restored) == 2


def test_from_dict_preserves_raise_on_exceed():
    tracker = BudgetTracker(
        limits={BudgetCategory.TOKENS_IN: 10.0}, raise_on_exceed=False
    )
    restored = BudgetTracker.from_dict(tracker.to_dict())
    # Should cap, not raise
    restored.record(BudgetCategory.TOKENS_IN, 100.0)
    assert restored.total(BudgetCategory.TOKENS_IN) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# BudgetTracker — repr
# ---------------------------------------------------------------------------


def test_repr():
    tracker = BudgetTracker()
    tracker.record(BudgetCategory.TOKENS_IN, 42)
    r = repr(tracker)
    assert "BudgetTracker" in r
    assert "entries=1" in r
