#!/usr/bin/env python3
from __future__ import annotations

import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from backend.app.catalog import (
    BROKER_CATALOG,
    BROKER_DETAILS,
    CAPABILITY_META,
    FILTERS,
    STATUS_META,
    build_summary_counts,
    get_broker_or_none,
    get_selected_broker,
    get_visible_brokers,
    normalize_filter,
    validate_broker_values,
)


ROOT = Path(__file__).resolve().parent
CAPABILITY_CARDS = [
    ("quote", "주식 확인"),
    ("buy", "주식 사기"),
    ("sell", "주식 팔기"),
    ("balance", "계좌 잔고 확인"),
]
CONNECTION_ROUTE = re.compile(r"^/connections/(?P<broker_id>[^/]+)/(?P<action>validate|export)$")
BROKER_API_ROUTE = re.compile(r"^/api/v1/brokers/(?P<broker_id>[^/]+)$")
BUILD_DATE = "2026-03-13"


def html(value: object) -> str:
    return escape(str(value), quote=True)


def selected_value(value: str | None, option_value: str) -> str:
    return " selected" if value == option_value else ""


def active_class(enabled: bool, class_name: str) -> str:
    return f" {class_name}" if enabled else ""


def build_url(**params: str) -> str:
    cleaned = {key: value for key, value in params.items() if value}
    if not cleaned:
        return "/"
    return f"/?{urlencode(cleaned)}"


def normalize_form_values(broker: dict, values: dict[str, str]) -> dict[str, str]:
    accepted = {field["key"] for field in broker.get("fields", [])}
    return {field["key"]: values.get(field["key"], "") for field in broker.get("fields", []) if field["key"] in accepted}


def render_summary_cards() -> str:
    counts = build_summary_counts()
    cards = [
        ("전체 증권사/앱", counts["total"], "현재 목록에 포함된 대상"),
        ("바로 연결 가능", counts["ready"], "self-service 공개 API 확인"),
        ("제휴형/레거시", counts["partner"] + counts["limited"], "회사 승인 또는 추가 검증 필요"),
        ("공개 주문 API 미확인", counts["unavailable"], "화면에는 사유만 우선 표시"),
    ]
    return "".join(
        f"""
        <div class="summary-card">
          <span>{html(label)}</span>
          <strong>{value}</strong>
          <span>{html(note)}</span>
        </div>
        """
        for label, value, note in cards
    )


def render_filters(filter_id: str) -> str:
    parts: list[str] = []
    for item in FILTERS:
        classes = f"filter-pill{active_class(filter_id == item['id'], 'is-active')}"
        href = build_url(filter=item["id"])
        parts.append(
            f"""
            <a class="{classes}" href="{href}">
              {html(item["label"])}
            </a>
            """
        )
    return "".join(parts)


def render_broker_list(filter_id: str, selected_id: str | None) -> str:
    visible_brokers = get_visible_brokers(filter_id)
    if not visible_brokers:
        return """
        <div class="empty-state">
          <h3>표시할 증권사가 없습니다.</h3>
          <p>현재 필터에 맞는 대상이 없습니다. 다른 필터를 선택해 보세요.</p>
        </div>
        """

    cards: list[str] = []
    for broker in visible_brokers:
        status = STATUS_META[broker["status"]]
        capability_html = []
        for key, label in CAPABILITY_CARDS:
            capability = CAPABILITY_META[broker["capability"][key]]
            capability_html.append(
                f"""
                <div class="compact-item">
                  <span>{html(label)}</span>
                  <strong class="cap-pill {html(capability['className'])}">{html(capability['label'])}</strong>
                </div>
                """
            )

        classes = f"broker-card{active_class(broker['id'] == selected_id, 'is-selected')}"
        href = build_url(filter=filter_id, broker=broker["id"])
        cards.append(
            f"""
            <a class="{classes}" href="{href}">
              <div class="broker-head">
                <div class="broker-name-wrap">
                  <h3 class="broker-name">{html(broker["name"])}</h3>
                  <p class="broker-subtitle">{html(broker["subtitle"])}</p>
                </div>
                <span class="status-badge {html(status['className'])}">{html(status['label'])}</span>
              </div>
              <p class="broker-summary">{html(broker["summary"])}</p>
              <div class="cap-grid-compact">
                {''.join(capability_html)}
              </div>
            </a>
            """
        )
    return "".join(cards)


def render_validation_panel(result: dict | None) -> str:
    if not result:
        return ""

    missing = result.get("missing_fields", [])
    warnings = result.get("warnings", [])
    if not result.get("is_supported"):
        title = "현재는 self-service 입력을 열지 않는 상태입니다."
    elif missing:
        title = "필수 입력값이 비어 있습니다."
    else:
        title = "기본 필드 검증은 통과했습니다."

    warning_html = ""
    if warnings:
        warning_html = f"""
        <ul class="note-list">
          {''.join(f"<li>{html(warning)}</li>" for warning in warnings)}
        </ul>
        """

    missing_html = ""
    if missing:
        missing_html = f"""
        <p class="helper-text">누락 필드: {html(', '.join(missing))}</p>
        """

    return f"""
    <div class="empty-state">
      <h3>{html(title)}</h3>
      {missing_html}
      {warning_html}
    </div>
    """


def render_field(field: dict, value: str | None) -> str:
    required = '<span class="required-mark">필수</span>' if field.get("required") else '<span class="required-mark">선택</span>'
    if field["type"] == "select":
        options = "".join(
            f'<option value="{html(option["value"])}"{selected_value(value, option["value"])}>{html(option["label"])}</option>'
            for option in field.get("options", [])
        )
        return f"""
        <div class="field">
          <label for="{html(field['key'])}">
            {html(field['label'])}
            {required}
          </label>
          <select id="{html(field['key'])}" name="{html(field['key'])}">
            {options}
          </select>
          <small>{html(field.get("help", ""))}</small>
        </div>
        """

    return f"""
    <div class="field">
      <label for="{html(field['key'])}">
        {html(field['label'])}
        {required}
      </label>
      <input
        id="{html(field['key'])}"
        name="{html(field['key'])}"
        type="{html(field['type'])}"
        value="{html(value or '')}"
        placeholder="{html(field.get('placeholder', ''))}"
        autocomplete="off"
      />
      <small>{html(field.get("help", ""))}</small>
    </div>
    """


def render_credential_panel(
    broker: dict,
    filter_id: str,
    form_values: dict[str, str] | None,
    validation_result: dict | None,
) -> str:
    if broker["status"] != "ready":
        status = STATUS_META[broker["status"]]
        return f"""
        <div class="stack-card">
          <h3>계정/API 입력</h3>
          <div class="empty-state">
            <h3>{html(status['label'])}</h3>
            <p>
              {html(status['description'])} 상태라서, 현재 버전에서는 이 증권사 전용 입력 폼을 열지 않았습니다.
              먼저 안내 문구와 공식 링크를 검토한 뒤, 실제 제휴 승인 또는 세부 인증 검증이 끝나면 전용 폼을 추가하는 흐름이 안전합니다.
            </p>
          </div>
        </div>
        """

    values = normalize_form_values(broker, form_values or {})
    fields_html = "".join(render_field(field, values.get(field["key"])) for field in broker.get("fields", []))
    validation_html = render_validation_panel(validation_result)
    action = f"/connections/{broker['id']}/validate"
    export_action = f"/connections/{broker['id']}/export"

    return f"""
    <div class="stack-card">
      <h3>계정/API 입력</h3>
      <p class="security-banner">
        지금은 <strong>브라우저 저장 없이 서버 렌더링만</strong> 합니다.
        값 검증과 JSON 내보내기만 지원하고, 실제 저장과 주문 실행은 아직 붙이지 않았습니다.
      </p>
      {validation_html}
      <form id="form-{html(broker['id'])}" method="post" action="{html(action)}">
        <input type="hidden" name="uiFilter" value="{html(filter_id)}" />
        <input type="hidden" name="uiBroker" value="{html(broker['id'])}" />
        <div class="form-grid">
          {fields_html}
        </div>
        <div class="actions">
          <button type="submit" class="action-btn action-primary">입력값 검증</button>
          <button
            type="submit"
            class="action-btn action-secondary"
            formaction="{html(export_action)}"
            formmethod="post"
          >
            JSON 내보내기
          </button>
        </div>
      </form>
      <p class="helper-text">
        이 값은 현재 세션에서만 검증에 사용됩니다. 실서비스 전환 시에는 서버 측 비밀정보 암호화 저장이 필요합니다.
      </p>
    </div>
    """


def render_detail_card(
    broker: dict | None,
    filter_id: str,
    form_values: dict[str, str] | None,
    validation_result: dict | None,
) -> str:
    if not broker:
        return """
        <div class="empty-state">
          <h3>표시할 증권사가 없습니다.</h3>
          <p>현재 필터에 맞는 대상이 없습니다. 다른 필터를 선택해 보세요.</p>
        </div>
        """

    status = STATUS_META[broker["status"]]
    capability_cards = "".join(
        f"""
        <div class="capability-card">
          <h3>{html(label)}</h3>
          <span class="cap-pill {html(CAPABILITY_META[broker['capability'][key]]['className'])}">
            {html(CAPABILITY_META[broker['capability'][key]]['label'])}
          </span>
        </div>
        """
        for key, label in CAPABILITY_CARDS
    )

    guide_items = "".join(f"<li>{html(step)}</li>" for step in broker.get("steps", []))
    notice_items = "".join(f"<li>{html(note)}</li>" for note in broker.get("notices", []))
    source_items = "".join(
        f'<li><a class="inline-link" href="{html(source["url"])}" target="_blank" rel="noreferrer">{html(source["label"])}</a></li>'
        for source in broker.get("sources", [])
    )
    form_state = "현재 입력값 있음" if form_values else "아직 입력 없음"
    credential_panel = render_credential_panel(broker, filter_id, form_values, validation_result)

    return f"""
    <article class="detail-card">
      <section class="detail-hero">
        <div class="detail-topline">
          <p class="section-label">Broker Detail</p>
          <span class="status-badge {html(status['className'])}">{html(status['label'])}</span>
          <span class="mini-badge">{html(broker['audience'])}</span>
        </div>
        <h2 class="detail-title">{html(broker['name'])}</h2>
        <p class="detail-summary">{html(broker['summary'])}</p>
        <div class="callout-strip">
          <div class="callout">
            <span>적합한 용도</span>
            <strong>{html(broker['fit'])}</strong>
          </div>
          <div class="callout">
            <span>온보딩 방식</span>
            <strong>{html(broker['onboardingMode'])}</strong>
          </div>
          <div class="callout">
            <span>폼 상태</span>
            <strong>{html(form_state)}</strong>
          </div>
        </div>
      </section>

      <section class="capability-matrix">
        {capability_cards}
      </section>

      <section class="detail-grid">
        <div class="stack-card">
          <h3>신청 가이드</h3>
          <ol class="guide-list">
            {guide_items}
          </ol>
        </div>

        {credential_panel}
      </section>

      <section class="detail-grid">
        <div class="stack-card">
          <h3>주의사항</h3>
          <ul class="note-list">
            {notice_items}
          </ul>
        </div>
        <div class="stack-card">
          <h3>공식 링크</h3>
          <ul class="source-list">
            {source_items}
          </ul>
        </div>
      </section>
    </article>
    """


def render_home_page(
    filter_id: str,
    selected_broker_id: str | None,
    form_values: dict[str, str] | None = None,
    validation_result: dict | None = None,
) -> bytes:
    normalized_filter = normalize_filter(filter_id)
    selected_broker = get_selected_broker(normalized_filter, selected_broker_id)
    selected_id = selected_broker["id"] if selected_broker else None

    document = f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Stock Broker Onboarding Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=VT323&display=swap"
      rel="stylesheet"
    />
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="page-shell">
      <div class="top-statusbar">
        <span>SYS: PYTHON-RENDER</span>
        <span>MODE: TOY-PROJECT</span>
        <span>DATE: {BUILD_DATE}</span>
        <span>PROFILE: MULTI-BROKER</span>
      </div>
      <header class="hero">
        <div class="hero-copy">
          <p class="boot-line">C:\\TRADER\\BOOT&gt; render --python --brokers --setup-guide</p>
          <p class="eyebrow">Multi-Broker Setup</p>
          <h1>증권사 API 키와 계좌 정보를 Python 중심으로 정리하는 허브</h1>
          <p class="hero-text">
            회원가입과 계좌개설은 각 증권사에서 직접 진행하고, 이 화면에서는
            자동매매에 필요한 <strong>계좌번호</strong>,
            <strong>App Key/App Secret</strong>, <strong>추가 식별값</strong>만
            다룹니다. 브로커 메타데이터, 필터링, 상세 가이드, 입력 검증, JSON 내보내기를
            모두 Python 서버가 직접 처리합니다.
          </p>
        </div>
        <div class="hero-meta">
          <div class="meta-card">
            <span class="meta-label">공통 목표</span>
            <strong>시세 확인 · 매수 · 매도 · 잔고 조회</strong>
          </div>
          <div class="meta-card">
            <span class="meta-label">현재 기준</span>
            <strong>{BUILD_DATE} 반영</strong>
          </div>
          <div class="meta-card">
            <span class="meta-label">실행 엔진</span>
            <strong>Python HTTP Server</strong>
          </div>
        </div>
      </header>

      <section class="summary-section">
        <div class="summary-grid">
          {render_summary_cards()}
        </div>
        <div class="legend">
          <span class="legend-item">
            <span class="dot dot-ready"></span> 바로 연결 가능
          </span>
          <span class="legend-item">
            <span class="dot dot-partner"></span> 제휴형
          </span>
          <span class="legend-item">
            <span class="dot dot-limited"></span> 레거시/확인 필요
          </span>
          <span class="legend-item">
            <span class="dot dot-unavailable"></span> 공개 주문 API 미확인
          </span>
        </div>
      </section>

      <main class="workspace">
        <aside class="catalog-panel">
          <div class="panel-header">
            <div>
              <p class="panel-kicker">Broker Catalog</p>
              <h2>증권사 목록</h2>
            </div>
            <div class="filter-pills">
              {render_filters(normalized_filter)}
            </div>
          </div>
          <div class="broker-list">
            {render_broker_list(normalized_filter, selected_id)}
          </div>
        </aside>

        <section class="detail-panel">
          {render_detail_card(selected_broker, normalized_filter, form_values, validation_result)}
        </section>
      </main>

      <footer class="footer-note">
        <p>
          현재 버전은 Python 서버 중심 프로토타입입니다. 다음 단계에서는 계좌/키 암호화 저장,
          브로커 어댑터, 패턴 감시 워커, AI 신호 엔진을 추가해야 합니다.
        </p>
      </footer>
    </div>
  </body>
</html>
"""
    return document.encode("utf-8")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "StockBrokerOnboardingPython/0.2"

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
        include_body: bool = True,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict | list,
        include_body: bool = True,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8", headers=headers, include_body=include_body)

    def _send_html(self, body: bytes, include_body: bool = True) -> None:
        self._send_bytes(HTTPStatus.OK, body, "text/html; charset=utf-8", include_body=include_body)

    def _send_html_status(self, status: HTTPStatus, body: bytes, include_body: bool = True) -> None:
        self._send_bytes(status, body, "text/html; charset=utf-8", include_body=include_body)

    def _send_static_file(self, target: Path, include_body: bool = True) -> None:
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send_bytes(HTTPStatus.OK, body, content_type, include_body=include_body)

    def _parse_form_body(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def _handle_home(self, query: dict[str, list[str]], include_body: bool) -> None:
        filter_id = query.get("filter", ["all"])[-1]
        broker_id = query.get("broker", [""])[-1] or None
        body = render_home_page(filter_id=filter_id, selected_broker_id=broker_id)
        self._send_html(body, include_body=include_body)

    def _handle_healthz(self, include_body: bool) -> None:
        self._send_json(
            HTTPStatus.OK,
            {"status": "ok", "service": "stock-broker-onboarding-python", "brokers": len(BROKER_DETAILS)},
            include_body=include_body,
        )

    def _handle_brokers_api(self, include_body: bool) -> None:
        payload = {"items": BROKER_CATALOG}
        self._send_json(HTTPStatus.OK, payload, include_body=include_body)

    def _handle_broker_detail_api(self, broker_id: str, include_body: bool) -> None:
        broker = get_broker_or_none(broker_id)
        if not broker:
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "broker_not_found"}, include_body=include_body)
            return
        self._send_json(HTTPStatus.OK, broker, include_body=include_body)

    def _handle_api_validation(self, include_body: bool) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        broker = get_broker_or_none(payload.get("broker_id"))
        if not broker:
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "broker_not_found"}, include_body=include_body)
            return
        result = validate_broker_values(broker, payload.get("values", {}))
        self._send_json(HTTPStatus.OK, result, include_body=include_body)

    def _handle_connection_action(self, broker_id: str, action: str, include_body: bool) -> None:
        broker = get_broker_or_none(broker_id)
        if not broker:
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "broker_not_found"}, include_body=include_body)
            return

        form = self._parse_form_body()
        filter_id = form.pop("uiFilter", "all")
        form.pop("uiBroker", None)
        values = normalize_form_values(broker, form)

        if action == "validate":
            result = validate_broker_values(broker, values)
            body = render_home_page(filter_id=filter_id, selected_broker_id=broker_id, form_values=values, validation_result=result)
            self._send_html(body, include_body=include_body)
            return

        payload = {
            "brokerId": broker["id"],
            "brokerName": broker["name"],
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "values": values,
        }
        headers = {"Content-Disposition": f'attachment; filename="{broker["id"]}-credentials.json"'}
        self._send_json(HTTPStatus.OK, payload, include_body=include_body, headers=headers)

    def _handle_static(self, path: str, include_body: bool) -> bool:
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
        self._send_static_file(target, include_body=include_body)
        return True

    def _route_get(self, include_body: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=True)

        if path in {"/", "/index.html"}:
            self._handle_home(query, include_body=include_body)
            return
        if path == "/healthz":
            self._handle_healthz(include_body=include_body)
            return
        if path == "/api/v1/brokers":
            self._handle_brokers_api(include_body=include_body)
            return
        if path == "/favicon.ico":
            self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon", include_body=include_body)
            return

        match = BROKER_API_ROUTE.match(path)
        if match:
            self._handle_broker_detail_api(match.group("broker_id"), include_body=include_body)
            return

        if self._handle_static(path, include_body=include_body):
            return

        self._send_html_status(HTTPStatus.NOT_FOUND, b"<h1>404</h1><p>Not found</p>", include_body=include_body)

    def do_GET(self) -> None:
        self._route_get(include_body=True)

    def do_HEAD(self) -> None:
        self._route_get(include_body=False)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/v1/account-connections/validate":
            self._handle_api_validation(include_body=True)
            return

        match = CONNECTION_ROUTE.match(path)
        if match:
            self._handle_connection_action(match.group("broker_id"), match.group("action"), include_body=True)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"detail": "not_found"})


def main() -> None:
    port = int(os.environ.get("PORT", "80"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
