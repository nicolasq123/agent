from datetime import UTC, datetime
from pathlib import Path

import pytest

from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.domain.models import SliceKey, TimeWindow

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "minimal_scenario.json"
WINDOW = TimeWindow(
    start=datetime(2026, 9, 2, 10, tzinfo=UTC),
    end=datetime(2026, 9, 2, 11, tzinfo=UTC),
)


@pytest.fixture
def repository() -> FixtureRepository:
    return FixtureRepository.load(FIXTURE_PATH)


def test_loads_validated_scenario_metadata(repository: FixtureRepository) -> None:
    assert repository.scenario_id == "minimal"
    assert repository.name == "Minimal readonly fixture"


def test_performance_filters_time_and_known_dimensions(repository: FixtureRepository) -> None:
    rows = repository.performance(WINDOW, SliceKey(offer_id="offer-a"))

    assert len(rows) == 1
    assert rows[0].offer_id == "offer-a"
    assert rows[0].channel_id == "channel-c"


def test_performance_returns_immutable_tuple(repository: FixtureRepository) -> None:
    rows = repository.performance(WINDOW, SliceKey())

    assert isinstance(rows, tuple)
    assert len(rows) == 2


def test_auxiliary_sources_filter_relevant_time_and_slice(repository: FixtureRepository) -> None:
    key = SliceKey(offer_id="offer-a", channel_id="channel-c")

    assert len(repository.conversion_events(WINDOW, key)) == 1
    assert len(repository.postback_events(WINDOW, key)) == 1
    assert len(repository.quality_events(WINDOW, key)) == 1
    assert len(repository.cap_observations(WINDOW, key)) == 1


def test_queries_do_not_change_fixture_bytes(repository: FixtureRepository) -> None:
    before = FIXTURE_PATH.read_bytes()

    repository.performance(WINDOW, SliceKey(country="US"))
    repository.pricing_changes(WINDOW, SliceKey(offer_id="offer-a"))

    assert FIXTURE_PATH.read_bytes() == before
