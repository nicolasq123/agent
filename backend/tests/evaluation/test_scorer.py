from pathlib import Path

from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.evaluation.scorer import GroundTruth, score_result

ROOT = Path(__file__).parents[3]


def test_scorer_accepts_grounded_pricing_result() -> None:
    repository = FixtureRepository.load(ROOT / "fixtures/demo/pricing_error.json")
    result = CoreRcaService(repository, default_verifiers()).investigate("pricing_error")
    truth = GroundTruth.model_validate_json(
        (ROOT / "fixtures/ground_truth/pricing_error.json").read_bytes()
    )

    score = score_result(result, truth)

    assert score.passed is True
    assert score.incident_match is True
    assert score.root_cause_top1 is True
    assert score.evidence_coverage == 1.0


def test_scorer_rejects_confidence_above_ground_truth_ceiling() -> None:
    repository = FixtureRepository.load(ROOT / "fixtures/demo/traffic_quality.json")
    result = CoreRcaService(repository, default_verifiers()).investigate("traffic_quality")
    truth = GroundTruth.model_validate_json(
        (ROOT / "fixtures/ground_truth/traffic_quality.json").read_bytes()
    )
    overstated = result.model_copy(
        update={
            "hypotheses": (result.hypotheses[0].model_copy(update={"confidence": "confirmed"}),)
        }
    )

    assert score_result(overstated, truth).passed is False
