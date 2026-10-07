"""CapCut Translate — 로컬 전용 앱. 실행: python app.py (외부 패키지 없음)

- 브라우저 화면(ui/) + 이 파일의 JSON API. 127.0.0.1 에만 열린다.
- .py 를 저장하면 서버가 저절로 다시 뜬다(감시 프로세스). ui/ 는 새로고침만.
- 설정·번역 캐시·사본 대장·백업은 data/ 에 쌓인다(git 제외).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).parent
for _s in (sys.stdout, sys.stderr):  # Windows 콘솔(cp949)에서 한글·기호 출력으로 죽지 않게
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass
sys.path.insert(0, str(HERE))

import drafts  # noqa: E402
import fonts  # noqa: E402
import localize  # noqa: E402
import translate  # noqa: E402
import tts  # noqa: E402

PORT = int(os.environ.get("CL_PORT", "3177"))
DATA = HERE / "data"
SETTINGS_PATH = DATA / "settings.json"
COPIES_PATH = DATA / "copies.json"
UI = HERE / "ui"


# ─── 설정·사본 대장 ────────────────────────────────────────────────────────
def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(path: Path, data) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def settings() -> dict:
    return load(SETTINGS_PATH, {})


def root() -> Path:
    r = drafts.find_root(settings().get("draft_root"))
    if not r:
        raise ApiError(400, "CapCut 프로젝트 폴더를 찾지 못했습니다. 설정에서 경로를 지정하세요.")
    return r


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ─── 백그라운드 작업 ───────────────────────────────────────────────────────
JOBS: dict[str, dict] = {}


def start_job(title: str, fn, total: int) -> str:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "title": title, "state": "running", "step": 0, "total": total,
           "label": "준비 중", "detail": "", "result": None, "error": None, "started": time.time()}
    JOBS[jid] = job

    def run():
        try:
            job["result"] = fn(job)
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job["state"], job["error"] = "failed", str(e)
    threading.Thread(target=run, daemon=True).start()
    return jid


def voice_items(draft: dict) -> list[dict]:
    """바꿀 수 있는 음성: CapCut 글자 읽어주기(kind=tts) + 직접 넣은 내레이션 파일 구간(kind=narration)."""
    voices = settings().get("tts_voices") or {}
    items = [dict(t, kind="tts") for t in localize.tts_items(draft)] + localize.narration_items(draft)
    return [dict(t, voice=voices.get(t["tone"], "")) for t in items]


def project_texts(folder: Path) -> tuple[list[str], dict]:
    draft = drafts.read_json(drafts.main_content_path(folder))
    items = localize.extract(draft)
    vlist = voice_items(draft)
    narr = [v for v in vlist if v["kind"] == "narration" and v["text"] and v.get("parts")]
    # 내레이션 구간 자막 조각은 문장 번역을 나눠 쓰므로 따로 번역하지 않는다(그 구간에만 나오는 조각이면)
    narr_ids = {p["material_id"] for v in narr for p in v["parts"]}
    ids_by_text: dict[str, set] = {}
    for it in items:
        ids_by_text.setdefault(it["text"], set()).add(it["id"])
    uniq: list[str] = []
    for it in items:
        t = it["text"]
        if t not in uniq and localize.needs_translation(t) and not ids_by_text[t] <= narr_ids:
            uniq.append(t)
    for v in narr:  # 내레이션 대본(자막을 이은 문장)은 통째로 번역해 표에서 고칠 수 있게
        if v["text"] not in uniq:
            uniq.append(v["text"])
    info = {"text_count": len(items), "subtitle_count": sum(1 for i in items if i["type"] == "subtitle"),
            "tts_count": len(vlist), "tts": vlist,
            "narration": [{"text": v["text"], "start": v["start"], "parts": [p["text"] for p in v["parts"]]}
                          for v in narr]}
    return uniq, info


def narration_overrides(draft: dict, lang: str, mapping: dict[str, str], compute: bool = True) -> dict[str, str]:
    """내레이션 구간 자막 → 문장 번역을 원래 조각 수로 나눈 조각 {자막 material id: 조각}.
    음성을 바꾸든 안 바꾸든 화면 자막은 늘 내레이션 문장과 똑같이 맞춘다.
    compute=False 면 저장된 나누기만 쓴다(번역 엔진을 부르지 않음)."""
    out: dict[str, str] = {}
    for it in localize.narration_items(draft):
        sentence = mapping.get(it["text"]) if it["text"] else None
        if not sentence or not it.get("parts"):
            continue
        frags = [p["text"] for p in it["parts"]]
        pieces = (translate.split_sentence(sentence, frags, lang, settings()) if compute
                  else translate.cached_split(sentence, frags, lang))
        if pieces:
            out.update({p["material_id"]: piece for p, piece in zip(it["parts"], pieces)})
    return out


def fit_translations(draft: dict, lang: str, mapping: dict[str, str], progress=None) -> list[str]:
    """화면 폭을 넘는 제목·글자(자막 조각 제외)는 크기를 줄이기 전에 먼저 짧게 다시 번역한다.
    바꿀 글꼴로 실제 폭을 재고, 넘치면 «한 줄 N자 · 원래 줄 수 + 1 줄» 한도로 다시 번역해 다시 잰다(두 번까지).
    맞는 번역은 번역 저장소에 넣는다 — 표에서 보이고 고칠 수 있다. mapping 도 바꾼다. 돌려주는 값: 알릴 말."""
    chosen = project_fonts(draft, lang)
    titles = localize.font_titles(draft)
    clips = {s.get("material_id"): float(((s.get("clip") or {}).get("scale") or {}).get("x") or 1.0)
             for t in draft.get("tracks") or [] for s in t.get("segments") or []}
    notes = []
    for tm in (draft.get("materials") or {}).get("texts") or []:
        text, inner = localize.parse_content(tm.get("content"))
        cur = mapping.get(text)
        if tm.get("type") == "subtitle" or not inner or not cur:
            continue
        first = next((st.get("font") or {} for st in inner.get("styles") or [] if (st.get("font") or {}).get("path")), {})
        if not first:
            continue
        c = chosen.get(titles.get(first.get("id"), "")) or chosen.get(first.get("id")) or {}
        new_path, k = c.get("path") or first["path"], float(c.get("scale") or 1.0)
        size, clip = float(tm.get("font_size") or 0), clips.get(tm.get("id"), 1.0)
        try:
            limit = max(fonts.text_em(first["path"], text) * size * clip, localize.SCREEN_EM * localize.FIT_FILL)
            width = lambda t: fonts.text_em(new_path, t) * size * k * clip  # noqa: E731
            lines = text.count("\n") + 1
            # 1) 원본과 같은 줄 수 — 글자는 마지막 단계에서 85% 까지 줄일 수 있으니 그만큼 한도를 넉넉히
            # 2) 그래도 안 되면 한 줄 더(그때는 fit_texts 가 줄 늘어난 만큼 조금 줄인다)
            room = 1 / localize.FIT_MIN_MEASURED
            # 85% 로 줄이면 들어가는 번역(앞서 맞춘 것·표에서 고친 것)은 그대로 둔다 — 만들 때마다 바뀌지 않게
            if width(cur) <= limit * room * 1.02 and cur.count("\n") + 1 <= lines:
                continue
            if progress:
                progress(f"화면을 넘는 글자를 짧게 다시 번역하는 중 · «{cur.splitlines()[0][:10]}…»")
            tried, done = [], False
            for max_lines, slack in ((lines, room), (lines, room), (lines + 1, 1.0)):
                budget = int(limit * slack / (size * k * clip)) - (1 if tried and max_lines == lines else 0)
                cand = translate.shorten_to_fit(text, cur, lang, budget, max_lines, settings(), tried)
                if cand and width(cand) <= limit * slack * 1.02:
                    translate.save_entries(lang, {text: cand})
                    mapping[text] = cand
                    notes.append(f"«{cur.splitlines()[0][:12]}…» 가 화면보다 넓어 짧게 다시 번역: «{cand.replace(chr(10), ' / ')}»")
                    done = True
                    break
                if cand:
                    tried.append(cand)
            if not done:
                notes.append(f"«{cur.splitlines()[0][:12]}…» 를 화면에 맞게 줄이지 못했습니다 — 번역 표에서 짧게 고쳐 주세요")
        except Exception:  # noqa: BLE001 — 글꼴을 못 읽으면 다음 단계(크기 줄이기)에 맡긴다
            continue
    return notes


def project_fonts(draft: dict, lang: str) -> dict[str, dict]:
    """이 프로젝트에 쓰인 글꼴 중 짝이 정해진 것 → {원본 글꼴 이름: {"path", "scale"}}. 글꼴 파일은 없으면 내려받는다."""
    fmap = fonts.font_map(settings(), lang)
    out = {}
    for f in localize.used_fonts(draft):
        c = fmap.get(f["key"]) or fmap.get(f["id"])
        if c:
            out[f["key"]] = {"path": str(fonts.ensure(lang, c["font"])).replace("\\", "/"),
                             "scale": float(c.get("scale") or 1.0)}
    return out


_PLACEHOLDER = re.compile(r"^##_draftpath_placeholder_[^/]*_##/")


def make_tts(folder: Path, lang: str, mapping: dict[str, str], progress=None) -> tuple[dict, dict, list[str]]:
    """번역문으로 음성을 만든다 → (repl {id: {file, duration, name, kind}}, extra_files, 건너뛴 이유들).
    목소리를 정하지 않은 음성, 번역문이 없는 음성은 원래대로 둔다."""
    s = settings()
    draft = drafts.read_json(drafts.main_content_path(folder))
    paths = {a.get("id"): str(a.get("path") or "") for a in draft.get("materials", {}).get("audios") or []}
    repl, files, skipped = {}, {}, []
    items = voice_items(draft)
    for i, it in enumerate(items, 1):
        label = it["tone"] if it["kind"] == "tts" else f"{it['tone']} {it['start'] / 1e6:.1f}초"
        text = mapping.get(it["text"]) if it["text"] else None
        if not it["voice"]:
            skipped.append(f"«{label}» 목소리를 정하지 않아 원래 음성 그대로")
            continue
        if not text:
            skipped.append(f"«{label}» 대본 번역이 없어 원래 음성 그대로")
            continue
        src_path = paths.get(it["id"] if it["kind"] == "tts" else it["material_id"], "").replace("\\", "/")
        if not _PLACEHOLDER.match(src_path):
            skipped.append(f"«{label}» 음성 파일이 프로젝트 폴더 밖에 있어 원래 음성 그대로")
            continue
        if progress:
            progress(f"음성 만드는 중 · {i}/{len(items)} · {label}")
        wav = tts.synthesize(text, it["voice"], lang, s)
        name = f"cl_{lang}_{wav.stem}.wav"
        rel = _PLACEHOLDER.sub("", src_path)  # 프로젝트 폴더 안 상대경로 — 새 파일은 원래 파일 옆에 둔다
        rel_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        files[f"{rel_dir}/{name}".lstrip("/")] = wav
        repl[it["id"]] = {"file": name, "duration": tts.duration_us(wav), "name": text.replace("\n", " "),
                          "kind": it["kind"]}
    return repl, files, skipped


def job_translate(draft_id: str, langs: list[str]):
    folder = drafts.folder_of(root(), draft_id)
    texts, _ = project_texts(folder)
    draft = drafts.read_json(drafts.main_content_path(folder))

    def fn(job):
        out = {}
        for i, lang in enumerate(langs, 1):
            job.update(step=i, label=f"{i}/{len(langs)} · {translate.LANGUAGE_LABELS.get(lang, lang)}")
            out[lang] = translate.translate(texts, lang, settings(),
                                            progress=lambda d: job.update(detail=d))
            fit_translations(draft, lang, out[lang], progress=lambda d: job.update(detail=d))
            job.update(detail="내레이션 문장을 자막 조각으로 나누는 중")
            narration_overrides(draft, lang, out[lang])
        return {"translations": out}
    return start_job("번역 미리보기", fn, len(langs))


def job_copies(draft_id: str, langs: list[str], pattern: str, with_tts: bool = False):
    r = root()
    src = drafts.folder_of(r, draft_id)
    texts, _ = project_texts(src)
    src_meta = drafts.read_json(src / "draft_meta_info.json")
    src_name = drafts.nfc(src_meta.get("draft_name") or src.name)
    # 단계: 언어마다 [번역, 복사, 정보, 반영, 등록]
    stages = ["translate", "voice", "copy", "rewrite", "apply", "register"]

    def fn(job):
        made = []
        for li, lang in enumerate(langs):
            label = translate.LANGUAGE_LABELS.get(lang, lang)
            base = li * len(stages)

            def step(stage, detail, _base=base, _li=li, _label=label):
                if drafts.capcut_running() and stage == "register":
                    raise RuntimeError("CapCut 이 켜져 있습니다. CapCut 을 닫고 다시 시도하세요.")
                job.update(step=_base + stages.index(stage) + 1,
                           label=f"{_li + 1}/{len(langs)} · {_label}", detail=detail)

            step("translate", "번역 확인 중")
            mapping = translate.translate(texts, lang, settings(), progress=lambda d: job.update(detail=d))
            repl, files, notes = {}, {}, []
            if with_tts:
                step("voice", "음성 확인 중")
                repl, files, notes = make_tts(src, lang, mapping, progress=lambda d: job.update(detail=d))
            job.update(detail="내레이션 구간 자막을 문장에 맞추는 중")
            src_draft = drafts.read_json(drafts.main_content_path(src))
            if settings().get("auto_fit", True):
                notes.extend(fit_translations(src_draft, lang, mapping, progress=lambda d: job.update(detail=d)))
            overrides = narration_overrides(src_draft, lang, mapping)
            job.update(detail="글꼴 준비 중")
            chosen = project_fonts(src_draft, lang)
            fit = settings().get("auto_fit", True)

            def transform(d, m=mapping, rp=repl, ov=overrides, ch=chosen, ft=fit):
                before = localize.snapshot_texts(d)
                localize.apply(d, m, ov)
                if ch:
                    localize.apply_fonts(d, ch)
                if ft:  # 글꼴까지 바꾼 뒤 실제 글자 폭으로 재서 화면을 넘는 것만 줄인다
                    els = float(settings().get("extra_line_scale", 0.85))  # 줄이 늘면 한 줄마다 이 배율로
                    notes.extend(w for w in localize.fit_texts(d, before, fonts.text_em, els) if w not in notes)
                if rp:
                    top = tts.max_speed(settings())
                    warns = localize.apply_tts(d, {k: v for k, v in rp.items() if v["kind"] == "tts"}, top)
                    warns += localize.apply_narration(d, {k: v for k, v in rp.items() if v["kind"] == "narration"}, top)
                    notes.extend(w for w in warns if w not in notes)
            name = (pattern or "{name} [{lang}]").replace("{name}", src_name).replace("{lang}", lang.upper())
            res = drafts.clone(r, src, name, transform=transform, progress=step, extra_files=files)
            res.update(source_id=draft_id, lang=lang, created=int(time.time()), voices=len(repl), notes=notes)
            copies = load(COPIES_PATH, [])
            copies.append(res)
            save(COPIES_PATH, copies)
            made.append(res)
        return {"copies": made}
    return start_job("언어별 복제", fn, len(langs) * len(stages))


# ─── API ───────────────────────────────────────────────────────────────────
def api(method: str, path: str, body: dict):
    parts = [unquote(p) for p in path.strip("/").split("/")][1:]  # 'api' 제거
    s = settings()

    if parts == ["state"]:
        r = drafts.find_root(s.get("draft_root"))
        return {"root": str(r) if r else None, "candidates": [str(c) for c in drafts.candidate_roots()],
                "capcut_running": drafts.capcut_running(), "engine": translate.engine_name(s),
                "has_key": bool(s.get("openai_api_key")), "openai_model": s.get("openai_model") or "gpt-4.1-mini",
                "name_pattern": s.get("name_pattern") or "{name} [{lang}]",
                "has_typecast": bool(tts.api_key(s)), "typecast_model": tts.model(s),
                "languages": [{"code": k, "label": translate.LANGUAGE_LABELS[k]} for k in translate.LANGUAGES],
                "platform": sys.platform}

    if parts == ["settings"] and method == "POST":
        if "auto_fit" in body:  # 켜고 끄는 값은 문자열이 아니라서 따로
            s["auto_fit"] = bool(body.pop("auto_fit"))
        for k in ("draft_root", "openai_api_key", "openai_model", "name_pattern", "codex_model",
                  "typecast_api_key", "typecast_model", "tts_lufs", "tts_max_speed"):
            if k in body:
                v = (body[k] or "").strip()
                if v:
                    s[k] = v
                else:
                    s.pop(k, None)
        if s.get("draft_root") and not Path(s["draft_root"]).is_dir():
            raise ApiError(400, "그 경로에 폴더가 없습니다.")
        save(SETTINGS_PATH, s)
        return {"ok": True}

    if parts == ["projects"]:
        r = root()
        copies = load(COPIES_PATH, [])
        by_folder = {c["folder"]: c for c in copies}
        items = drafts.list_projects(r)
        for it in items:
            c = by_folder.get(it["folder"])
            it["copy_of"] = c["source_id"] if c else None
            it["lang"] = c["lang"] if c else None
        return {"projects": items}

    if len(parts) == 3 and parts[0] == "projects" and parts[2] == "texts":
        folder = drafts.folder_of(root(), parts[1])
        texts, info = project_texts(folder)
        cache = translate.load_cache()
        for n in info["narration"]:  # 표에 «실제로 들어갈 자막 조각» 을 보여 준다(저장된 나누기만)
            n["pieces"] = {lang: translate.cached_split(m[n["text"]], n["parts"], lang)
                           for lang, m in cache.items() if n["text"] in m}
        return {"texts": texts, **info,
                "translations": {lang: {t: m[t] for t in texts if t in m} for lang, m in cache.items()}}

    if parts == ["translate"] and method == "POST":
        return {"job": job_translate(body["id"], body["langs"])}

    if parts == ["translation"] and method == "POST":
        translate.save_entries(body["lang"], {body["src"]: body["dst"]})
        return {"ok": True}

    if len(parts) == 4 and parts[0] == "projects" and parts[2] == "fonts":  # 쓰인 글꼴과 언어별 짝
        folder = drafts.folder_of(root(), parts[1])
        draft = drafts.read_json(drafts.main_content_path(folder))
        fmap = fonts.font_map(s, parts[3])
        return {"fonts": [dict(f, map=fmap.get(f["key"]) or fmap.get(f["id"]) or {})
                          for f in localize.used_fonts(draft)],
                "choices": fonts.choices(parts[3]), "auto_fit": s.get("auto_fit", True)}

    if parts == ["font"] and method == "POST":  # 원본 글꼴 하나의 짝(글꼴·크기 배율)을 저장
        m = s.setdefault("font_map", {}).setdefault(body["lang"], {})
        m[body["key"]] = {"font": body.get("font") or "", "scale": float(body.get("scale") or 1.0)}
        save(SETTINGS_PATH, s)
        return {"ok": True}

    if parts == ["split"] and method == "POST":  # 내레이션 문장을 고친 뒤 자막 조각을 다시 나눈다
        folder = drafts.folder_of(root(), body["id"])
        draft = drafts.read_json(drafts.main_content_path(folder))
        narration_overrides(draft, body["lang"], translate.load_cache().get(body["lang"], {}))
        return {"ok": True}

    if parts == ["copies"] and method == "POST":
        if drafts.capcut_running():
            raise ApiError(409, "CapCut 이 켜져 있습니다. CapCut 을 닫은 뒤 만드세요 (CapCut 이 종료할 때 목록 파일을 덮어씁니다).")
        if not body.get("langs"):
            raise ApiError(400, "만들 언어를 고르세요.")
        if body.get("tts") and not tts.api_key(s):
            raise ApiError(400, "음성까지 바꾸려면 설정에서 Typecast API 키를 넣으세요.")
        return {"job": job_copies(body["id"], body["langs"], body.get("pattern") or "", bool(body.get("tts")))}

    if parts == ["tts", "voices"]:
        return {"voices": tts.voices(s)}

    if parts == ["tts", "voice"] and method == "POST":  # CapCut 목소리 이름 → Typecast 목소리
        m = s.setdefault("tts_voices", {})
        if body.get("voice"):
            m[body["tone"]] = body["voice"]
        else:
            m.pop(body["tone"], None)
        save(SETTINGS_PATH, s)
        return {"ok": True}

    if parts == ["tts", "preview"] and method == "POST":  # 번역문 한 줄을 들어 보기
        wav = tts.synthesize(body["text"], body["voice"], body["lang"], s)
        return {"url": "/tts-audio/" + wav.name, "duration": tts.duration_us(wav) / 1e6}

    if len(parts) == 2 and parts[0] == "jobs":
        job = JOBS.get(parts[1])
        if not job:
            raise ApiError(404, "작업이 없습니다(서버가 다시 시작됐을 수 있음).")
        return job

    if parts == ["delete"] and method == "POST":
        if drafts.capcut_running():
            raise ApiError(409, "CapCut 을 닫은 뒤 삭제하세요.")
        copies = load(COPIES_PATH, [])
        c = next((c for c in copies if c["id"] == body["id"]), None)
        if not c:
            raise ApiError(400, "이 앱이 만든 사본만 지울 수 있습니다.")
        drafts.remove(root(), c["folder"])
        save(COPIES_PATH, [x for x in copies if x["id"] != body["id"]])
        return {"ok": True}

    if parts == ["open"] and method == "POST":
        r = root()
        drafts.open_folder(drafts.folder_of(r, body["id"]) if body.get("id") else r)
        return {"ok": True}

    raise ApiError(404, f"없는 API: {method} {path}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _handle(self, method: str):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                return self._json(200, api(method, path, body))
            if path.startswith("/font-file/"):  # 글꼴 미리보기용 — data/fonts/<언어>/<파일>
                lang, _, name = unquote(path[11:]).partition("/")
                p = fonts.FONT_DIR / Path(lang).name / Path(name).name
                return self._send(200, p.read_bytes(), "font/ttf") if p.is_file() else self._send(404, b"", "text/plain")
            if path.startswith("/tts-audio/"):
                p = tts.TTS_DIR / Path(unquote(path[11:])).name
                return self._send(200, p.read_bytes(), "audio/wav") if p.is_file() else self._send(404, b"", "text/plain")
            if path.startswith("/cover/"):
                folder = drafts.folder_of(root(), unquote(path[7:]))
                p = folder / "draft_cover.jpg"
                return self._send(200, p.read_bytes(), "image/jpeg") if p.is_file() else self._send(404, b"", "text/plain")
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (UI / name).resolve()
            if UI.resolve() in f.parents and f.is_file():
                ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                         ".svg": "image/svg+xml"}.get(f.suffix, "application/octet-stream")
                return self._send(200, f.read_bytes(), ctype + "; charset=utf-8")
            self._send(404, b"not found", "text/plain")
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except KeyError as e:
            self._json(404, {"error": str(e).strip("'\"")})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": str(e)})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


# ─── 실행 + 저장하면 다시 뜨기 ─────────────────────────────────────────────
def serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"CapCut Translate — http://127.0.0.1:{PORT}  (끄려면 이 창을 닫거나 Ctrl+C)", flush=True)
    httpd.serve_forever()


def py_mtimes() -> dict:
    return {p: p.stat().st_mtime for p in HERE.glob("*.py")}


def supervise():
    """자식 서버를 띄우고 .py 가 바뀌면 다시 띄운다. 브라우저는 처음 한 번만 연다."""
    env = dict(os.environ, CL_CHILD="1", PYTHONIOENCODING="utf-8")
    opened = False
    while True:
        child = subprocess.Popen([sys.executable, __file__], env=env)
        if not opened and not os.environ.get("CL_NO_BROWSER"):
            time.sleep(0.8)
            webbrowser.open(f"http://127.0.0.1:{PORT}")
            opened = True
        before = py_mtimes()
        try:
            while child.poll() is None and py_mtimes() == before:
                time.sleep(0.7)
        except KeyboardInterrupt:
            child.terminate()
            return
        if child.poll() is None:
            print("코드가 바뀌어 다시 시작합니다…", flush=True)
            child.terminate()
            child.wait()
        else:
            print("서버가 멈췄습니다. 코드를 고쳐 저장하면 다시 시작합니다.", flush=True)
            while py_mtimes() == before:
                time.sleep(0.7)


if __name__ == "__main__":
    if os.environ.get("CL_CHILD"):
        serve()
    else:
        supervise()
