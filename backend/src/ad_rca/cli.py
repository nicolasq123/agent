import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.data.fixture_repository import FixtureRepository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="profitlens")
    subparsers = parser.add_subparsers(dest="command", required=True)
    investigate = subparsers.add_parser("investigate")
    investigate.add_argument("fixture", type=Path)
    investigate.add_argument("--format", choices=("json",), default="json")
    args = parser.parse_args(argv)
    fixture: Path = args.fixture
    if not fixture.is_file():
        print(f"scenario file not found: {fixture}", file=sys.stderr)
        return 2
    try:
        repository = FixtureRepository.load(fixture)
        result = CoreRcaService(repository, default_verifiers()).investigate(repository.scenario_id)
    except (ValueError, OSError) as error:
        print(f"unable to investigate scenario: {error}", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
