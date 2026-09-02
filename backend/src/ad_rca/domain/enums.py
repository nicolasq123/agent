from enum import StrEnum


class IncidentType(StrEnum):
    PROFIT_DROP = "profit_drop"
    NEGATIVE_PROFIT = "negative_profit"


class HypothesisType(StrEnum):
    PAYOUT_PRICE_INCREASE = "payout_price_increase"
    REVENUE_PRICE_DECREASE = "revenue_price_decrease"
    TRAFFIC_VOLUME_DROP = "traffic_volume_drop"
    TRAFFIC_MIX_SHIFT = "traffic_mix_shift"
    CONVERSION_PATH_FAILURE = "conversion_path_failure"
    CAP_REACHED = "cap_reached"
    TRAFFIC_QUALITY_DEGRADATION = "traffic_quality_degradation"


class HypothesisStatus(StrEnum):
    SUPPORTED = "supported"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceStrength(StrEnum):
    DIRECT = "direct"
    CORROBORATING = "corroborating"
    INDIRECT = "indirect"


class RunStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DATA_QUALITY_BLOCKED = "data_quality_blocked"
    FAILED = "failed"
