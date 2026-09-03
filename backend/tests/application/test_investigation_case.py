from pathlib import Path

import pytest

from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.domain.enums import Confidence, HypothesisType


def _service() -> CoreRcaService:
    repository = FixtureRepository.load(Path("../fixtures/demo/pricing_error.json"))
    return CoreRcaService(repository, default_verifiers())


def test_prepare_exposes_candidates_without_running_verifiers() -> None:
    prepared = _service().prepare("pricing_error")

    assert prepared.incident is not None
    assert prepared.context is not None
    assert prepared.context.incident == prepared.incident
    assert prepared.candidates[0] is HypothesisType.PAYOUT_PRICE_INCREASE
    assert prepared.hypotheses == ()


def test_verify_runs_only_selected_offered_candidates() -> None:
    service = _service()
    prepared = service.prepare("pricing_error")

    result = service.verify(prepared, (HypothesisType.PAYOUT_PRICE_INCREASE,))

    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].confidence is Confidence.CONFIRMED


@pytest.mark.parametrize(
    "selected",
    [
        (HypothesisType.CAP_REACHED,),
        (
            HypothesisType.PAYOUT_PRICE_INCREASE,
            HypothesisType.PAYOUT_PRICE_INCREASE,
        ),
    ],
)
def test_verify_rejects_unoffered_or_duplicate_candidates(
    selected: tuple[HypothesisType, ...],
) -> None:
    service = _service()
    prepared = service.prepare("pricing_error")

    with pytest.raises(ValueError, match="candidate"):
        service.verify(prepared, selected)
