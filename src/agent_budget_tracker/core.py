"""Per-run budget tracking for tokens, cost, and API calls.

:class:`BudgetTracker` records spending across named categories and
optionally enforces per-category limits.  Call :meth:`~BudgetTracker.record`
after each LLM call, tool invocation, or cost event.

Example::

    tracker = BudgetTracker(
        limits={
            BudgetCategory.TOKENS_IN:  50_000,
            BudgetCategory.USD_COST:   1.00,
            BudgetCategory.API_CALLS:  20,
        }
    )

    tracker.record(BudgetCategory.TOKENS_IN, 1200, description="turn 1 prompt")
    tracker.record(BudgetCategory.TOKENS_OUT, 340,  description="turn 1 reply")
    tracker.record(BudgetCategory.USD_COST,   0.02, description="turn 1 cost")
    tracker.record(BudgetCategory.API_CALLS,  1)

    print(tracker.summary())
    # {'tokens_in': 1200, 'tokens_out': 340, 'usd_cost': 0.02, 'api_calls': 1}
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class BudgetCategory(str, Enum):
    """Category of a budget entry."""

    TOKENS_IN = "tokens_in"
    TOKENS_OUT = "tokens_out"
    USD_COST = "usd_cost"
    API_CALLS = "api_calls"
    CUSTOM = "custom"


class BudgetExceededError(RuntimeError):
    """Raised when recording would exceed a budget limit.

    Attributes:
        category:   The exceeded category.
        limit:      The configured limit.
        current:    The total *before* the new entry.
        attempted:  The amount that was attempted to be recorded.
    """

    def __init__(
        self,
        category: BudgetCategory | str,
        *,
        limit: float,
        current: float,
        attempted: float,
    ) -> None:
        self.category = category
        self.limit = limit
        self.current = current
        self.attempted = attempted
        name = category.value if isinstance(category, BudgetCategory) else category
        super().__init__(
            f"Budget for {name!r} exceeded:"
            f" limit={limit}, current={current}, attempted={attempted}."
        )


@dataclass
class BudgetEntry:
    """A single recorded spending event.

    Attributes:
        category:    Spending category.
        amount:      How much was spent.
        description: Optional human-readable note.
        created_at:  Unix timestamp of recording.
    """

    category: BudgetCategory | str
    amount: float
    description: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        cat = (
            self.category.value
            if isinstance(self.category, BudgetCategory)
            else self.category
        )
        return {
            "category": cat,
            "amount": self.amount,
            "description": self.description,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetEntry:
        """Reconstruct a :class:`BudgetEntry` from a plain dict."""
        raw_cat = data.get("category", BudgetCategory.CUSTOM.value)
        try:
            cat: BudgetCategory | str = BudgetCategory(raw_cat)
        except ValueError:
            cat = raw_cat
        return cls(
            category=cat,
            amount=float(data["amount"]),
            description=data.get("description", ""),
            created_at=float(data.get("created_at", 0.0)),
        )

    def __repr__(self) -> str:
        cat = (
            self.category.value
            if isinstance(self.category, BudgetCategory)
            else self.category
        )
        return f"BudgetEntry(category={cat!r}, amount={self.amount})"


class BudgetTracker:
    """Track per-run spending across categories with optional limits.

    Args:
        limits: Optional dict mapping category → maximum allowed total.
            Attempting to record past the limit raises
            :class:`BudgetExceededError`.
        raise_on_exceed: If ``False`` (default ``True``), silently cap
            instead of raising when a limit is hit.
        clock: Callable returning current Unix time.

    Example::

        tracker = BudgetTracker(limits={BudgetCategory.USD_COST: 0.50})
        tracker.record(BudgetCategory.USD_COST, 0.10)
        assert tracker.total(BudgetCategory.USD_COST) == pytest.approx(0.10)
    """

    def __init__(
        self,
        *,
        limits: dict[BudgetCategory | str, float] | None = None,
        raise_on_exceed: bool = True,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._limits: dict[str, float] = {}
        if limits:
            for k, v in limits.items():
                key = k.value if isinstance(k, BudgetCategory) else k
                self._limits[key] = float(v)
        self._raise_on_exceed = raise_on_exceed
        self._entries: list[BudgetEntry] = []
        self._clock: Callable[[], float] = clock if clock is not None else time.time

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        category: BudgetCategory | str,
        amount: float,
        *,
        description: str = "",
    ) -> BudgetEntry:
        """Record a spending event.

        Args:
            category:    Spending category.
            amount:      How much was spent (must be non-negative).
            description: Optional human-readable note.

        Returns:
            The new :class:`BudgetEntry`.

        Raises:
            ValueError: If *amount* is negative.
            BudgetExceededError: If this would exceed the configured limit
                and *raise_on_exceed* is ``True``.
        """
        if amount < 0:
            raise ValueError(f"amount must be non-negative, got {amount!r}.")
        cat_key = category.value if isinstance(category, BudgetCategory) else category
        limit = self._limits.get(cat_key)
        if limit is not None:
            current = self._total_by_key(cat_key)
            if current + amount > limit:
                if self._raise_on_exceed:
                    raise BudgetExceededError(
                        category,
                        limit=limit,
                        current=current,
                        attempted=amount,
                    )
                # Cap: only record up to the limit
                amount = max(0.0, limit - current)
        entry = BudgetEntry(
            category=category,
            amount=amount,
            description=description,
            created_at=self._clock(),
        )
        self._entries.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def total(self, category: BudgetCategory | str | None = None) -> float:
        """Total amount recorded, optionally filtered by *category*."""
        if category is None:
            return sum(e.amount for e in self._entries)
        key = category.value if isinstance(category, BudgetCategory) else category
        return self._total_by_key(key)

    def remaining(self, category: BudgetCategory | str) -> float | None:
        """Remaining budget for *category*, or ``None`` if no limit set.

        Returns a negative value if spending has exceeded the limit.
        """
        key = category.value if isinstance(category, BudgetCategory) else category
        limit = self._limits.get(key)
        if limit is None:
            return None
        return limit - self._total_by_key(key)

    def is_over_budget(self, category: BudgetCategory | str | None = None) -> bool:
        """Return ``True`` if any limit is exceeded.

        If *category* is given, check only that category.
        """
        if category is not None:
            key = category.value if isinstance(category, BudgetCategory) else category
            limit = self._limits.get(key)
            if limit is None:
                return False
            return self._total_by_key(key) > limit
        # Check all categories
        return any(self._total_by_key(k) > v for k, v in self._limits.items())

    def entries(
        self, category: BudgetCategory | str | None = None
    ) -> list[BudgetEntry]:
        """All entries in insertion order, optionally filtered by *category*."""
        if category is None:
            return list(self._entries)
        key = category.value if isinstance(category, BudgetCategory) else category
        return [
            e
            for e in self._entries
            if (
                e.category.value
                if isinstance(e.category, BudgetCategory)
                else e.category
            )
            == key
        ]

    def summary(self) -> dict[str, float]:
        """Return a dict of category → total across all recorded entries."""
        result: dict[str, float] = {}
        for entry in self._entries:
            key = (
                entry.category.value
                if isinstance(entry.category, BudgetCategory)
                else entry.category
            )
            result[key] = result.get(key, 0.0) + entry.amount
        return result

    def limit_for(self, category: BudgetCategory | str) -> float | None:
        """Return the configured limit for *category*, or ``None``."""
        key = category.value if isinstance(category, BudgetCategory) else category
        return self._limits.get(key)

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Serialisation / reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all entries (limits are preserved)."""
        self._entries.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialise the tracker to a plain dict."""
        return {
            "limits": dict(self._limits),
            "raise_on_exceed": self._raise_on_exceed,
            "entries": [e.to_dict() for e in self._entries],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        clock: Callable[[], float] | None = None,
    ) -> BudgetTracker:
        """Reconstruct a :class:`BudgetTracker` from a plain dict."""
        tracker = cls(
            limits={k: float(v) for k, v in data.get("limits", {}).items()},
            raise_on_exceed=bool(data.get("raise_on_exceed", True)),
            clock=clock,
        )
        for d in data.get("entries", []):
            entry = BudgetEntry.from_dict(d)
            tracker._entries.append(entry)
        return tracker

    def __repr__(self) -> str:
        s = self.summary()
        return f"BudgetTracker(entries={len(self._entries)}, summary={s!r})"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _total_by_key(self, key: str) -> float:
        return sum(
            e.amount
            for e in self._entries
            if (
                e.category.value
                if isinstance(e.category, BudgetCategory)
                else e.category
            )
            == key
        )
