"""HTTP transport for the existing fixed, read-only MySQL query executor."""

# pyright: reportUnknownMemberType=false
import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import cast

import httpx
import sqlglot
from pydantic import SecretStr
from sqlglot import expressions as exp

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TIME_COLUMNS = frozenset({"event_hour", "ut", "create_at", "expire_at", "event_time"})


class HttpQueryError(RuntimeError):
    pass


def render_query(query: str, parameters: Mapping[str, object]) -> str:
    """Bind AST values; hex text is independent of MySQL backslash escaping modes."""
    expression = sqlglot.parse_one(query, read="mysql")
    placeholders = tuple(expression.find_all(exp.Placeholder))
    if {node.name for node in placeholders} != set(parameters):
        raise ValueError("HTTP query parameters do not match placeholders")
    for node in placeholders:
        value = parameters[node.name]
        if value is None:
            replacement = exp.Null()
        elif isinstance(value, datetime):
            if value.tzinfo is not None:
                raise ValueError("HTTP SQL dates must already use database timezone")
            replacement = exp.Literal.string(value.isoformat(sep=" "))
        elif isinstance(value, str):
            encoded = value.encode("utf-8").hex()
            replacement = sqlglot.parse_one(f"CONVERT(X'{encoded}' USING utf8mb4)", read="mysql")
        elif isinstance(value, int) and not isinstance(value, bool):
            replacement = exp.Literal.number(value)
        else:
            raise ValueError("unsupported HTTP query parameter type")
        node.replace(replacement)
    return expression.sql(dialect="mysql")


class HttpQueryClient:
    def __init__(
        self,
        url: str,
        token: SecretStr,
        database: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._token = token
        self._database = database
        self._transport = transport

    async def fetch_all(
        self,
        query: str,
        parameters: Mapping[str, object],
        timeout_seconds: float,
    ) -> Sequence[Mapping[str, object]]:
        sql = render_query(query, parameters)
        try:
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    async with client.stream(
                        "POST",
                        self._url,
                        headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                        json={"db": self._database, "sql": sql},
                    ) as response:
                        if not 200 <= response.status_code < 300:
                            raise HttpQueryError(
                                f"[HTTP_QUERY_STATUS] 查询接口返回 HTTP {response.status_code}"
                            )
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_RESPONSE_BYTES:
                                raise HttpQueryError("[HTTP_QUERY_TOO_LARGE] 查询响应超过 8 MiB")
        except (TimeoutError, httpx.TimeoutException) as error:
            raise HttpQueryError("[HTTP_QUERY_TIMEOUT] HTTP 查询超时") from error
        except httpx.RequestError as error:
            raise HttpQueryError("[HTTP_QUERY_CONNECTION] 无法连接 HTTP 查询服务") from error
        return decode_rows(bytes(content))


def decode_rows(content: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        payload = cast(object, json.loads(content, parse_float=Decimal))
    except (ValueError, UnicodeDecodeError) as error:
        raise HttpQueryError("[HTTP_QUERY_FORMAT] 响应不是有效 JSON") from error
    if not isinstance(payload, dict):
        raise HttpQueryError("[HTTP_QUERY_FORMAT] 预期包含 rows 数组的对象")
    data = cast(dict[str, object], payload)
    if data.get("error") or data.get("success") is False:
        raise HttpQueryError("[HTTP_QUERY_REMOTE_ERROR] 查询服务报告执行失败")
    if data.get("truncated") or data.get("has_more") or data.get("next_cursor"):
        raise HttpQueryError("[HTTP_QUERY_INCOMPLETE] 查询服务返回了不完整结果")
    raw_rows = data.get("rows")
    if not isinstance(raw_rows, list) or len(cast(list[object], raw_rows)) > 10000:
        raise HttpQueryError("[HTTP_QUERY_FORMAT] rows 必须是至多 10000 行的数组")
    rows: list[Mapping[str, object]] = []
    for raw in cast(list[object], raw_rows):
        if not isinstance(raw, dict):
            raise HttpQueryError("[HTTP_QUERY_FORMAT] 每行必须是列名到值的对象")
        row = cast(dict[str, object], raw).copy()
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                raise HttpQueryError("[HTTP_QUERY_FORMAT] 列值不能是嵌套对象")
            if key in _TIME_COLUMNS and isinstance(value, str):
                try:
                    row[key] = datetime.fromisoformat(value)
                except ValueError as error:
                    raise HttpQueryError(f"[HTTP_QUERY_DATETIME] 无效时间字段：{key}") from error
        rows.append(row)
    return tuple(rows)
