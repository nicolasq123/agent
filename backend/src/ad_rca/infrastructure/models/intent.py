from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.domain.models import SliceKey, StrictModel, TimeWindow
from ad_rca.infrastructure.models.deepseek import JsonCompletionClient, ModelUnavailableError

_PROFIT_TERMS = ("利润", "亏损", "收入", "支出", "profit", "revenue", "payout")
_COUNTRY_ALIASES = {
    "美国": "US",
    "中国": "CN",
    "印度": "IN",
    "印度尼西亚": "ID",
    "日本": "JP",
    "韩国": "KR",
}
_MAX_WINDOW = timedelta(days=7)


class IntentParseError(ValueError):
    pass


class _IntentDraft(StrictModel):
    start: datetime
    end: datetime
    advertiser_id: str | None = None
    offer_id: str | None = None
    channel_id: str | None = None
    country: str | None = None


class RuleIntentParser:
    def __init__(
        self,
        *,
        timezone: str = "Asia/Shanghai",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._timezone = ZoneInfo(timezone)
        self._now = now or (lambda: datetime.now(self._timezone))

    def parse(self, question: str) -> AnalysisIntent:
        normalized = question.strip()
        if not normalized or not any(term in normalized.lower() for term in _PROFIT_TERMS):
            raise IntentParseError("请输入包含利润、收入或支出的分析问题")
        current = self._localized_now()
        window = self._parse_window(normalized, current)
        _validate_window(window, current)
        return AnalysisIntent(
            question=normalized,
            window=window,
            scope=_parse_scope(normalized),
            timezone=self._timezone.key,
        )

    def _localized_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise IntentParseError("解析时钟必须包含时区")
        return value.astimezone(self._timezone)

    def _parse_window(self, question: str, current: datetime) -> TimeWindow:
        today = datetime.combine(current.date(), time.min, self._timezone)
        iso_dates = tuple(
            date.fromisoformat(item) for item in re.findall(r"\d{4}-\d{2}-\d{2}", question)
        )
        if len(iso_dates) == 1:
            start = datetime.combine(iso_dates[0], time.min, self._timezone)
            return TimeWindow(start=start, end=start + timedelta(days=1))
        if len(iso_dates) == 2:
            start = datetime.combine(iso_dates[0], time.min, self._timezone)
            end = datetime.combine(iso_dates[1], time.min, self._timezone) + timedelta(days=1)
            return TimeWindow(start=start, end=end)
        if len(iso_dates) > 2:
            raise IntentParseError("时间范围包含过多日期")
        recent = re.search(r"最近\s*(\d+)\s*天", question)
        if recent:
            days = int(recent.group(1))
            return TimeWindow(start=today - timedelta(days=days), end=today)
        if "今天" in question:
            end = current.replace(minute=0, second=0, microsecond=0)
            if end <= today:
                end = current
            return TimeWindow(start=today, end=end)
        start = today - timedelta(days=1)
        return TimeWindow(start=start, end=today)


class DeepSeekIntentParser:
    def __init__(
        self,
        client: JsonCompletionClient,
        *,
        timezone: str = "Asia/Shanghai",
        now: Callable[[], datetime] | None = None,
        fallback: RuleIntentParser | None = None,
    ) -> None:
        self._client = client
        self._timezone = ZoneInfo(timezone)
        self._now = now or (lambda: datetime.now(self._timezone))
        self._fallback = fallback or RuleIntentParser(timezone=timezone, now=self._now)

    def parse(self, question: str) -> AnalysisIntent:
        normalized = question.strip()
        if not normalized:
            raise IntentParseError("分析问题不能为空")
        current = self._current_time()
        system = (
            "Convert one profit-analysis question into JSON only. "
            "Allowed concepts are time range, advertiser_id, offer_id, channel_id, and "
            "two-letter country code. Missing time means the previous complete calendar day; "
            "missing scope means the whole platform. The maximum range is seven days. "
            "Do not add fields. Response schema: "
            + json.dumps(_IntentDraft.model_json_schema(), separators=(",", ":"))
        )
        validation_error = ""
        for attempt in range(2):
            user = json.dumps(
                {
                    "question": normalized,
                    "current_time": current.isoformat(),
                    "timezone": self._timezone.key,
                    **(
                        {
                            "validation_error": validation_error,
                            "instruction": "Return corrected JSON only.",
                        }
                        if attempt
                        else {}
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            try:
                draft = _IntentDraft.model_validate_json(self._client.complete_json(system, user))
                window = TimeWindow(start=draft.start, end=draft.end)
                _validate_window(window, current)
                return AnalysisIntent(
                    question=normalized,
                    window=window,
                    scope=SliceKey(
                        advertiser_id=draft.advertiser_id,
                        offer_id=draft.offer_id,
                        channel_id=draft.channel_id,
                        country=draft.country.upper() if draft.country else None,
                    ),
                    timezone=self._timezone.key,
                )
            except ModelUnavailableError:
                break
            except (ValidationError, ValueError) as error:
                validation_error = str(error)[:1000]
        return self._fallback.parse(normalized)

    def _current_time(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            raise IntentParseError("解析时钟必须包含时区")
        return current.astimezone(self._timezone)


def _parse_scope(question: str) -> SliceKey:
    advertiser = _extract_id(
        question,
        r"(?:广告主|advertiser|ader)(?:[_\s-]*id)?\s*[:：#]?\s*(\d+)",
    )
    offer = _extract_id(question, r"(?:offer|oid)(?:[_\s-]*id)?\s*[:：#]?\s*(\d+)")
    channel = _extract_id(question, r"(?:渠道|channel|aid)(?:[_\s-]*id)?\s*[:：#]?\s*(\d+)")
    country = next((code for name, code in _COUNTRY_ALIASES.items() if name in question), None)
    if country is None:
        match = re.search(r"(?:国家|country)\s*[:：#]?\s*([A-Za-z]{2})\b", question)
        country = match.group(1).upper() if match else None
    return SliceKey(
        advertiser_id=advertiser,
        offer_id=offer,
        channel_id=channel,
        country=country,
    )


def _extract_id(question: str, pattern: str) -> str | None:
    match = re.search(pattern, question, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _validate_window(window: TimeWindow, current: datetime) -> None:
    if window.start.tzinfo is None or window.end.tzinfo is None:
        raise IntentParseError("时间范围必须包含时区")
    if window.end > current:
        raise IntentParseError("暂不分析未来时间")
    if window.end - window.start > _MAX_WINDOW:
        raise IntentParseError("单次分析时间范围不能超过七天")
