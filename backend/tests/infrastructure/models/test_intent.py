from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ad_rca.domain.models import SliceKey
from ad_rca.infrastructure.models.deepseek import ModelUnavailableError
from ad_rca.infrastructure.models.intent import (
    DeepSeekIntentParser,
    IntentParseError,
    RuleIntentParser,
)

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class RecordingJsonClient:
    def __init__(self, *responses: str | Exception) -> None:
        self._responses = iter(responses)
        self.requests: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> str:
        self.requests.append((system, user))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _now() -> datetime:
    return NOW


def _valid_intent_json() -> str:
    return (
        '{"start":"2026-09-03T00:00:00+08:00",'
        '"end":"2026-09-04T00:00:00+08:00",'
        '"advertiser_id":null,"offer_id":"12345",'
        '"channel_id":null,"country":null}'
    )


def test_rule_parser_defaults_to_previous_complete_day() -> None:
    intent = RuleIntentParser(now=_now).parse("分析 offer 12345 为什么利润下降")

    assert intent.window.start.isoformat() == "2026-09-03T00:00:00+08:00"
    assert intent.window.end.isoformat() == "2026-09-04T00:00:00+08:00"
    assert intent.scope == SliceKey(offer_id="12345")


def test_rule_parser_supports_channel_country_and_recent_days() -> None:
    intent = RuleIntentParser(now=_now).parse("分析最近3天渠道678在美国的利润")

    assert intent.window.start.isoformat() == "2026-09-01T00:00:00+08:00"
    assert intent.window.end.isoformat() == "2026-09-04T00:00:00+08:00"
    assert intent.scope == SliceKey(channel_id="678", country="US")


def test_rule_parser_supports_advertiser_and_iso_date() -> None:
    intent = RuleIntentParser(now=_now).parse("分析广告主 88 在 2026-09-02 的利润")

    assert intent.window.start.isoformat() == "2026-09-02T00:00:00+08:00"
    assert intent.window.end.isoformat() == "2026-09-03T00:00:00+08:00"
    assert intent.scope == SliceKey(advertiser_id="88")


@pytest.mark.parametrize("question", ("", "最近8天利润", "分析2026-09-10的利润"))
def test_rule_parser_rejects_unsafe_or_unsupported_ranges(question: str) -> None:
    with pytest.raises(IntentParseError):
        RuleIntentParser(now=_now).parse(question)


def test_deepseek_parser_returns_validated_intent_without_sensitive_prompt_data() -> None:
    client = RecordingJsonClient(_valid_intent_json())

    intent = DeepSeekIntentParser(client, now=_now).parse("分析昨天 offer 12345 为什么利润下降")

    assert intent.scope.offer_id == "12345"
    prompt = " ".join(client.requests[0])
    for forbidden in ("SELECT", "au_stat", "ymgw", "MYSQL_", "asyncmy://"):
        assert forbidden not in prompt


def test_deepseek_parser_repairs_invalid_json_once() -> None:
    client = RecordingJsonClient("not-json", _valid_intent_json())

    intent = DeepSeekIntentParser(client, now=_now).parse("分析昨天 offer 12345")

    assert intent.scope.offer_id == "12345"
    assert len(client.requests) == 2
    assert "validation_error" in client.requests[1][1]


def test_deepseek_parser_falls_back_when_model_is_unavailable() -> None:
    client = RecordingJsonClient(ModelUnavailableError("offline"))

    intent = DeepSeekIntentParser(client, now=_now).parse("分析昨天渠道678的利润")

    assert intent.scope.channel_id == "678"


def test_deepseek_parser_rejects_invalid_output_when_rule_fallback_is_ambiguous() -> None:
    client = RecordingJsonClient("{}", "{}")

    with pytest.raises(IntentParseError):
        DeepSeekIntentParser(client, now=_now).parse("帮我看看发生了什么")


def test_parser_accepts_injected_clock_callable() -> None:
    def clock() -> datetime:
        return NOW

    assert RuleIntentParser(now=clock).parse("昨天利润").window.end.day == 4
