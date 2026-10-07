"""번역문 음성 만들기 — Typecast API (https://typecast.ai/docs).

- POST /v1/text-to-speech → wav(44.1kHz 16bit mono) 바이너리. 인증은 X-API-KEY 헤더.
- 같은 (모델·목소리·언어·문장)은 data/tts/<해시>.wav 로 저장해 두고 다시 돈 내고 만들지 않는다.
- CapCut 목소리 이름(tone_type, 예: «따뜻한 남자») → Typecast 목소리 ID 짝은 설정(tts_voices)에 둔다.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

API = "https://api.typecast.ai"
DEFAULT_MODEL = "ssfm-v30"
DEFAULT_LUFS = -16.0  # 쇼츠 내레이션 크기. Typecast 기본 출력은 -33 LUFS 안팎으로 훨씬 작다(실측)
TTS_DIR = Path(__file__).parent / "data" / "tts"

# 앱 언어 코드 → Typecast(ISO 639-3)
LANG3 = {
    "en": "eng", "ja": "jpn", "zh": "zho", "zh-TW": "zho", "es": "spa", "fr": "fra", "de": "deu",
    "pt": "por", "ru": "rus", "vi": "vie", "id": "ind", "th": "tha", "ar": "ara", "hi": "hin", "ko": "kor",
}

_voices_cache: dict[str, tuple[float, list]] = {}


def api_key(settings: dict) -> str:
    return settings.get("typecast_api_key") or ""


def model(settings: dict) -> str:
    return settings.get("typecast_model") or DEFAULT_MODEL


DEFAULT_MAX_SPEED = 1.15  # 이보다 빠르면 알아듣기 어렵다(1.4배는 실측으로 너무 빨랐음) — 넘치면 영상을 늘린다


def max_speed(settings: dict) -> float:
    try:
        return max(1.0, min(2.0, float(settings.get("tts_max_speed", DEFAULT_MAX_SPEED))))
    except (TypeError, ValueError):
        return DEFAULT_MAX_SPEED


def lufs(settings: dict) -> float:
    try:
        return max(-70.0, min(0.0, float(settings.get("tts_lufs", DEFAULT_LUFS))))
    except (TypeError, ValueError):
        return DEFAULT_LUFS


def _request(method: str, path: str, settings: dict, body: dict | None = None, timeout: int = 120) -> bytes:
    key = api_key(settings)
    if not key:
        raise RuntimeError("Typecast API 키가 없습니다. 설정에서 넣으세요.")
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = {401: "API 키가 맞지 않습니다", 402: "크레딧이 모자랍니다", 429: "요청이 너무 잦습니다 — 잠시 뒤 다시"}.get(e.code, "")
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Typecast 오류 {e.code}{' — ' + msg if msg else ''}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Typecast 에 연결하지 못했습니다: {e.reason}") from e


def voices(settings: dict) -> list[dict]:
    """[{id, name, gender, age, use_cases, preview_url}] — 10분 동안 기억."""
    m = model(settings)
    hit = _voices_cache.get(m)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    raw = json.loads(_request("GET", "/v3/voices?" + urllib.parse.urlencode({"model": m}), settings))
    items = raw if isinstance(raw, list) else raw.get("voices") or raw.get("result") or []
    out = []
    for v in items:
        name = v.get("voice_name")
        if isinstance(name, dict):
            name = name.get("kor") or name.get("eng") or next(iter(name.values()), "")
        out.append({"id": v.get("voice_id"), "name": name or v.get("voice_id"), "gender": v.get("gender") or "",
                    "age": v.get("age") or "", "use_cases": v.get("use_cases") or [],
                    "preview_url": v.get("preview_url") or ""})
    out.sort(key=lambda v: (v["gender"], v["name"]))
    _voices_cache[m] = (time.time(), out)
    return out


def cache_path(settings: dict, voice_id: str, lang: str, text: str) -> Path:
    h = hashlib.sha1(f"{model(settings)}|{voice_id}|{lang}|{lufs(settings)}|{text}".encode("utf-8")).hexdigest()[:20]
    return TTS_DIR / f"{h}.wav"


def synthesize(text: str, voice_id: str, lang: str, settings: dict) -> Path:
    """번역문 → wav 파일 경로(캐시)."""
    p = cache_path(settings, voice_id, lang, text)
    if p.is_file() and p.stat().st_size > 44:
        return p
    body = {"text": text, "model": model(settings), "voice_id": voice_id,
            "output": {"audio_format": "wav", "target_lufs": lufs(settings)}}
    if lang in LANG3:
        body["language"] = LANG3[lang]
    if model(settings) == "ssfm-v30":
        body["prompt"] = {"emotion_type": "smart"}  # 문맥으로 감정을 고른다
    data = _request("POST", "/v1/text-to-speech", settings, body, timeout=180)
    if not data.startswith(b"RIFF"):
        raise RuntimeError(f"Typecast 가 wav 가 아닌 응답을 보냈습니다: {data[:200]!r}")
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    return p


def duration_us(p: Path) -> int:
    """wav 길이(마이크로초) — CapCut 시간 단위."""
    try:
        with wave.open(str(p), "rb") as w:
            frames, rate, width, ch = w.getnframes(), w.getframerate(), w.getsampwidth(), w.getnchannels()
        real = (p.stat().st_size - 44) // (width * ch)  # 헤더 길이가 비어 있는(스트리밍식) wav 대비
        return int(min(frames, real) * 1_000_000 / rate) if frames else int(real * 1_000_000 / rate)
    except (wave.Error, EOFError):
        return int((p.stat().st_size - 44) / (44100 * 2) * 1_000_000)  # 문서상 기본: 44.1kHz 16bit mono
