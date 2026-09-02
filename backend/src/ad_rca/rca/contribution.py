from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from pydantic import Field

from ad_rca.domain.models import AttributionResult, PerformanceRow, SliceKey, StrictModel

ALLOWED_DIMENSIONS = frozenset({"advertiser_id", "offer_id", "channel_id", "country"})
DIMENSION_PREFERENCE = {
    "advertiser_id": 0,
    "country": 1,
    "channel_id": 2,
    "offer_id": 3,
}


class AttributionSummary(StrictModel):
    total_loss: float = Field(ge=0)
    explained_loss: float = Field(ge=0)
    residual_loss: float = Field(ge=0)
    paths: tuple[AttributionResult, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    result: AttributionResult
    members: frozenset[tuple[str, str, str, str]]
    preference: int


def attribute_loss(
    actual: Sequence[PerformanceRow],
    expected: Sequence[PerformanceRow],
    dimensions: Sequence[str],
    *,
    max_depth: int = 3,
    min_share: float = 0.10,
) -> AttributionSummary:
    if not dimensions or not set(dimensions) <= ALLOWED_DIMENSIONS:
        raise ValueError("dimensions must be a non-empty subset of the allowlist")
    if not 1 <= max_depth <= 3:
        raise ValueError("max_depth must be between 1 and 3")
    if not 0 <= min_share <= 1:
        raise ValueError("min_share must be between 0 and 1")

    actual_profit = _profit_by_leaf(actual)
    expected_profit = _profit_by_leaf(expected)
    leaves = frozenset(actual_profit) | frozenset(expected_profit)
    leaf_losses = {
        leaf: max(expected_profit.get(leaf, 0.0) - actual_profit.get(leaf, 0.0), 0.0)
        for leaf in leaves
    }
    total_loss = sum(leaf_losses.values())
    if total_loss <= 0:
        return AttributionSummary(total_loss=0.0, explained_loss=0.0, residual_loss=0.0)

    candidates: list[_Candidate] = []
    dimension_tuple = tuple(dimensions)
    for depth in range(1, min(max_depth, len(dimension_tuple)) + 1):
        for selected in combinations(dimension_tuple, depth):
            grouped: dict[tuple[str, ...], set[tuple[str, str, str, str]]] = defaultdict(set)
            for leaf in leaves:
                grouped[tuple(_leaf_value(leaf, name) for name in selected)].add(leaf)
            for values, members in grouped.items():
                loss = sum(leaf_losses[member] for member in members)
                share = loss / total_loss
                if loss <= 0 or share < min_share:
                    continue
                key = SliceKey.model_validate(dict(zip(selected, values, strict=True)))
                candidates.append(
                    _Candidate(
                        result=AttributionResult(
                            slice_key=key,
                            actual_profit=sum(actual_profit.get(member, 0.0) for member in members),
                            expected_profit=sum(
                                expected_profit.get(member, 0.0) for member in members
                            ),
                            lost_profit=loss,
                            share=share,
                        ),
                        members=frozenset(members),
                        preference=sum(DIMENSION_PREFERENCE[name] for name in selected),
                    )
                )

    candidates.sort(
        key=lambda item: (
            -item.result.slice_key.depth,
            -item.result.lost_profit,
            -item.preference,
            item.result.slice_key.dimensions(),
        )
    )
    claimed: set[tuple[str, str, str, str]] = set()
    paths: list[AttributionResult] = []
    for candidate in candidates:
        if candidate.members & claimed:
            continue
        paths.append(candidate.result)
        claimed.update(candidate.members)

    paths.sort(key=lambda item: item.lost_profit, reverse=True)
    explained_loss = sum(path.lost_profit for path in paths)
    return AttributionSummary(
        total_loss=total_loss,
        explained_loss=explained_loss,
        residual_loss=max(total_loss - explained_loss, 0.0),
        paths=tuple(paths),
    )


def _profit_by_leaf(rows: Sequence[PerformanceRow]) -> dict[tuple[str, str, str, str], float]:
    profits: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for row in rows:
        leaf = (row.advertiser_id, row.offer_id, row.channel_id, row.country)
        profits[leaf] += row.revenue - row.payout
    return dict(profits)


def _leaf_value(leaf: tuple[str, str, str, str], dimension: str) -> str:
    indexes = {"advertiser_id": 0, "offer_id": 1, "channel_id": 2, "country": 3}
    return leaf[indexes[dimension]]
