# agent-budget-tracker

Per-run budget tracking for tokens, cost, and API calls.

Record spending across named categories and optionally enforce per-category limits. Raises `BudgetExceededError` when a limit is hit, or silently caps if `raise_on_exceed=False`.

## Install

```bash
pip install agent-budget-tracker
```

## Quick start

```python
from agent_budget_tracker import BudgetTracker, BudgetCategory

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
# {'tokens_in': 1200.0, 'tokens_out': 340.0, 'usd_cost': 0.02, 'api_calls': 1.0}
print(tracker.remaining(BudgetCategory.USD_COST))
# 0.98
```

## API

### `BudgetCategory`

Built-in categories: `TOKENS_IN`, `TOKENS_OUT`, `USD_COST`, `API_CALLS`, `CUSTOM`. Pass a plain string for custom metrics.

### `BudgetTracker`

```python
BudgetTracker(
    *,
    limits: dict[BudgetCategory | str, float] | None = None,
    raise_on_exceed: bool = True,
    clock: Callable[[], float] | None = None,
)
```

| Method | Description |
|---|---|
| `record(category, amount, *, description)` | Record spending; raises or caps on limit hit |
| `total(category=None)` | Total recorded (all or one category) |
| `remaining(category)` | Budget left, or `None` if no limit |
| `is_over_budget(category=None)` | True if any limit exceeded |
| `entries(category=None)` | All `BudgetEntry` objects |
| `summary()` | `dict[str, float]` of category totals |
| `limit_for(category)` | Configured limit or `None` |
| `clear()` | Remove all entries (limits preserved) |
| `to_dict()` / `from_dict(data)` | Serialise/restore |

### `BudgetEntry`

| Field | Type | Description |
|---|---|---|
| `category` | `BudgetCategory \| str` | Spending category |
| `amount` | `float` | Amount recorded |
| `description` | `str` | Optional note |
| `created_at` | `float` | Unix timestamp |

## License

MIT
