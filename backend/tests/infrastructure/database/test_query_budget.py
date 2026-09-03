import pytest

from ad_rca.infrastructure.database.query_budget import QueryBudget, QueryBudgetExceeded


def test_query_budget_rejects_twenty_first_query_before_execution() -> None:
    budget = QueryBudget(max_queries=20)

    for _ in range(20):
        budget.consume()

    with pytest.raises(QueryBudgetExceeded, match="20"):
        budget.consume()
    assert budget.used == 20


def test_query_budget_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError):
        QueryBudget(max_queries=0)
