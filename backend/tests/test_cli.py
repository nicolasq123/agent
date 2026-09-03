import json
from pathlib import Path

import pytest

from ad_rca.cli import main

ROOT = Path(__file__).parents[2]


def test_cli_emits_evidence_backed_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        ["investigate", str(ROOT / "fixtures/demo/pricing_error.json"), "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["hypotheses"][0]["hypothesis"] == "payout_price_increase"
    assert payload["hypotheses"][0]["confidence"] == "confirmed"
    assert payload["evidence"]


def test_cli_reports_invalid_path_without_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["investigate", "/missing/scenario.json", "--format", "json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "scenario file not found" in captured.err
    assert "Traceback" not in captured.err
