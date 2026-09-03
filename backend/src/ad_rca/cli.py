import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError

from ad_rca.api.app import create_app
from ad_rca.api.dependencies import build_service
from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.config import Settings
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.infrastructure.models.deepseek import (
    JsonCompletionClient,
    ModelUnavailableError,
    OpenAIJsonClient,
)


class ModelClientFactory(Protocol):
    def __call__(self, settings: Settings) -> JsonCompletionClient: ...


class ServerRunner(Protocol):
    def __call__(self, app: FastAPI, host: str, port: int) -> None: ...


def main(
    argv: Sequence[str] | None = None,
    *,
    model_client_factory: ModelClientFactory | None = None,
    server_runner: ServerRunner | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "investigate":
            return _investigate(args.fixture)
        if args.command == "agent":
            return _agent(args.fixture, args.model, args.artifacts_dir)
        if args.command == "model-check":
            return _model_check(model_client_factory or _default_model_client)
        if args.command == "serve":
            return _serve(
                args.fixture_dir,
                args.artifacts_dir,
                args.host,
                args.port,
                server_runner or _default_server_runner,
            )
    except (ValidationError, ValueError, OSError, ModelUnavailableError) as error:
        print(f"profitlens command failed: {_safe_error(error)}", file=sys.stderr)
        return 2
    parser.error("unsupported command")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="profitlens")
    subparsers = parser.add_subparsers(dest="command", required=True)

    investigate = subparsers.add_parser("investigate")
    investigate.add_argument("fixture", type=Path)
    investigate.add_argument("--format", choices=("json",), default="json")

    agent = subparsers.add_parser("agent")
    agent.add_argument("fixture", type=Path)
    agent.add_argument("--model", choices=("fake", "deepseek"), default="fake")
    agent.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    agent.add_argument("--format", choices=("json",), default="json")

    subparsers.add_parser("model-check")

    serve = subparsers.add_parser("serve")
    serve.add_argument("--fixture-dir", type=Path, default=Path("../fixtures/demo"))
    serve.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def _investigate(fixture: Path) -> int:
    if not fixture.is_file():
        print(f"scenario file not found: {fixture}", file=sys.stderr)
        return 2
    repository = FixtureRepository.load(fixture)
    result = CoreRcaService(repository, default_verifiers()).investigate(repository.scenario_id)
    print(result.model_dump_json(indent=2))
    return 0


def _agent(
    fixture: Path,
    model: Literal["fake", "deepseek"],
    artifacts_dir: Path,
) -> int:
    if not fixture.is_file():
        print(f"scenario file not found: {fixture}", file=sys.stderr)
        return 2
    settings = Settings(
        fixture_dir=fixture.parent,
        artifacts_dir=artifacts_dir,
        model_mode=model,
    )
    repository = FixtureRepository.load(fixture)
    prepared = CoreRcaService(repository, default_verifiers()).prepare(repository.scenario_id)
    if prepared.incident is None:
        print("scenario did not produce an incident", file=sys.stderr)
        return 2
    run = build_service(settings).start_investigation(prepared.incident.incident_id)
    print(run.model_dump_json(indent=2))
    return 0


def _model_check(factory: ModelClientFactory) -> int:
    settings = Settings()
    if settings.deepseek_api_key is None:
        print("profitlens command failed: DEEPSEEK_API_KEY is not configured", file=sys.stderr)
        return 2
    client = factory(settings)
    raw = client.complete_json(
        "Return JSON only. Do not request or reveal credentials.",
        'Return exactly {"status":"ok"}.',
    )
    payload = json.loads(raw)
    if payload.get("status") != "ok":
        print("profitlens command failed: model health response was invalid", file=sys.stderr)
        return 2
    print(json.dumps({"model": settings.deepseek_model, "status": "ok"}))
    return 0


def _serve(
    fixture_dir: Path,
    artifacts_dir: Path,
    host: str,
    port: int,
    runner: ServerRunner,
) -> int:
    settings = Settings(fixture_dir=fixture_dir, artifacts_dir=artifacts_dir)
    runner(create_app(build_service(settings)), host, port)
    return 0


def _default_model_client(settings: Settings) -> JsonCompletionClient:
    if settings.deepseek_api_key is None:
        raise ValueError("DEEPSEEK_API_KEY is not configured")
    return OpenAIJsonClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.model_timeout_seconds,
    )


def _default_server_runner(app: FastAPI, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port)


def _safe_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        fields = sorted({str(item["loc"][0]) for item in error.errors() if item["loc"]})
        return f"invalid configuration fields: {', '.join(fields)}"
    return str(error)


if __name__ == "__main__":
    raise SystemExit(main())
