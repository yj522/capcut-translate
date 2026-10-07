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

import pearl

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
# 자연스럽게 바꾸되 놓치면 안 되는 것 — 일본어판 검토(2026-10)에서 지적된 유형을 규칙으로 남겼다
FIDELITY = (
    "NATURAL BUT FAITHFUL — while rewriting naturally, never lose these:\n"
    "- Who does what: keep the subject and the action. e.g. '다이소에 파는 건데' = 'it is SOLD at Daiso' "
    "(not 'I bought it'); do not swap selling/buying, giving/receiving, doing/being done.\n"
    "- Intensity: keep intensifiers and emphasis (너무, 진짜, 완전, 엄청 …) with a natural equivalent — "
    "'너무 예쁘다고요?' must stay emphatic, not a flat 'cute, right?'.\n"
    "- Precision: do not make a word more specific or more vague than the source "
    "(질감 = texture, 광택감 = gloss — keep whichever was said).\n"
    "- Quantity/frequency: '많이' (a lot / often), '두 가지 모두' (both of the two), numbers, shade numbers "
    "and product names stay exact.\n"
    "- Connectives: a caption that ends mid-sentence (…인데, …하고, …해서) must end so it still flows into the "
    "next caption (e.g. Japanese …なんだけど / …して), not as a closed statement.\n"
    "- Speaker's tone: casual stays casual, polite stays polite.\n\n"
)
LANG_NOTES: dict[str, str] = {
    "ja": ("JAPANESE NOTES — sound like a Japanese beauty/lifestyle short (TikTok/Reels JP): "
           "keep emphasis with すごく / めっちゃ / ほんと / 〜すぎ; '-인데' mid-sentence → 〜なんだけど / 〜で; "
           "'파는' → 売ってる; brand names in their official Japanese/Latin form.\n\n"),
}
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
def local_engine(settings: dict) -> str:
    """이 PC 에서 돌릴 수 있는 엔진(서버 실패 때 대신 쓴다)."""
    if settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY"):
        return "openai-api"
    if shutil.which("codex"):
        return "codex-cli"
    return "none"


def engine_name(settings: dict) -> str:
    if settings.get("pearl_token"):
        return "pearlstudio"
    return local_engine(settings)


def _call(prompt: str, settings: dict) -> str:
    """Pearl Studio 서버(로그인돼 있으면) → 실패하면 이 PC 의 OpenAI API 키 → codex CLI."""
    if settings.get("pearl_token"):
        try:
            return pearl.call_llm(prompt, SYSTEM, settings)
        except Exception as e:  # noqa: BLE001 — 서버가 안 되면 이 PC 엔진으로 계속
            if local_engine(settings) == "none":
                raise
            print(f"[translate] Pearl Studio 서버 실패, 이 PC 엔진으로 대신: {e}", flush=True)
    if local_engine(settings) == "openai-api":
        return _call_openai_api(prompt, settings)
    return _call_codex_cli(prompt, settings)


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
        if settings.get("codex_effort"):  # ~/.codex/config.toml 의 추론 강도를 이 앱에서만 덮어쓴다
            cmd[2:2] = ["-c", f'model_reasoning_effort="{settings["codex_effort"]}"']
        for attempt in (1, 2):
            r = subprocess.run(cmd, input=f"{SYSTEM}\n\n{prompt}", capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600, cwd=tempfile.gettempdir())
            content = Path(out_path).read_text(encoding="utf-8", errors="replace")
            if r.returncode == 0 and content.strip():
                return content
            # 로그인이 풀려 실패했으면 설정에 저장한 토큰으로 다시 로그인하고 한 번 더
            if attempt == 1 and settings.get("codex_token") and not codex_status().lower().startswith("logged in"):
                codex_login(settings["codex_token"])
                continue
            raise RuntimeError(f"codex CLI 실패(code={r.returncode}): {r.stderr[-400:]}")
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def codex_status() -> str:
    """«codex login status» 결과 한 줄(예: Logged in using ChatGPT). codex 가 없으면 빈 문자열."""
    codex = shutil.which("codex")
    if not codex:
        return ""
    try:
        r = subprocess.run([codex, "login", "status"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return "확인 실패"
    lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return lines[-1] if lines else "로그인 안 됨"


def codex_login(token: str) -> str:
    """토큰으로 codex 에 로그인한다(codex login --with-access-token). 토큰은 codex 가 ~/.codex 에 보관하고
    이 앱 설정에는 남기지 않는다. 성공하면 로그인 상태 문자열을 돌려준다."""
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("codex CLI 가 없습니다. 먼저 «npm install -g @openai/codex» 로 설치하세요.")
    r = subprocess.run([codex, "login", "--with-access-token"], input=token.strip(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"codex 토큰 로그인 실패: {(r.stderr or r.stdout).strip()[-300:]}")
    return codex_status()


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
        f"{FIDELITY}"
        f"{LANG_NOTES.get(lang, '')}"
        f"{gloss}"
        f"INPUT (JSON array):\n{json.dumps(texts, ensure_ascii=False)}\n\n"
        'OUTPUT (JSON only): {"items":["<localized 1>","<localized 2>", ...]}'
    )
    items = _parse_json(_call(prompt, settings)).get("items")
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


# ─── 내레이션 문장을 자막 조각으로 나누기 ─────────────────────────────────
SPLITS_PATH = DATA_DIR / "splits.json"
_BREAKS = set(" 　、。，,.!?！？…~〜")
_AFTER = set("はがをにでともへやのねよ")  # 일본어 조사 뒤는 끊어도 자연스럽다


def _kata(ch: str) -> bool:
    return "゠" <= ch <= "ヿ"  # 가타카나


def _even_split(sentence: str, fragments: list[str]) -> list[str]:
    """원래 조각 길이 비율대로 나누되, 끊는 자리는 가까운 공백·문장부호·조사 뒤로 옮긴다."""
    n, total = len(fragments), sum(max(1, len(f)) for f in fragments)
    cuts, acc = [], 0
    for f in fragments[:-1]:
        acc += max(1, len(f))
        ideal = round(len(sentence) * acc / total)
        best, best_d = ideal, 99
        for i in range(max(1, ideal - 4), min(len(sentence), ideal + 5)):
            prev, nxt = sentence[i - 1], sentence[i]
            good = prev in _BREAKS or (prev in _AFTER and not _kata(nxt))
            if good and abs(i - ideal) < best_d:
                best, best_d = i, abs(i - ideal)
        while 0 < best < len(sentence) and _kata(sentence[best - 1]) and _kata(sentence[best]):
            best += 1  # 가타카나 단어 중간은 자르지 않는다
        cuts.append(max(cuts[-1] + 1 if cuts else 1, min(best, len(sentence) - (n - len(cuts) - 1))))
    edges = [0, *cuts, len(sentence)]
    return [sentence[a:b].strip() for a, b in zip(edges, edges[1:])]


def _split_key(sentence: str, fragments: list[str], lang: str) -> str:
    return json.dumps([lang, sentence.replace("\n", " ").strip(), fragments], ensure_ascii=False)


def cached_split(sentence: str, fragments: list[str], lang: str) -> list[str] | None:
    """저장해 둔 나누기만 돌려준다(없으면 None). 조각이 하나면 문장 그대로."""
    if len(fragments) <= 1:
        return [sentence.replace("\n", " ").strip()]
    try:
        return json.loads(SPLITS_PATH.read_text(encoding="utf-8")).get(_split_key(sentence, fragments, lang))
    except (OSError, ValueError):
        return None


def split_sentence(sentence: str, fragments: list[str], lang: str, settings: dict) -> list[str]:
    """번역 문장 하나를 원래 자막 조각 수만큼 나눈다(이어 붙이면 문장과 같다). 결과는 저장해 두고 다시 쓴다.
    번역 엔진에게 원래 조각과 짝을 맞춰 끊게 하고, 틀리게 오면 길이 비율로 나눈다."""
    sentence = sentence.replace("\n", " ").strip()
    if len(fragments) <= 1:
        return [sentence]
    key = _split_key(sentence, fragments, lang)
    try:
        cache = json.loads(SPLITS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return cache[key]
    squash = lambda xs: "".join("".join(xs).split())  # noqa: E731 — 공백만 다른 건 같다고 본다
    parts = None
    if engine_name(settings) != "none":
        prompt = (
            f"A narration line was spoken as ONE sentence but is shown on screen as {len(fragments)} consecutive "
            f"caption chunks. Original chunks (in order):\n{json.dumps(fragments, ensure_ascii=False)}\n\n"
            f"Its {LANGUAGES.get(lang, lang)} version is:\n{json.dumps(sentence, ensure_ascii=False)}\n\n"
            f"Cut the {LANGUAGES.get(lang, lang)} sentence into EXACTLY {len(fragments)} consecutive chunks that "
            "line up with the original chunks in meaning and order. Cut only at natural word/phrase boundaries. "
            "Do NOT change, add, drop or reorder any character — joined together they must equal the sentence. "
            'OUTPUT (JSON only): {"parts":["...", "..."]}'
        )
        try:
            got = _parse_json(_call(prompt, settings)).get("parts")
            if isinstance(got, list) and len(got) == len(fragments) and squash(got) == squash([sentence]) \
                    and all(str(x).strip() for x in got):
                parts = [str(x).strip() for x in got]
        except Exception:  # noqa: BLE001 — 엔진이 실패해도 비율 나누기로 계속
            parts = None
    parts = parts or _even_split(sentence, fragments)
    with _lock:
        cache[key] = parts
        DATA_DIR.mkdir(exist_ok=True)
        tmp = SPLITS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, SPLITS_PATH)
    return parts


# ─── 화면을 넘는 제목·글자를 짧게 다시 번역 ───────────────────────────────
def shorten_to_fit(source: str, current: str, lang: str, max_chars: int, max_lines: int,
                   settings: dict, avoid: list[str] | None = None) -> str | None:
    """화면 폭을 넘는 번역문을 «한 줄 max_chars 자(전각 기준) · 최대 max_lines 줄» 안으로 다시 쓴다.
    뜻·말투는 유지하고 더 짧은 표현을 고른다. 실패하면 None — 맞는지는 부르는 쪽이 실제 폭으로 다시 잰다."""
    if engine_name(settings) == "none":
        return None
    prompt = (
        f"This is an on-screen title of a short-form video. It does NOT fit the screen width.\n"
        f"Original (Korean): {json.dumps(source, ensure_ascii=False)}\n"
        f"Current {LANGUAGES.get(lang, lang)}: {json.dumps(current, ensure_ascii=False)}\n"
        + (f"Already tried (still too wide): {json.dumps(avoid, ensure_ascii=False)}\n" if avoid else "")
        + f"Rewrite it in natural, punchy {LANGUAGES.get(lang, lang)} so that EVERY line has at most {max_chars} "
        f"full-width characters (count Latin letters/digits as half), using at most {max_lines} lines (\\n). "
        "Keep the key meaning, names and the hook. Prefer shorter native wording over cutting meaning. "
        'OUTPUT (JSON only): {"text": "..."}'
    )
    try:
        out = str(_parse_json(_call(prompt, settings)).get("text") or "").strip()
    except Exception:  # noqa: BLE001
        return None
    lines = [x.strip() for x in out.split("\n") if x.strip()]
    return "\n".join(lines) if lines and len(lines) <= max_lines else None
