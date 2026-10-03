"""숏폼 자막 로컬라이즈(직역 아님) — automaker capcut_service 의 프롬프트를 옮겨 왔다.

엔진: OpenAI API 키가 있으면 API(빠름), 없으면 codex CLI(로그인 세션, 느림).
번역 결과는 data/translations.json 에 언어별로 쌓아 두고, 미리보기에서 고친 문장도
같은 곳에 저장한다 → 복제할 때 그대로 쓰고 같은 문장은 다시 돈 내고 번역하지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

LANGUAGES: dict[str, str] = {
    "en": "English", "ja": "Japanese", "zh": "Chinese (Simplified)", "zh-TW": "Chinese (Traditional)",
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "ru": "Russian",
    "vi": "Vietnamese", "id": "Indonesian", "th": "Thai", "ar": "Arabic", "hi": "Hindi", "ko": "Korean",
}
LANGUAGE_LABELS: dict[str, str] = {
    "en": "English", "ja": "日本語", "zh": "简体中文", "zh-TW": "繁體中文", "es": "Español",
    "fr": "Français", "de": "Deutsch", "pt": "Português", "ru": "Русский", "vi": "Tiếng Việt",
    "id": "Indonesia", "th": "ไทย", "ar": "العربية", "hi": "हिन्दी", "ko": "한국어",
}

SYSTEM = (
    "You are a native-speaker localizer for short-form video captions (YouTube Shorts, "
    "TikTok, Reels). You do NOT translate literally — you rewrite the meaning the way native "
    "speakers actually talk RIGHT NOW, using current, natural, commonly-used everyday wording "
    "and slang where it fits. Keep the tone and vibe, keep it short and punchy for on-screen text. "
    "Return ONLY valid JSON."
)
BATCH_SIZE = 150  # 한 번에 크게 보내야 영상 전체의 용어·톤이 맞는다

DATA_DIR = Path(__file__).parent / "data"
CACHE_PATH = DATA_DIR / "translations.json"
_lock = threading.Lock()


# ─── 캐시 ──────────────────────────────────────────────────────────────────
def load_cache() -> dict[str, dict[str, str]]:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_entries(lang: str, pairs: dict[str, str]) -> None:
    with _lock:
        cache = load_cache()
        cache.setdefault(lang, {}).update(pairs)
        DATA_DIR.mkdir(exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, CACHE_PATH)


# ─── 엔진 ──────────────────────────────────────────────────────────────────
def engine_name(settings: dict) -> str:
    if settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY"):
        return "openai-api"
    if shutil.which("codex"):
        return "codex-cli"
    return "none"


def _call_openai_api(prompt: str, settings: dict) -> str:
    key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    body = json.dumps({
        "model": settings.get("openai_model") or "gpt-4.1-mini",
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI API 오류 {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
    return data["choices"][0]["message"]["content"] or ""


def _call_codex_cli(prompt: str, settings: dict) -> str:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("번역 엔진이 없습니다. 설정에서 OpenAI API 키를 넣거나 codex CLI 에 로그인하세요.")
    fd, out_path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        cmd = [codex, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
               "--color", "never", "-o", out_path, "-"]
        if settings.get("codex_model"):
            cmd[2:2] = ["-m", settings["codex_model"]]
        r = subprocess.run(cmd, input=f"{SYSTEM}\n\n{prompt}", capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, cwd=tempfile.gettempdir())
        content = Path(out_path).read_text(encoding="utf-8", errors="replace")
        if r.returncode != 0 or not content.strip():
            raise RuntimeError(f"codex CLI 실패(code={r.returncode}): {r.stderr[-400:]}")
        return content
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _parse_json(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    return json.loads(s[start:end + 1])


def _translate_batch(texts: list[str], lang: str, settings: dict, glossary: dict[str, str]) -> list[str]:
    lang_name = LANGUAGES.get(lang, lang)
    gloss = ""
    if glossary:
        gloss = ("GLOSSARY — these terms already appeared earlier in the SAME video and were localized "
                 "as below. Reuse the EXACT same rendering:\n"
                 + "\n".join(f'"{k}" -> "{v}"' for k, v in glossary.items()) + "\n\n")
    prompt = (
        f"These strings are the sequential on-screen captions of ONE short-form video. "
        f"Localize each into {lang_name}. "
        "Do NOT translate word-for-word. Rewrite the way a native speaker would actually say it "
        "today — natural, current, commonly-used wording/slang, not stiff or textbook. "
        "Read them as a connected script: keep terminology, names, and tone CONSISTENT across all "
        "items so the whole video flows naturally. Keep the same meaning and length feel (short & punchy). "
        "Keep the SAME order and SAME number of items, do not merge or split, keep line breaks (\\n). "
        "Keep emoji as they are.\n\n"
        f"{gloss}"
        f"INPUT (JSON array):\n{json.dumps(texts, ensure_ascii=False)}\n\n"
        'OUTPUT (JSON only): {"items":["<localized 1>","<localized 2>", ...]}'
    )
    call = _call_openai_api if engine_name(settings) == "openai-api" else _call_codex_cli
    items = _parse_json(call(prompt, settings)).get("items")
    if not isinstance(items, list) or len(items) != len(texts):
        raise RuntimeError(f"번역 개수 불일치(요청 {len(texts)}, 응답 {len(items) if isinstance(items, list) else '없음'})")
    return [str(x) for x in items]


def translate(texts: list[str], lang: str, settings: dict, progress=None) -> dict[str, str]:
    """texts(순서 유지·중복 없음) → {원문: 번역}. 캐시에 있는 건 건너뛰고 새로 번역한 것만 저장."""
    cached = load_cache().get(lang, {})
    todo = [t for t in texts if t not in cached]
    result = {t: cached[t] for t in texts if t in cached}
    glossary: dict[str, str] = {}
    batches = max(1, -(-len(todo) // BATCH_SIZE))
    for bi, i in enumerate(range(0, len(todo), BATCH_SIZE), 1):
        chunk = todo[i:i + BATCH_SIZE]
        if progress:
            progress(f"{LANGUAGE_LABELS.get(lang, lang)} 번역 중 · 묶음 {bi}/{batches} · {len(chunk)}줄 "
                     f"(보통 10~60초)")
        out = _translate_batch(chunk, lang, settings, glossary)
        pairs = dict(zip(chunk, out))
        save_entries(lang, pairs)
        result.update(pairs)
        for s, d in pairs.items():  # 다음 묶음으로 넘길 짧은 용어
            if 0 < len(s) <= 16:
                glossary[s] = d
        glossary = dict(list(glossary.items())[-60:])
    return result
