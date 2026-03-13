#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import mimetypes
import os
from copy import deepcopy
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from backend.app.catalog import (
    BROKER_CATALOG,
    BROKER_DETAILS,
    CAPABILITY_META,
    STATUS_META,
    get_broker_or_none,
    validate_broker_values,
)


ROOT = Path(__file__).resolve().parent
COOKIE_NAME = "stock_broker_wizard_v2"
BUILD_DATE = "2026-03-13"
READY_BROKERS = [broker for broker in BROKER_DETAILS if broker["status"] == "ready"]
MODAL_KEYS = {"broker", "symbol", "pattern", "ai"}

AUTH_PROVIDERS = [
    {"value": "google", "label": "Google", "subtitle": "Google 계정으로 시작", "className": "auth-google", "email": "gmail.com"},
    {"value": "kakao", "label": "Kakao", "subtitle": "카카오로 빠르게 시작", "className": "auth-kakao", "email": "kakao.com"},
    {"value": "naver", "label": "Naver", "subtitle": "네이버 계정으로 연결", "className": "auth-naver", "email": "naver.com"},
    {"value": "facebook", "label": "Facebook", "subtitle": "Facebook 계정으로 계속", "className": "auth-facebook", "email": "facebook.com"},
]

PATTERN_OPTIONS = [
    {
        "value": "scheduled",
        "label": "정액 적립식",
        "description": "정해진 시간마다 같은 금액으로 반복 매수하거나 일부 매도합니다.",
    },
    {
        "value": "dip-buy",
        "label": "N% 하락 분할매수",
        "description": "기준 가격 대비 하락 폭이 커질 때마다 나눠서 진입합니다.",
    },
    {
        "value": "breakout",
        "label": "전고점 돌파",
        "description": "돌파 구간에서 진입하고 목표 수익 구간에서 분할 매도합니다.",
    },
    {
        "value": "golden-cross",
        "label": "이동평균 골든크로스",
        "description": "단기선과 장기선의 교차를 기준으로 자동 매매합니다.",
    },
    {
        "value": "rsi",
        "label": "RSI 과매도/과매수",
        "description": "정해진 RSI 값 기준으로 반응하는 정량 룰입니다.",
    },
]

SCHEDULE_OPTIONS = [
    {"value": "market-open", "label": "장 시작 직후"},
    {"value": "every-15m", "label": "15분마다"},
    {"value": "every-30m", "label": "30분마다"},
    {"value": "every-1h", "label": "1시간마다"},
    {"value": "daily", "label": "하루 1회"},
    {"value": "weekly", "label": "주 1회"},
]

AI_PROVIDERS = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "google", "label": "Google"},
    {"value": "openrouter", "label": "OpenRouter"},
    {"value": "custom", "label": "직접 입력"},
]

FLASH_MESSAGES = {
    "logged_in": {"kind": "success", "text": "로그인 세션을 시작했습니다."},
    "logged_out": {"kind": "success", "text": "로그아웃했습니다."},
    "reset": {"kind": "success", "text": "워크스페이스를 초기화했습니다."},
    "broker_added": {"kind": "success", "text": "증권 계좌를 추가했습니다."},
    "broker_removed": {"kind": "success", "text": "증권 연결을 삭제했습니다."},
    "symbol_added": {"kind": "success", "text": "감시 종목을 추가했습니다."},
    "symbol_removed": {"kind": "success", "text": "종목과 연결된 규칙을 삭제했습니다."},
    "pattern_added": {"kind": "success", "text": "자동매매 패턴을 저장했습니다."},
    "pattern_removed": {"kind": "success", "text": "자동매매 패턴을 삭제했습니다."},
    "ai_saved": {"kind": "success", "text": "AI 전략 설정을 저장했습니다."},
    "ai_cleared": {"kind": "success", "text": "AI 전략 설정을 초기화했습니다."},
}

SYMBOL_LIBRARY = {
    "default": [
        {"symbol": "005930", "name": "삼성전자", "market": "KRX", "price": "73,400", "change": "+0.8%"},
        {"symbol": "000660", "name": "SK하이닉스", "market": "KRX", "price": "208,500", "change": "+1.9%"},
        {"symbol": "035420", "name": "NAVER", "market": "KRX", "price": "214,000", "change": "-0.3%"},
        {"symbol": "AAPL", "name": "Apple", "market": "NASDAQ", "price": "$212.51", "change": "+0.4%"},
        {"symbol": "NVDA", "name": "NVIDIA", "market": "NASDAQ", "price": "$918.42", "change": "+2.3%"},
    ],
    "kis": [
        {"symbol": "005930", "name": "삼성전자", "market": "KRX", "price": "73,400", "change": "+0.8%"},
        {"symbol": "005380", "name": "현대차", "market": "KRX", "price": "245,500", "change": "+1.0%"},
        {"symbol": "AAPL", "name": "Apple", "market": "NASDAQ", "price": "$212.51", "change": "+0.4%"},
        {"symbol": "MSFT", "name": "Microsoft", "market": "NASDAQ", "price": "$428.15", "change": "+0.7%"},
    ],
    "kiwoom": [
        {"symbol": "005930", "name": "삼성전자", "market": "KRX", "price": "73,400", "change": "+0.8%"},
        {"symbol": "000660", "name": "SK하이닉스", "market": "KRX", "price": "208,500", "change": "+1.9%"},
        {"symbol": "035720", "name": "카카오", "market": "KRX", "price": "57,300", "change": "-0.6%"},
        {"symbol": "251270", "name": "넷마블", "market": "KRX", "price": "59,600", "change": "+0.2%"},
    ],
    "db": [
        {"symbol": "005930", "name": "삼성전자", "market": "KRX", "price": "73,400", "change": "+0.8%"},
        {"symbol": "035420", "name": "NAVER", "market": "KRX", "price": "214,000", "change": "-0.3%"},
        {"symbol": "TSLA", "name": "Tesla", "market": "NASDAQ", "price": "$178.93", "change": "-1.1%"},
        {"symbol": "QQQ", "name": "Invesco QQQ", "market": "ETF", "price": "$442.80", "change": "+0.5%"},
    ],
    "ls": [
        {"symbol": "005930", "name": "삼성전자", "market": "KRX", "price": "73,400", "change": "+0.8%"},
        {"symbol": "068270", "name": "셀트리온", "market": "KRX", "price": "184,300", "change": "+1.3%"},
        {"symbol": "AMD", "name": "AMD", "market": "NASDAQ", "price": "$178.61", "change": "+1.4%"},
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "ETF", "price": "$509.34", "change": "+0.2%"},
    ],
}


def fresh_draft() -> dict:
    return {
        "profile": {"nickname": "", "email": "", "phone": "", "auth_provider": "", "logged_in_at": ""},
        "brokers": [],
        "symbols": [],
        "patterns": [],
        "ai": {"provider": "", "model": "", "prompt": "", "has_api_key": False, "updated_at": ""},
    }


def html(value: object) -> str:
    return escape(str(value), quote=True)


def trim(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_cookie_value(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cookie_value(encoded: str) -> dict:
    padding = "=" * (-len(encoded) % 4)
    raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def load_draft(cookie_header: str | None) -> dict:
    draft = fresh_draft()
    if not cookie_header:
        return draft

    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        return draft

    morsel = jar.get(COOKIE_NAME)
    if not morsel:
        return draft

    try:
        stored = decode_cookie_value(morsel.value)
    except Exception:
        return draft

    if not isinstance(stored, dict):
        return draft

    merged = deepcopy(draft)
    merged["profile"].update(stored.get("profile", {}))
    merged["brokers"] = list(stored.get("brokers", []))[:8]
    merged["symbols"] = list(stored.get("symbols", []))[:20]
    merged["patterns"] = list(stored.get("patterns", []))[:20]
    merged["ai"].update(stored.get("ai", {}))
    return merged


def draft_cookie_header(draft: dict) -> str:
    return f"{COOKIE_NAME}={encode_cookie_value(draft)}; Path=/; Max-Age=1209600; SameSite=Lax"


def clear_cookie_header() -> str:
    return f"{COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax"


def checked_attr(enabled: bool) -> str:
    return " checked" if enabled else ""


def selected_attr(current: str | None, expected: str) -> str:
    return " selected" if current == expected else ""


def is_authenticated(draft: dict) -> bool:
    profile = draft["profile"]
    return bool(profile.get("auth_provider") and profile.get("email"))


def provider_meta(provider: str | None) -> dict:
    return next((item for item in AUTH_PROVIDERS if item["value"] == provider), AUTH_PROVIDERS[0])


def provider_label(provider: str | None) -> str:
    if not provider:
        return "미연결"
    return provider_meta(provider)["label"] if provider in {item["value"] for item in AUTH_PROVIDERS} else provider


def flash_message_from_query(query: dict[str, list[str]]) -> dict | None:
    flash_key = query.get("flash", [""])[-1]
    return FLASH_MESSAGES.get(flash_key)


def find_connected_broker(draft: dict, broker_id: str) -> dict | None:
    for item in draft["brokers"]:
        if item["broker_id"] == broker_id:
            return item
    return None


def find_symbol(draft: dict, symbol_id: str) -> dict | None:
    for item in draft["symbols"]:
        if item["id"] == symbol_id:
            return item
    return None


def remove_item(items: list[dict], item_id: str) -> list[dict]:
    return [item for item in items if item.get("id") != item_id]


def root_path_for_draft(draft: dict) -> str:
    return "/dashboard" if is_authenticated(draft) else "/login"


def recommended_modal(draft: dict, requested: str | None) -> str | None:
    if requested in MODAL_KEYS:
        return requested
    if not draft["brokers"]:
        return "broker"
    return None


def capability_summary(broker: dict) -> str:
    labels = {"quote": "주가 확인", "buy": "매수", "sell": "매도", "balance": "잔고"}
    parts = []
    for key, label in labels.items():
        capability = CAPABILITY_META[broker["capability"][key]]
        parts.append(f"{label} {capability['label']}")
    return " · ".join(parts)


def get_symbol_catalog(broker_id: str | None) -> list[dict]:
    if not broker_id:
        return SYMBOL_LIBRARY["default"]
    return SYMBOL_LIBRARY.get(broker_id, SYMBOL_LIBRARY["default"])


def lookup_symbol_choice(broker_id: str, symbol_code: str) -> dict | None:
    for item in get_symbol_catalog(broker_id):
        if item["symbol"] == symbol_code:
            return item
    return None


def upsert_broker_entry(draft: dict, broker: dict, values: dict[str, str]) -> None:
    account_label = trim(values.get("accountNumber"), 40)
    if not account_label:
        account_prefix = trim(values.get("accountPrefix"), 40)
        product_code = trim(values.get("accountProductCode"), 20)
        if account_prefix:
            account_label = f"{account_prefix}-{product_code}" if product_code else account_prefix
    if not account_label:
        account_label = trim(values.get("htsId"), 40) or "연결 정보"

    entry = {
        "id": uuid4().hex[:10],
        "broker_id": broker["id"],
        "broker_name": broker["name"],
        "environment": values.get("environment", "production"),
        "account_label": account_label,
        "saved_at": now_iso(),
        "capability_summary": capability_summary(broker),
    }
    existing = [
        item
        for item in draft["brokers"]
        if not (
            item["broker_id"] == entry["broker_id"]
            and item["environment"] == entry["environment"]
            and item["account_label"] == entry["account_label"]
        )
    ]
    draft["brokers"] = [entry, *existing][:8]


def add_symbol_entry(draft: dict, form: dict[str, str]) -> tuple[bool, str]:
    broker_id = trim(form.get("brokerId"), 40)
    symbol_code = trim(form.get("symbolCode"), 24).upper()
    broker_entry = find_connected_broker(draft, broker_id)
    if not broker_entry:
        return False, "먼저 증권을 연결해야 종목을 고를 수 있습니다."
    if not symbol_code:
        return False, "종목을 먼저 선택해야 합니다."

    symbol_meta = lookup_symbol_choice(broker_id, symbol_code)
    if not symbol_meta:
        return False, "선택한 종목을 찾지 못했습니다."

    item = {
        "id": uuid4().hex[:10],
        "symbol": symbol_meta["symbol"],
        "name": symbol_meta["name"],
        "market": symbol_meta["market"],
        "price": symbol_meta["price"],
        "change": symbol_meta["change"],
        "broker_id": broker_id,
        "broker_name": broker_entry["broker_name"],
        "saved_at": now_iso(),
    }
    existing = [entry for entry in draft["symbols"] if not (entry["symbol"] == item["symbol"] and entry["broker_id"] == broker_id)]
    draft["symbols"] = [item, *existing][:20]
    return True, f"{item['name']} 종목을 워치리스트에 추가했습니다."


def add_pattern_entry(draft: dict, form: dict[str, str]) -> tuple[bool, str]:
    symbol_id = trim(form.get("symbolId"), 40)
    pattern_type = trim(form.get("patternType"), 40)
    schedule = trim(form.get("schedule"), 40)
    budget = trim(form.get("budget"), 40)
    profit_target = trim(form.get("profitTarget"), 40)
    stop_loss = trim(form.get("stopLoss"), 40)
    note = trim(form.get("note"), 200)
    buy_enabled = form.get("buyEnabled") == "on"
    sell_enabled = form.get("sellEnabled") == "on"

    if not symbol_id or not pattern_type or not schedule:
        return False, "종목, 패턴, 주기를 모두 선택해야 합니다."
    if not buy_enabled and not sell_enabled:
        return False, "자동 매수나 자동 매도 중 하나 이상을 켜야 합니다."

    symbol_entry = find_symbol(draft, symbol_id)
    if not symbol_entry:
        return False, "먼저 종목을 선택해야 합니다."

    pattern_meta = next((item for item in PATTERN_OPTIONS if item["value"] == pattern_type), None)
    schedule_meta = next((item for item in SCHEDULE_OPTIONS if item["value"] == schedule), None)

    draft["patterns"] = [
        {
            "id": uuid4().hex[:10],
            "symbol_id": symbol_entry["id"],
            "symbol": symbol_entry["symbol"],
            "symbol_name": symbol_entry["name"],
            "pattern_type": pattern_type,
            "pattern_label": pattern_meta["label"] if pattern_meta else pattern_type,
            "pattern_description": pattern_meta["description"] if pattern_meta else "",
            "schedule": schedule,
            "schedule_label": schedule_meta["label"] if schedule_meta else schedule,
            "buy_enabled": buy_enabled,
            "sell_enabled": sell_enabled,
            "budget": budget or "예산 미설정",
            "profit_target": profit_target,
            "stop_loss": stop_loss,
            "note": note,
            "saved_at": now_iso(),
        },
        *draft["patterns"],
    ][:20]
    return True, f"{symbol_entry['name']} 전략을 저장했습니다."


def save_ai_entry(draft: dict, form: dict[str, str]) -> tuple[bool, str]:
    provider = trim(form.get("provider"), 40)
    model = trim(form.get("model"), 80)
    prompt = trim(form.get("prompt"), 400)
    api_key = trim(form.get("apiKey"), 240)

    if not provider or not model or not prompt:
        return False, "AI 제공사, 모델, 프롬프트를 모두 입력해야 합니다."

    draft["ai"] = {
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "has_api_key": bool(api_key),
        "updated_at": now_iso(),
    }
    return True, "AI 전략 설정을 저장했습니다."


def render_select(name: str, label: str, options: list[dict[str, str]], value: str | None, help_text: str, *, required: bool = False) -> str:
    required_tag = '<span class="field-chip">필수</span>' if required else '<span class="field-chip field-chip-muted">선택</span>'
    options_html = "".join(
        f'<option value="{html(option["value"])}"{selected_attr(value, option["value"])}>{html(option["label"])}</option>'
        for option in options
    )
    return f"""
    <div class="field">
      <label for="{html(name)}">{html(label)} {required_tag}</label>
      <select id="{html(name)}" name="{html(name)}">{options_html}</select>
      <small>{html(help_text)}</small>
    </div>
    """


def render_input(
    name: str,
    label: str,
    value: str | None,
    help_text: str,
    *,
    required: bool = False,
    input_type: str = "text",
    placeholder: str = "",
) -> str:
    required_tag = '<span class="field-chip">필수</span>' if required else '<span class="field-chip field-chip-muted">선택</span>'
    return f"""
    <div class="field">
      <label for="{html(name)}">{html(label)} {required_tag}</label>
      <input
        id="{html(name)}"
        name="{html(name)}"
        type="{html(input_type)}"
        value="{html(value or '')}"
        placeholder="{html(placeholder)}"
        autocomplete="off"
      />
      <small>{html(help_text)}</small>
    </div>
    """


def render_textarea(name: str, label: str, value: str | None, help_text: str, *, required: bool = False, placeholder: str = "") -> str:
    required_tag = '<span class="field-chip">필수</span>' if required else '<span class="field-chip field-chip-muted">선택</span>'
    return f"""
    <div class="field field-full">
      <label for="{html(name)}">{html(label)} {required_tag}</label>
      <textarea id="{html(name)}" name="{html(name)}" rows="6" placeholder="{html(placeholder)}">{html(value or '')}</textarea>
      <small>{html(help_text)}</small>
    </div>
    """


def render_message(message: dict | None) -> str:
    if not message:
        return ""
    return f'<div class="message message-{html(message["kind"])}">{html(message["text"])}</div>'


def render_login_page(message: dict | None = None) -> bytes:
    provider_buttons = []
    for provider in AUTH_PROVIDERS:
        provider_buttons.append(
            f"""
            <form method="post" action="/auth/demo">
              <input type="hidden" name="provider" value="{html(provider['value'])}" />
              <button class="auth-button {html(provider['className'])}" type="submit">
                <span class="auth-logo">{html(provider['label'][0])}</span>
                <span>
                  <strong>{html(provider['label'])}</strong>
                  <small>{html(provider['subtitle'])}</small>
                </span>
              </button>
            </form>
            """
        )

    html_body = f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>로그인 | 주식 자동매매</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body class="login-body">
    <main class="login-shell">
      <section class="login-stage">
        <div class="login-copy">
          <span class="eyebrow">Auto Trading</span>
          <h1>로그인 후 바로 대시보드에서 시작하는 자동매매 워크스페이스</h1>
          <p>먼저 로그인하고, 이후 빈 대시보드에서 증권 계좌를 연결한 뒤 종목과 전략을 하나씩 쌓아갑니다.</p>
          <div class="login-bullets">
            <div class="bullet-card">
              <strong>증권 먼저 연결</strong>
              <span>빈 대시보드에서 모달로 바로 추가</span>
            </div>
            <div class="bullet-card">
              <strong>정밀 전략은 템플릿</strong>
              <span>정액, 정률, 시간 조건은 패턴 빌더로 설정</span>
            </div>
            <div class="bullet-card">
              <strong>애매한 조건은 AI</strong>
              <span>정량화하기 어려운 문장은 AI 전략으로 분리</span>
            </div>
          </div>
        </div>

        <div class="login-card">
          <div class="card-head">
            <span class="eyebrow eyebrow-muted">SSO Login</span>
            <h2>소셜 로그인</h2>
            <p>Google, Kakao, Naver, Facebook 기반 흐름으로 시작합니다.</p>
          </div>
          {render_message(message)}
          <div class="auth-stack">
            {''.join(provider_buttons)}
          </div>
          <div class="login-note">
            <strong>현재 프로토타입</strong>
            <p>실제 OAuth 앱 키를 붙이기 전까지는 SSO 버튼이 데모 세션으로 동작합니다.</p>
          </div>
        </div>
      </section>
    </main>
  </body>
</html>
"""
    return html_body.encode("utf-8")


def render_topbar(draft: dict) -> str:
    provider = provider_meta(draft["profile"].get("auth_provider"))
    return f"""
    <header class="dashboard-topbar">
      <div>
        <span class="eyebrow">Trading Desk</span>
        <h1>주식 자동매매</h1>
      </div>
      <div class="topbar-actions">
        <span class="user-badge">{html(provider['label'])} · {html(draft['profile'].get('nickname') or '사용자')}</span>
        <a class="button button-subtle button-small" href="/dashboard?modal=broker">증권 추가</a>
        <form method="post" action="/auth/logout">
          <button class="button button-subtle button-small" type="submit">로그아웃</button>
        </form>
      </div>
    </header>
    """


def render_summary_strip(draft: dict) -> str:
    ai_ready = "연결됨" if draft["ai"].get("provider") and draft["ai"].get("has_api_key") else "대기"
    cards = [
        ("연결 증권", f'{len(draft["brokers"])}개', "브로커 계좌"),
        ("감시 종목", f'{len(draft["symbols"])}개', "워치리스트"),
        ("자동 전략", f'{len(draft["patterns"])}개', "정량 패턴"),
        ("AI 전략", ai_ready, provider_label(draft["ai"].get("provider"))),
    ]
    return "".join(
        f"""
        <div class="summary-card">
          <span>{html(label)}</span>
          <strong>{html(value)}</strong>
          <small>{html(note)}</small>
        </div>
        """
        for label, value, note in cards
    )


def render_dashboard_hero(draft: dict) -> str:
    name = draft["profile"].get("nickname") or "사용자"
    return f"""
    <section class="hero-panel">
      <div>
        <span class="eyebrow eyebrow-dark">Dashboard</span>
        <h2>{html(name)}님의 자동매매 워크스페이스</h2>
        <p>먼저 증권을 연결하고, 그 다음 종목을 고른 뒤 정량 패턴을 붙입니다. 숫자로 정의하기 어려운 전략만 AI로 넘깁니다.</p>
      </div>
      <div class="hero-actions">
        <a class="button button-primary" href="/dashboard?modal=broker">증권 연결</a>
        <a class="button button-secondary" href="/dashboard?modal=symbol">종목 추가</a>
      </div>
      <div class="summary-grid">
        {render_summary_strip(draft)}
      </div>
    </section>
    """


def render_connected_brokers(draft: dict) -> str:
    if not draft["brokers"]:
        return """
        <div class="section-empty">
          <h3>아직 연결된 증권이 없습니다.</h3>
          <p>처음에는 빈 상태로 시작합니다. 여기서 바로 증권 계좌를 추가하면 이후 종목 선택이 열립니다.</p>
          <a class="button button-primary" href="/dashboard?modal=broker">증권 추가</a>
        </div>
        """

    cards = []
    for item in draft["brokers"]:
        env_label = "실전" if item["environment"] == "production" else "모의"
        cards.append(
            f"""
            <div class="broker-card">
              <div>
                <strong>{html(item["broker_name"])}</strong>
                <span>{html(item["account_label"])}</span>
                <small>{html(item.get("capability_summary", ""))}</small>
              </div>
              <div class="broker-card-actions">
                <span class="status-chip">{html(env_label)}</span>
                <form method="post" action="/dashboard/brokers/remove">
                  <input type="hidden" name="itemId" value="{html(item['id'])}" />
                  <button class="button button-subtle button-small" type="submit">삭제</button>
                </form>
              </div>
            </div>
            """
        )
    return "".join(cards)


def render_watchlist_rows(draft: dict) -> str:
    if not draft["symbols"]:
        return """
        <div class="section-empty">
          <h3>워치리스트가 비어 있습니다.</h3>
          <p>증권 연결 후 브로커 기반 종목 목록에서 종목을 고를 수 있습니다.</p>
          <a class="button button-primary" href="/dashboard?modal=symbol">종목 추가</a>
        </div>
        """

    rows = []
    for item in draft["symbols"]:
        rule_count = sum(1 for pattern in draft["patterns"] if pattern["symbol_id"] == item["id"])
        rows.append(
            f"""
            <div class="watchlist-row">
              <div class="watchlist-main">
                <strong>{html(item["name"])}</strong>
                <span>{html(item["symbol"])} · {html(item["market"])} · {html(item["broker_name"])}</span>
              </div>
              <span>{html(item["price"])}</span>
              <span class="price-change">{html(item["change"])}</span>
              <span>{rule_count}개 규칙</span>
              <form method="post" action="/dashboard/symbols/remove">
                <input type="hidden" name="itemId" value="{html(item['id'])}" />
                <button class="button button-subtle button-small" type="submit">삭제</button>
              </form>
            </div>
            """
        )
    return "".join(rows)


def render_pattern_rows(draft: dict) -> str:
    if not draft["patterns"]:
        return """
        <div class="section-empty">
          <h3>정량 패턴이 아직 없습니다.</h3>
          <p>정액, 정률, 주기 기반 전략은 전략 빌더에서 만드는 쪽이 가장 안정적입니다.</p>
          <a class="button button-primary" href="/dashboard?modal=pattern">패턴 만들기</a>
        </div>
        """

    cards = []
    for item in draft["patterns"]:
        badges = [item["budget"], item["schedule_label"]]
        if item.get("profit_target"):
            badges.append(f'익절 {item["profit_target"]}')
        if item.get("stop_loss"):
            badges.append(f'손절 {item["stop_loss"]}')
        cards.append(
            f"""
            <div class="strategy-card">
              <div class="strategy-head">
                <div>
                  <strong>{html(item["symbol_name"])}</strong>
                  <span>{html(item["pattern_label"])}</span>
                </div>
                <form method="post" action="/dashboard/patterns/remove">
                  <input type="hidden" name="itemId" value="{html(item['id'])}" />
                  <button class="button button-subtle button-small" type="submit">삭제</button>
                </form>
              </div>
              <div class="tag-row">
                {''.join(f'<span class="tag">{html(badge)}</span>' for badge in badges)}
              </div>
              <p>{html(item.get("note") or item.get("pattern_description") or "")}</p>
            </div>
            """
        )
    return "".join(cards)


def render_ai_panel(draft: dict) -> str:
    ai = draft["ai"]
    if not ai.get("provider"):
        return """
        <div class="section-empty">
          <h3>AI 전략은 아직 비어 있습니다.</h3>
          <p>정확한 수치로 정의하기 애매한 조건만 AI 전략으로 분리하는 구성이 좋습니다.</p>
          <a class="button button-secondary" href="/dashboard?modal=ai">AI 전략 추가</a>
        </div>
        """

    return f"""
    <div class="ai-card">
      <strong>{html(provider_label(ai["provider"]))}</strong>
      <span>{html(ai.get("model", "모델 미지정"))}</span>
      <p>{html(ai.get("prompt", ""))}</p>
      <div class="tag-row">
        <span class="tag">{'API 키 입력됨' if ai.get('has_api_key') else 'API 키 미입력'}</span>
        <span class="tag">업데이트 {html((ai.get("updated_at") or "")[:10] or "방금")}</span>
      </div>
      <form method="post" action="/dashboard/ai/clear">
        <button class="button button-subtle button-small" type="submit">초기화</button>
      </form>
    </div>
    """


def render_guide_panel() -> str:
    return """
    <div class="guide-panel">
      <div class="guide-card">
        <strong>정밀 전략</strong>
        <p>정액 매수, 정률 매도, 익절·손절, 시간 주기처럼 수치화 가능한 전략은 패턴 빌더에서 처리합니다.</p>
      </div>
      <div class="guide-card">
        <strong>AI 전략</strong>
        <p>뉴스 반응, 서술형 판단, 애매한 심리 조건처럼 정량화가 어려운 구간만 AI 전략으로 넘깁니다.</p>
      </div>
      <div class="guide-card">
        <strong>실브로커 연동</strong>
        <p>현재 종목 선택은 브로커별 데모 카탈로그 기반입니다. 실제 주문 API 연결은 다음 단계에서 붙입니다.</p>
      </div>
    </div>
    """


def render_broker_picker(selected_broker_id: str) -> str:
    chips = []
    for broker in BROKER_DETAILS:
        status = STATUS_META[broker["status"]]
        classes = "broker-tab is-active" if broker["id"] == selected_broker_id else "broker-tab"
        chips.append(
            f"""
            <a class="{classes}" href="/dashboard?modal=broker&broker={html(broker['id'])}">
              <strong>{html(broker["name"])}</strong>
              <span>{html(status["label"])}</span>
            </a>
            """
        )
    return "".join(chips)


def render_modal_shell(title: str, subtitle: str, body: str, message: dict | None = None) -> str:
    return f"""
    <div class="modal-backdrop">
      <a class="modal-dismiss" href="/dashboard" aria-label="닫기"></a>
      <section class="modal-sheet">
        <div class="modal-head">
          <div>
            <span class="eyebrow eyebrow-muted">Workspace Modal</span>
            <h3>{html(title)}</h3>
            <p>{html(subtitle)}</p>
          </div>
          <a class="button button-subtle button-small" href="/dashboard">닫기</a>
        </div>
        {render_message(message)}
        <div class="modal-body">
          {body}
        </div>
      </section>
    </div>
    """


def render_broker_modal(draft: dict, selected_broker_id: str, values: dict[str, str], message: dict | None, validation: dict | None) -> str:
    broker = get_broker_or_none(selected_broker_id) or READY_BROKERS[0]
    status = STATUS_META[broker["status"]]
    guide_items = "".join(f"<li>{html(step)}</li>" for step in broker.get("steps", []))
    source_items = "".join(
        f'<li><a class="inline-link" href="{html(source["url"])}" target="_blank" rel="noreferrer">{html(source["label"])}</a></li>'
        for source in broker.get("sources", [])
    )

    if broker["status"] != "ready":
        body = f"""
        <div class="broker-picker">{render_broker_picker(broker["id"])}</div>
        <div class="unsupported-card">
          <div class="status-row">
            <strong>{html(broker["name"])}</strong>
            <span class="status-chip">{html(status["label"])}</span>
          </div>
          <p>{html(broker["summary"])}</p>
          <div class="capability-row">
            {''.join(f'<span class="tag">{html(label)} {html(CAPABILITY_META[broker["capability"][key]]["label"])}</span>' for key, label in {"quote": "주가", "buy": "매수", "sell": "매도", "balance": "잔고"}.items())}
          </div>
          <div class="modal-split">
            <div>
              <h4>확인 포인트</h4>
              <ol class="bullet-list ordered-list">{guide_items}</ol>
            </div>
            <div>
              <h4>공식 링크</h4>
              <ul class="bullet-list">{source_items}</ul>
            </div>
          </div>
        </div>
        """
        return render_modal_shell("증권 추가", "지원 상태에 맞춰 연결 방식을 확인합니다.", body, message)

    fields_html = []
    for field in broker.get("fields", []):
        if field["type"] == "select":
            fields_html.append(
                render_select(
                    field["key"],
                    field["label"],
                    field.get("options", []),
                    values.get(field["key"]),
                    field.get("help", ""),
                    required=field.get("required", False),
                )
            )
        else:
            fields_html.append(
                render_input(
                    field["key"],
                    field["label"],
                    values.get(field["key"]),
                    field.get("help", ""),
                    required=field.get("required", False),
                    input_type="password" if field["type"] == "password" else "text",
                    placeholder=field.get("placeholder", ""),
                )
            )

    validation_html = ""
    if validation:
        missing = validation.get("missing_fields", [])
        warnings = validation.get("warnings", [])
        validation_html = f"""
        <div class="message message-{'success' if not missing else 'warning'}">
          {'필수 값 검증을 통과했습니다.' if not missing else '필수 입력을 더 채워야 합니다.'}
          {f"<br />누락 필드: {html(', '.join(missing))}" if missing else ""}
          {('<ul class="bullet-list compact-list">' + ''.join(f'<li>{html(item)}</li>' for item in warnings) + '</ul>') if warnings else ''}
        </div>
        """

    body = f"""
    <div class="broker-picker">{render_broker_picker(broker["id"])}</div>
    <div class="modal-split">
      <div class="modal-panel">
        <div class="status-row">
          <strong>{html(broker["name"])}</strong>
          <span class="status-chip">{html(status["label"])}</span>
        </div>
        <p class="panel-copy">{html(broker["summary"])}</p>
        <div class="tag-row">
          {''.join(f'<span class="tag">{html(label)} {html(CAPABILITY_META[broker["capability"][key]]["label"])}</span>' for key, label in {"quote": "주가", "buy": "매수", "sell": "매도", "balance": "잔고"}.items())}
        </div>
        {validation_html}
        <form method="post" action="/dashboard/brokers/add" class="form-grid">
          <input type="hidden" name="selectedBrokerId" value="{html(broker['id'])}" />
          {''.join(fields_html)}
          <div class="field field-full">
            <div class="button-row">
              <button class="button button-primary" type="submit">이 증권 연결</button>
            </div>
            <small>실제 API 키 원문은 저장하지 않고 연결 메타 정보만 임시로 보관합니다.</small>
          </div>
        </form>
      </div>
      <div class="modal-panel">
        <h4>가이드</h4>
        <ol class="bullet-list ordered-list">{guide_items}</ol>
        <h4>공식 링크</h4>
        <ul class="bullet-list">{source_items}</ul>
      </div>
    </div>
    """
    return render_modal_shell("증권 추가", "빈 대시보드에서 가장 먼저 계좌를 연결합니다.", body, message)


def render_symbol_modal(draft: dict, selected_broker_id: str | None, values: dict[str, str], message: dict | None) -> str:
    if not draft["brokers"]:
        body = """
        <div class="section-empty">
          <h3>먼저 증권을 연결해야 합니다.</h3>
          <p>브로커 연결이 끝나면 해당 브로커 기준의 종목 목록을 고를 수 있습니다.</p>
          <a class="button button-primary" href="/dashboard?modal=broker">증권 연결 열기</a>
        </div>
        """
        return render_modal_shell("종목 추가", "브로커 연결 후 종목 선택이 열립니다.", body, message)

    broker_id = selected_broker_id or values.get("brokerId") or draft["brokers"][0]["broker_id"]
    broker_tabs = []
    for broker in draft["brokers"]:
        classes = "broker-tab is-active" if broker["broker_id"] == broker_id else "broker-tab"
        broker_tabs.append(
            f'<a class="{classes}" href="/dashboard?modal=symbol&broker={html(broker["broker_id"])}"><strong>{html(broker["broker_name"])}</strong><span>{html(broker["account_label"])}</span></a>'
        )

    catalog = get_symbol_catalog(broker_id)
    option_label = lambda item: f'{item["name"]} ({item["symbol"]}) · {item["market"]} · {item["price"]} · {item["change"]}'
    symbol_options = [{"value": item["symbol"], "label": option_label(item)} for item in catalog]
    preview_cards = "".join(
        f"""
        <div class="quote-card">
          <strong>{html(item["name"])}</strong>
          <span>{html(item["symbol"])} · {html(item["market"])}</span>
          <b>{html(item["price"])}</b>
          <small>{html(item["change"])}</small>
        </div>
        """
        for item in catalog[:4]
    )
    body = f"""
    <div class="broker-picker">{''.join(broker_tabs)}</div>
    <div class="modal-split">
      <div class="modal-panel">
        <form method="post" action="/dashboard/symbols/add" class="form-grid">
          <input type="hidden" name="brokerId" value="{html(broker_id)}" />
          {render_select("symbolCode", "종목 선택", symbol_options, values.get("symbolCode"), "연결한 증권 기준 종목 카탈로그에서 선택", required=True)}
          <div class="field field-full">
            <div class="button-row">
              <button class="button button-primary" type="submit">워치리스트에 추가</button>
            </div>
          </div>
        </form>
      </div>
      <div class="modal-panel">
        <h4>브로커 기반 종목 목록</h4>
        <p class="panel-copy">실제 브로커 검색 API 연결 전까지는 데모 카탈로그로 흐름을 검증합니다.</p>
        <div class="quote-grid">{preview_cards}</div>
      </div>
    </div>
    """
    return render_modal_shell("종목 추가", "연결된 증권 계좌를 기준으로 워치리스트를 채웁니다.", body, message)


def render_pattern_modal(draft: dict, values: dict[str, str], message: dict | None) -> str:
    if not draft["symbols"]:
        body = """
        <div class="section-empty">
          <h3>먼저 종목을 추가해야 합니다.</h3>
          <p>워치리스트에 종목이 들어와야 패턴 빌더가 열립니다.</p>
          <a class="button button-primary" href="/dashboard?modal=symbol">종목 추가 열기</a>
        </div>
        """
        return render_modal_shell("패턴 설정", "정량 패턴은 종목이 있어야 만들 수 있습니다.", body, message)

    symbol_options = [{"value": item["id"], "label": f'{item["name"]} ({item["symbol"]}) · {item["broker_name"]}'} for item in draft["symbols"]]
    pattern_options = [{"value": item["value"], "label": item["label"]} for item in PATTERN_OPTIONS]
    schedule_options = SCHEDULE_OPTIONS
    presets = "".join(
        f"""
        <div class="guide-card">
          <strong>{html(item["label"])}</strong>
          <p>{html(item["description"])}</p>
        </div>
        """
        for item in PATTERN_OPTIONS
    )
    body = f"""
    <div class="modal-split">
      <div class="modal-panel">
        <form method="post" action="/dashboard/patterns/add" class="form-grid">
          {render_select("symbolId", "대상 종목", symbol_options, values.get("symbolId"), "전략을 붙일 종목 선택", required=True)}
          {render_select("patternType", "전략 템플릿", pattern_options, values.get("patternType"), "정확한 숫자로 표현 가능한 전략 위주", required=True)}
          {render_select("schedule", "감시 주기", schedule_options, values.get("schedule"), "얼마나 자주 체크할지", required=True)}
          {render_input("budget", "회당 금액/비율", values.get("budget"), "예: 회당 30만원, 보유분 25%", required=True, placeholder="회당 30만원")}
          {render_input("profitTarget", "익절 조건", values.get("profitTarget"), "예: +6%, +12% 구간 분할매도", placeholder="+6%")}
          {render_input("stopLoss", "손절 조건", values.get("stopLoss"), "예: -3%, -5% 구간 정리", placeholder="-3%")}
          <div class="field">
            <label>주문 방향 <span class="field-chip">필수</span></label>
            <div class="toggle-group">
              <label class="toggle-item"><input type="checkbox" name="buyEnabled"{checked_attr(values.get("buyEnabled") != "off")} /> 자동 매수</label>
              <label class="toggle-item"><input type="checkbox" name="sellEnabled"{checked_attr(values.get("sellEnabled") == "on")} /> 자동 매도</label>
            </div>
            <small>둘 중 하나 이상 켜야 저장됩니다.</small>
          </div>
          {render_textarea("note", "전략 메모", values.get("note"), "예: 5% 하락 시 3번 분할매수, 8% 수익 시 절반 매도", placeholder="전략 설명")}
          <div class="field field-full">
            <div class="button-row">
              <button class="button button-primary" type="submit">패턴 저장</button>
              <a class="button button-secondary" href="/dashboard?modal=ai">애매한 조건은 AI로</a>
            </div>
          </div>
        </form>
      </div>
      <div class="modal-panel">
        <h4>정량 전략 예시</h4>
        <div class="guide-panel">{presets}</div>
      </div>
    </div>
    """
    return render_modal_shell("패턴 설정", "정액·정률·주기 기반 조건은 패턴 빌더에서 정의합니다.", body, message)


def render_ai_modal(draft: dict, values: dict[str, str], message: dict | None) -> str:
    ai = draft["ai"]
    provider_value = values.get("provider") or ai.get("provider") or "openai"
    model_value = values.get("model") or ai.get("model")
    prompt_value = values.get("prompt") or ai.get("prompt")
    body = f"""
    <div class="modal-split">
      <div class="modal-panel">
        <form method="post" action="/dashboard/ai/save" class="form-grid">
          {render_select("provider", "AI 제공사", AI_PROVIDERS, provider_value, "OpenAI, Anthropic, Google 등", required=True)}
          {render_input("model", "모델명", model_value, "예: gpt-5, claude-sonnet, gemini-pro", required=True, placeholder="gpt-5")}
          {render_input("apiKey", "API 키", "", "입력 즉시 사용하고 저장은 하지 않습니다.", required=True, input_type="password", placeholder="sk-...")}
          {render_textarea("prompt", "전략 프롬프트", prompt_value, "정량화하기 어려운 조건만 자연어로 적습니다.", required=True, placeholder="예: 뉴스 급등 이후 거래량이 둔화되면 보수적으로 분할매도")}
          <div class="field field-full">
            <div class="button-row">
              <button class="button button-primary" type="submit">AI 전략 저장</button>
            </div>
          </div>
        </form>
      </div>
      <div class="modal-panel">
        <h4>AI로 넘기는 경우</h4>
        <div class="guide-panel">
          <div class="guide-card">
            <strong>추천 상황</strong>
            <p>정액, 정률, 시간 조건처럼 숫자로 바로 못 정하는 전략</p>
          </div>
          <div class="guide-card">
            <strong>실행 가드레일</strong>
            <p>AI는 신호만 만들고 최종 예산, 중복 주문, 장 시간 검증은 서버가 다시 확인</p>
          </div>
          <div class="guide-card">
            <strong>현재 상태</strong>
            <p>브로커 주문 API 연결 전까지는 전략 입력과 저장 UX를 먼저 검증</p>
          </div>
        </div>
      </div>
    </div>
    """
    return render_modal_shell("AI 전략", "정량화하기 어려운 전략만 AI 쪽으로 분리합니다.", body, message)


def render_modal(draft: dict, modal: str | None, query: dict[str, list[str]], values: dict[str, str] | None, message: dict | None, validation: dict | None) -> str:
    if modal not in MODAL_KEYS:
        return ""

    selected_broker_id = (query.get("broker", [""])[-1] or (values or {}).get("selectedBrokerId") or (values or {}).get("brokerId") or (draft["brokers"][0]["broker_id"] if draft["brokers"] else READY_BROKERS[0]["id"]))

    if modal == "broker":
        return render_broker_modal(draft, selected_broker_id, values or {}, message, validation)
    if modal == "symbol":
        return render_symbol_modal(draft, selected_broker_id, values or {}, message)
    if modal == "pattern":
        return render_pattern_modal(draft, values or {}, message)
    if modal == "ai":
        return render_ai_modal(draft, values or {}, message)
    return ""


def render_dashboard_page(
    draft: dict,
    *,
    query: dict[str, list[str]],
    message: dict | None = None,
    values: dict[str, str] | None = None,
    validation: dict | None = None,
) -> bytes:
    modal = recommended_modal(draft, query.get("modal", [""])[-1])
    html_body = f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>대시보드 | 주식 자동매매</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body class="dashboard-body">
    <div class="dashboard-shell">
      {render_topbar(draft)}
      {render_dashboard_hero(draft)}
      {render_message(message)}

      <section class="dashboard-grid">
        <article class="panel panel-wide">
          <div class="panel-head">
            <div>
              <h3>워치리스트</h3>
              <p>브로커별 종목 목록을 기반으로 자동매매 대상을 고릅니다.</p>
            </div>
            <a class="button button-secondary button-small" href="/dashboard?modal=symbol">종목 추가</a>
          </div>
          <div class="watchlist-table">{render_watchlist_rows(draft)}</div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>연결된 증권</h3>
              <p>여러 증권 계좌를 동시에 붙일 수 있습니다.</p>
            </div>
            <a class="button button-secondary button-small" href="/dashboard?modal=broker">증권 추가</a>
          </div>
          <div class="stack-list">{render_connected_brokers(draft)}</div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>정량 패턴</h3>
              <p>정액, 정률, 주기 같은 수치 기반 전략</p>
            </div>
            <a class="button button-secondary button-small" href="/dashboard?modal=pattern">패턴 설정</a>
          </div>
          <div class="stack-list">{render_pattern_rows(draft)}</div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>AI 전략</h3>
              <p>애매한 조건은 AI로 분리</p>
            </div>
            <a class="button button-secondary button-small" href="/dashboard?modal=ai">AI 전략</a>
          </div>
          {render_ai_panel(draft)}
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>가이드</h3>
              <p>대시보드는 비워 두고 필요한 작업만 모달로 엽니다.</p>
            </div>
          </div>
          {render_guide_panel()}
        </article>
      </section>
    </div>

    {render_modal(draft, modal, query, values, message if modal else None, validation)}
  </body>
</html>
"""
    return html_body.encode("utf-8")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "StockBrokerOnboardingPython/0.4"

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        include_body: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _send_html(self, body: bytes, *, include_body: bool = True, extra_headers: dict[str, str] | None = None) -> None:
        self._send_bytes(HTTPStatus.OK, body, "text/html; charset=utf-8", include_body=include_body, extra_headers=extra_headers)

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict | list,
        *,
        include_body: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8", include_body=include_body, extra_headers=extra_headers)

    def _send_redirect(self, location: str, *, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send_static(self, path: str, *, include_body: bool) -> bool:
        relative = path.lstrip("/")
        if not relative:
            return False
        target = (ROOT / relative).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            return False
        if not target.is_file():
            return False
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send_bytes(HTTPStatus.OK, body, content_type, include_body=include_body)
        return True

    def _draft(self) -> dict:
        return load_draft(self.headers.get("Cookie"))

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def _route_get(self, *, include_body: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=True)
        draft = self._draft()
        flash = flash_message_from_query(query)

        if path in {"/", "/index.html"}:
            location = root_path_for_draft(draft)
            if include_body:
                self._send_redirect(location)
            else:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", location)
                self.end_headers()
            return

        if path in {"/login", "/signup"}:
            if is_authenticated(draft):
                self._send_redirect("/dashboard")
                return
            self._send_html(render_login_page(flash), include_body=include_body)
            return

        if path == "/dashboard":
            if not is_authenticated(draft):
                self._send_redirect("/login")
                return
            self._send_html(render_dashboard_page(draft, query=query, message=flash), include_body=include_body)
            return

        if path == "/brokers":
            self._send_redirect("/dashboard?modal=broker")
            return

        if path == "/symbols":
            self._send_redirect("/dashboard?modal=symbol")
            return

        if path == "/patterns":
            self._send_redirect("/dashboard?modal=pattern")
            return

        if path == "/ai":
            self._send_redirect("/dashboard?modal=ai")
            return

        if path == "/healthz":
            payload = {
                "status": "ok",
                "service": "stock-broker-onboarding-python",
                "brokers": len(BROKER_DETAILS),
                "build": BUILD_DATE,
            }
            self._send_json(HTTPStatus.OK, payload, include_body=include_body)
            return

        if path == "/api/v1/brokers":
            self._send_json(HTTPStatus.OK, {"items": BROKER_CATALOG}, include_body=include_body)
            return

        if path.startswith("/api/v1/brokers/") and path.endswith("/symbols"):
            broker_id = path.split("/")[-2]
            broker = get_broker_or_none(broker_id)
            if not broker:
                self._send_json(HTTPStatus.NOT_FOUND, {"detail": "broker_not_found"}, include_body=include_body)
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "broker_id": broker_id,
                    "mode": "demo_catalog",
                    "items": get_symbol_catalog(broker_id),
                },
                include_body=include_body,
            )
            return

        if path.startswith("/api/v1/brokers/"):
            broker_id = path.rsplit("/", 1)[-1]
            broker = get_broker_or_none(broker_id)
            if not broker:
                self._send_json(HTTPStatus.NOT_FOUND, {"detail": "broker_not_found"}, include_body=include_body)
                return
            self._send_json(HTTPStatus.OK, broker, include_body=include_body)
            return

        if path == "/favicon.ico":
            self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon", include_body=include_body)
            return

        if self._send_static(path, include_body=include_body):
            return

        self._send_bytes(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8", include_body=include_body)

    def do_GET(self) -> None:
        self._route_get(include_body=True)

    def do_HEAD(self) -> None:
        self._route_get(include_body=False)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        draft = self._draft()

        if path == "/api/v1/account-connections/validate":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            broker = get_broker_or_none(payload.get("broker_id"))
            if not broker:
                self._send_json(HTTPStatus.NOT_FOUND, {"detail": "broker_not_found"})
                return
            result = validate_broker_values(broker, payload.get("values", {}))
            self._send_json(HTTPStatus.OK, result)
            return

        form = self._read_form()

        if path == "/auth/demo":
            provider = trim(form.get("provider"), 32)
            if provider not in {item["value"] for item in AUTH_PROVIDERS}:
                self._send_redirect("/login")
                return
            meta = provider_meta(provider)
            draft = fresh_draft()
            draft["profile"] = {
                "nickname": meta["label"] + " 사용자",
                "email": f'{provider}.demo@{meta["email"]}',
                "phone": "",
                "auth_provider": provider,
                "logged_in_at": now_iso(),
            }
            self._send_redirect("/dashboard?flash=logged_in", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            return

        if path == "/auth/logout":
            self._send_redirect("/login?flash=logged_out", extra_headers={"Set-Cookie": clear_cookie_header()})
            return

        if not is_authenticated(draft):
            self._send_redirect("/login")
            return

        if path == "/dashboard/reset":
            self._send_redirect("/login?flash=reset", extra_headers={"Set-Cookie": clear_cookie_header()})
            return

        if path == "/dashboard/brokers/add":
            selected_broker = form.get("selectedBrokerId") or READY_BROKERS[0]["id"]
            broker = get_broker_or_none(selected_broker)
            if not broker:
                body = render_dashboard_page(
                    draft,
                    query={"modal": ["broker"], "broker": [selected_broker]},
                    message={"kind": "warning", "text": "선택한 증권사를 찾지 못했습니다."},
                    values=form,
                )
                self._send_html(body)
                return

            validation = validate_broker_values(broker, form)
            if validation["is_supported"] and not validation["missing_fields"]:
                upsert_broker_entry(draft, broker, form)
                self._send_redirect(
                    f"/dashboard?flash=broker_added&modal=symbol&broker={html(selected_broker)}",
                    extra_headers={"Set-Cookie": draft_cookie_header(draft)},
                )
                return

            body = render_dashboard_page(
                draft,
                query={"modal": ["broker"], "broker": [selected_broker]},
                message={"kind": "warning", "text": "필수 입력을 채운 뒤 다시 시도해 주세요."},
                values=form,
                validation=validation,
            )
            self._send_html(body)
            return

        if path == "/dashboard/brokers/remove":
            draft["brokers"] = remove_item(draft["brokers"], trim(form.get("itemId"), 40))
            remaining_ids = {item["broker_id"] for item in draft["brokers"]}
            draft["symbols"] = [item for item in draft["symbols"] if item["broker_id"] in remaining_ids]
            remaining_symbol_ids = {item["id"] for item in draft["symbols"]}
            draft["patterns"] = [item for item in draft["patterns"] if item["symbol_id"] in remaining_symbol_ids]
            self._send_redirect("/dashboard?flash=broker_removed", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            return

        if path == "/dashboard/symbols/add":
            success, text = add_symbol_entry(draft, form)
            if success:
                self._send_redirect("/dashboard?flash=symbol_added&modal=pattern", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            else:
                body = render_dashboard_page(
                    draft,
                    query={"modal": ["symbol"], "broker": [form.get("brokerId", "")]},
                    message={"kind": "warning", "text": text},
                    values=form,
                )
                self._send_html(body)
            return

        if path == "/dashboard/symbols/remove":
            removed_id = trim(form.get("itemId"), 40)
            draft["symbols"] = remove_item(draft["symbols"], removed_id)
            draft["patterns"] = [pattern for pattern in draft["patterns"] if pattern.get("symbol_id") != removed_id]
            self._send_redirect("/dashboard?flash=symbol_removed", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            return

        if path == "/dashboard/patterns/add":
            success, text = add_pattern_entry(draft, form)
            if success:
                self._send_redirect("/dashboard?flash=pattern_added", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            else:
                body = render_dashboard_page(
                    draft,
                    query={"modal": ["pattern"]},
                    message={"kind": "warning", "text": text},
                    values=form,
                )
                self._send_html(body)
            return

        if path == "/dashboard/patterns/remove":
            draft["patterns"] = remove_item(draft["patterns"], trim(form.get("itemId"), 40))
            self._send_redirect("/dashboard?flash=pattern_removed", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            return

        if path == "/dashboard/ai/save":
            success, text = save_ai_entry(draft, form)
            if success:
                self._send_redirect("/dashboard?flash=ai_saved", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            else:
                body = render_dashboard_page(
                    draft,
                    query={"modal": ["ai"]},
                    message={"kind": "warning", "text": text},
                    values=form,
                )
                self._send_html(body)
            return

        if path == "/dashboard/ai/clear":
            draft["ai"] = {"provider": "", "model": "", "prompt": "", "has_api_key": False, "updated_at": ""}
            self._send_redirect("/dashboard?flash=ai_cleared", extra_headers={"Set-Cookie": draft_cookie_header(draft)})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"detail": "not_found"})


def main() -> None:
    port = int(os.environ.get("PORT", "80"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
