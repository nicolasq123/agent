import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, Protocol

import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from ad_rca.agent.models import QuestionAnswer
from ad_rca.api.app import create_app
from ad_rca.api.dependencies import build_natural_language_service, build_service
from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.application.natural_language_service import (
    AnalysisDataQualityError,
    NaturalLanguageAnalysis,
)
from ad_rca.application.scope_discovery import (
    InsufficientComparableHistoryError,
    NoAnalyzableDataError,
    NoCurrentDataError,
)
from ad_rca.config import Settings
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.infrastructure.database.mysql import QueryApprovalRejected
from ad_rca.infrastructure.database.query_budget import QueryBudgetExceeded
from ad_rca.infrastructure.models.deepseek import (
    JsonCompletionClient,
    ModelUnavailableError,
    OpenAIJsonClient,
)
from ad_rca.infrastructure.models.intent import IntentParseError
from ad_rca.presentation.markdown import render_analysis_markdown


class ModelClientFactory(Protocol):
    def __call__(self, settings: Settings) -> JsonCompletionClient: ...


class ServerRunner(Protocol):
    def __call__(self, app: FastAPI, host: str, port: int) -> None: ...


class NaturalService(Protocol):
    async def ask(
        self,
        question: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> NaturalLanguageAnalysis: ...

    def answer(self, analysis: NaturalLanguageAnalysis, question: str) -> QuestionAnswer: ...

    async def check_database(self) -> None: ...


class NaturalServiceFactory(Protocol):
    def __call__(self, settings: Settings) -> NaturalService: ...


def main(
    argv: Sequence[str] | None = None,
    *,
    model_client_factory: ModelClientFactory | None = None,
    server_runner: ServerRunner | None = None,
    natural_service_factory: NaturalServiceFactory | None = None,
    line_reader: Callable[[str], str] | None = None,
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
        if args.command == "ask":
            return _ask(
                args.question,
                args.json,
                natural_service_factory or build_natural_language_service,
            )
        if args.command == "chat":
            return _chat(
                natural_service_factory or build_natural_language_service,
                line_reader or input,
            )
        if args.command == "db-check":
            return _db_check(natural_service_factory or build_natural_language_service)
    except (
        ValidationError,
        ValueError,
        RuntimeError,
        OSError,
        SQLAlchemyError,
        ModelUnavailableError,
    ) as error:
        print(f"profitlens command failed: {safe_error_message(error)}", file=sys.stderr)
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

    ask = subparsers.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true")

    subparsers.add_parser("chat")
    subparsers.add_parser("db-check")
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
        data_mode="fixture",
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
    settings = Settings(
        data_mode="fixture",
        fixture_dir=fixture_dir,
        artifacts_dir=artifacts_dir,
    )
    runner(create_app(build_service(settings)), host, port)
    return 0


def _ask(
    question: str,
    as_json: bool,
    factory: NaturalServiceFactory,
) -> int:
    analysis = asyncio.run(factory(Settings()).ask(question))
    if as_json:
        payload = {
            "intent": analysis.intent.model_dump(mode="json"),
            "selected_scope": analysis.selected_scope.model_dump(mode="json"),
            "run": analysis.run.model_dump(mode="json"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_analysis_markdown(analysis))
    return 0


def _chat(factory: NaturalServiceFactory, line_reader: Callable[[str], str]) -> int:
    service = factory(Settings())
    try:
        return asyncio.run(_chat_loop(service, line_reader))
    except (EOFError, KeyboardInterrupt):
        print("\n已退出 ProfitLens。")
        return 0


async def _chat_loop(
    service: NaturalService,
    line_reader: Callable[[str], str],
) -> int:
    print("ProfitLens 对话模式。输入 /new 开始新分析，/exit 退出。")
    analysis: NaturalLanguageAnalysis | None = None
    while True:
        line = line_reader("profitlens> ").strip()
        if not line:
            continue
        if line == "/exit":
            return 0
        if line == "/new":
            analysis = None
            print("已清除当前分析，请输入新问题。")
            continue
        if analysis is None:
            analysis = await service.ask(
                line,
                progress=lambda message: print(f"[分析] {message}", flush=True),
            )
            print(render_analysis_markdown(analysis))
        else:
            answer = service.answer(analysis, line)
            print(answer.answer)
            if answer.evidence_ids:
                print(f"Evidence IDs：{', '.join(answer.evidence_ids)}")


def _db_check(factory: NaturalServiceFactory) -> int:
    asyncio.run(factory(Settings()).check_database())
    print("DB20 au_stat: ok")
    print("DB40 ymgw: ok")
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


def safe_error_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        fields = sorted({str(item["loc"][0]) for item in error.errors() if item["loc"]})
        return f"[VALIDATION_ERROR] 输入或配置校验失败（字段：{', '.join(fields)}）"
    if isinstance(error, IntentParseError):
        return f"[INTENT_PARSE_ERROR] 无法理解分析条件：{error}"
    if isinstance(error, NoCurrentDataError):
        return "[DATA_NO_CURRENT] 查询时间范围内没有利润数据"
    if isinstance(error, InsufficientComparableHistoryError):
        return "[DATA_HISTORY_INSUFFICIENT] 当前数据存在，但不足四个历史同期样本"
    if isinstance(error, NoAnalyzableDataError):
        return "[DATA_NOT_ANALYZABLE] 没有可供分析的数据范围"
    if isinstance(error, AnalysisDataQualityError):
        return "[DATA_QUALITY_BLOCKED] 数据完整度低于 95%、点击量不足或同期样本不足"
    if isinstance(error, QueryApprovalRejected):
        return "[QUERY_REJECTED] 只读 SQL 未获人工批准"
    if isinstance(error, QueryBudgetExceeded):
        return "[QUERY_BUDGET_EXCEEDED] 本次分析查询数量超过安全上限"
    if isinstance(error, TimeoutError):
        return "[DB_TIMEOUT] 数据库只读查询超时"
    if isinstance(error, ConnectionError):
        return "[DB_CONNECTION_FAILED] 无法连接数据库"
    if isinstance(error, SQLAlchemyError):
        return _database_error_message(error)
    if isinstance(error, ModelUnavailableError):
        return "[MODEL_UNAVAILABLE] 模型服务暂时不可用"
    return str(error)


def _database_error_message(error: SQLAlchemyError) -> str:
    code: int | None = None
    if isinstance(error, DBAPIError) and error.orig is not None:
        arguments = error.orig.args
        if arguments and isinstance(arguments[0], int):
            code = arguments[0]
    messages = {
        1044: "[DB_PERMISSION_DENIED] 只读账号无权访问目标数据库",
        1045: "[DB_AUTH_FAILED] MySQL 用户名或密码错误",
        1049: "[DB_DATABASE_MISSING] 配置的数据库不存在",
        1054: "[DB_COLUMN_MISSING] SQL 使用的字段与生产表结构不一致",
        1146: "[DB_TABLE_MISSING] SQL 使用的表不存在",
        1227: "[DB_PERMISSION_DENIED] 只读账号权限不足",
        2003: "[DB_CONNECTION_FAILED] 无法连接 MySQL 地址或端口",
        2005: "[DB_HOST_UNKNOWN] 无法解析 MySQL 主机名",
        2013: "[DB_CONNECTION_LOST] 查询期间 MySQL 连接中断",
    }
    if code is None:
        return "[DB_QUERY_FAILED] 数据库只读查询失败"
    return messages.get(code, "[DB_QUERY_FAILED] 数据库只读查询失败")


if __name__ == "__main__":
    raise SystemExit(main())
