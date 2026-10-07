"""Pearl Studio 서버로 번역 — 포털 로그인 토큰으로 automaker 의 LLM 을 부른다.

- 로그인: 브라우저로 포털 GET /api/auth/handoff?redirect=<이 앱>/auth/callback&state=<s> 를 연다.
  포털이 1분짜리 1회용 code 를 붙여 돌려보내면 POST /api/auth/handoff/exchange 로 토큰을 받는다.
  (토큰은 주소창·방문 기록에 남지 않는다. 토큰 수명은 포털 AUTH_TOKEN_TTL_DAYS, 보통 30일)
- 번역: POST <서버>/maker/api/v1/capcut/llm {prompt, system} (Authorization: Bearer <토큰>) → {text}
- 토큰·사용자는 data/settings.json 의 pearl_token · pearl_user 에 둔다.
"""
from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SERVER = "https://www.pearlstudio.kr"
_states: dict[str, float] = {}  # 로그인 시작 때 만든 state → 만든 시각(10분 유효)


class AuthError(RuntimeError):
    """토큰이 없거나 만료 — 다시 로그인해야 한다."""


def server(settings: dict) -> str:
    return (settings.get("pearl_server") or DEFAULT_SERVER).rstrip("/")


def login_url(settings: dict, callback: str) -> str:
    now = time.time()
    for k, t in list(_states.items()):
        if now - t > 600:
            _states.pop(k, None)
    state = secrets.token_urlsafe(16)
    _states[state] = now
    q = urllib.parse.urlencode({"redirect": callback, "state": state})
    return f"{server(settings)}/api/auth/handoff?{q}"


def _request(url: str, *, body: dict | None = None, token: str | None = None, timeout: int = 30) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(raw)
            msg = msg.get("error") or msg.get("detail") or raw
        except ValueError:
            msg = raw
        if e.code in (401, 403):
            raise AuthError(f"Pearl Studio 로그인이 필요합니다({e.code}): {str(msg)[:200]}") from e
        raise RuntimeError(f"Pearl Studio 서버 오류 {e.code}: {str(msg)[:300]}") from e


def exchange(settings: dict, code: str, state: str) -> tuple[str, dict]:
    """콜백으로 받은 code 를 토큰으로 바꾼다. state 가 이 앱이 만든 게 아니면 거절."""
    if _states.pop(state, None) is None:
        raise AuthError("로그인 요청이 만료됐거나 이 앱에서 시작한 게 아닙니다. 다시 로그인하세요.")
    res = _request(f"{server(settings)}/api/auth/handoff/exchange", body={"code": code})
    if not res.get("token"):
        raise AuthError(res.get("error") or "토큰을 받지 못했습니다.")
    return res["token"], res.get("user") or {}


def me(settings: dict) -> dict | None:
    """토큰이 살아 있으면 포털 사용자 정보, 아니면 None."""
    token = settings.get("pearl_token")
    if not token:
        return None
    try:
        res = _request(f"{server(settings)}/api/auth/me", token=token, timeout=10)
    except AuthError:
        return None
    return res.get("user") if res.get("success") else None


def call_llm(prompt: str, system: str, settings: dict) -> str:
    token = settings.get("pearl_token")
    if not token:
        raise AuthError("Pearl Studio 에 로그인하지 않았습니다.")
    res = _request(f"{server(settings)}/maker/api/v1/capcut/llm", body={"prompt": prompt, "system": system},
                   token=token, timeout=900)
    text = res.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Pearl Studio 서버가 빈 응답을 돌려줬습니다.")
    return text
