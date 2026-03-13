from __future__ import annotations

from typing import Any

from .catalog_data import BROKERS, CAPABILITY_META, FILTERS, STATUS_META

BrokerDict = dict[str, Any]

BROKER_DETAILS: list[BrokerDict] = BROKERS
BROKER_MAP: dict[str, BrokerDict] = {broker["id"]: broker for broker in BROKER_DETAILS}

BROKER_CATALOG: list[BrokerDict] = [
    {
        "id": broker["id"],
        "name": broker["name"],
        "status": broker["status"],
        "required_fields": [field["key"] for field in broker.get("fields", []) if field.get("required")],
        "optional_fields": [field["key"] for field in broker.get("fields", []) if not field.get("required")],
    }
    for broker in BROKER_DETAILS
]


def normalize_filter(filter_id: str | None) -> str:
    allowed_filters = {item["id"] for item in FILTERS}
    if filter_id in allowed_filters:
        return filter_id
    return "all"


def get_visible_brokers(filter_id: str | None) -> list[BrokerDict]:
    normalized = normalize_filter(filter_id)
    if normalized == "all":
        return BROKER_DETAILS
    return [broker for broker in BROKER_DETAILS if broker["status"] == normalized]


def get_broker_or_none(broker_id: str | None) -> BrokerDict | None:
    if not broker_id:
        return None
    return BROKER_MAP.get(broker_id)


def get_selected_broker(filter_id: str | None, broker_id: str | None) -> BrokerDict | None:
    visible = get_visible_brokers(filter_id)
    if not visible:
        return None

    selected = get_broker_or_none(broker_id)
    if selected and selected in visible:
        return selected
    return visible[0]


def build_summary_counts() -> dict[str, int]:
    counts = {"total": len(BROKER_DETAILS), "ready": 0, "partner": 0, "limited": 0, "unavailable": 0}
    for broker in BROKER_DETAILS:
        counts[broker["status"]] += 1
    return counts


def list_accepted_fields(broker: BrokerDict) -> list[str]:
    return [field["key"] for field in broker.get("fields", [])]


def list_required_fields(broker: BrokerDict) -> list[str]:
    return [field["key"] for field in broker.get("fields", []) if field.get("required")]


def list_optional_fields(broker: BrokerDict) -> list[str]:
    return [field["key"] for field in broker.get("fields", []) if not field.get("required")]


def summarize_broker(broker: BrokerDict) -> BrokerDict:
    return {
        "id": broker["id"],
        "name": broker["name"],
        "status": broker["status"],
        "required_fields": list_required_fields(broker),
        "optional_fields": list_optional_fields(broker),
    }


def validate_broker_values(broker: BrokerDict, values: dict[str, Any]) -> dict[str, Any]:
    accepted_fields = list_accepted_fields(broker)
    if broker["status"] != "ready":
        return {
            "broker_id": broker["id"],
            "status": broker["status"],
            "is_supported": False,
            "missing_fields": [],
            "accepted_fields": accepted_fields,
            "warnings": [
                "현재 상태에서는 self-service 입력형 연동을 열지 않는 것이 안전합니다.",
                f"broker_status={broker['status']}",
            ],
        }

    missing_fields: list[str] = []
    for field_name in list_required_fields(broker):
        raw_value = values.get(field_name)
        if raw_value is None:
            missing_fields.append(field_name)
            continue
        if isinstance(raw_value, str) and not raw_value.strip():
            missing_fields.append(field_name)

    warnings: list[str] = []
    extra_fields = sorted(set(values.keys()) - set(accepted_fields))
    if extra_fields:
        warnings.append(f"unused_fields={','.join(extra_fields)}")

    if values.get("appKey") or values.get("appSecret"):
        warnings.append("toy_project_only_do_not_store_plaintext_secrets_in_production")

    return {
        "broker_id": broker["id"],
        "status": broker["status"],
        "is_supported": True,
        "missing_fields": missing_fields,
        "accepted_fields": accepted_fields,
        "warnings": warnings,
    }
