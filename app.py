"""CapCut 언어 복제 — 로컬 전용 앱. 실행: python app.py (외부 패키지 없음)

- 브라우저 화면(ui/) + 이 파일의 JSON API. 127.0.0.1 에만 열린다.
- .py 를 저장하면 서버가 저절로 다시 뜬다(감시 프로세스). ui/ 는 새로고침만.
- 설정·번역 캐시·사본 대장·백업은 data/ 에 쌓인다(git 제외).
"""
from __future__ import annotations

import json
import os
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
import localize  # noqa: E402
import translate  # noqa: E402

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


def project_texts(folder: Path) -> tuple[list[str], dict]:
    draft = drafts.read_json(drafts.main_content_path(folder))
    items = localize.extract(draft)
    uniq: list[str] = []
    for it in items:
        if it["text"] not in uniq and localize.needs_translation(it["text"]):
            uniq.append(it["text"])
    info = {"text_count": len(items), "subtitle_count": sum(1 for i in items if i["type"] == "subtitle"),
            "tts_count": localize.tts_linked_count(draft)}
    return uniq, info


def job_translate(draft_id: str, langs: list[str]):
    folder = drafts.folder_of(root(), draft_id)
    texts, _ = project_texts(folder)

    def fn(job):
        out = {}
        for i, lang in enumerate(langs, 1):
            job.update(step=i, label=f"{i}/{len(langs)} · {translate.LANGUAGE_LABELS.get(lang, lang)}")
            out[lang] = translate.translate(texts, lang, settings(),
                                            progress=lambda d: job.update(detail=d))
        return {"translations": out}
    return start_job("번역 미리보기", fn, len(langs))


def job_copies(draft_id: str, langs: list[str], pattern: str):
    r = root()
    src = drafts.folder_of(r, draft_id)
    texts, _ = project_texts(src)
    src_meta = drafts.read_json(src / "draft_meta_info.json")
    src_name = drafts.nfc(src_meta.get("draft_name") or src.name)
    # 단계: 언어마다 [번역, 복사, 정보, 반영, 등록]
    stages = ["translate", "copy", "rewrite", "apply", "register"]

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
            name = (pattern or "{name} [{lang}]").replace("{name}", src_name).replace("{lang}", lang.upper())
            res = drafts.clone(r, src, name, transform=lambda d, m=mapping: localize.apply(d, m),
                               progress=step)
            res.update(source_id=draft_id, lang=lang, created=int(time.time()))
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
                "languages": [{"code": k, "label": translate.LANGUAGE_LABELS[k]} for k in translate.LANGUAGES],
                "platform": sys.platform}

    if parts == ["settings"] and method == "POST":
        for k in ("draft_root", "openai_api_key", "openai_model", "name_pattern", "codex_model"):
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
        return {"texts": texts, **info,
                "translations": {lang: {t: m[t] for t in texts if t in m} for lang, m in cache.items()}}

    if parts == ["translate"] and method == "POST":
        return {"job": job_translate(body["id"], body["langs"])}

    if parts == ["translation"] and method == "POST":
        translate.save_entries(body["lang"], {body["src"]: body["dst"]})
        return {"ok": True}

    if parts == ["copies"] and method == "POST":
        if drafts.capcut_running():
            raise ApiError(409, "CapCut 이 켜져 있습니다. CapCut 을 닫은 뒤 만드세요 (CapCut 이 종료할 때 목록 파일을 덮어씁니다).")
        if not body.get("langs"):
            raise ApiError(400, "만들 언어를 고르세요.")
        return {"job": job_copies(body["id"], body["langs"], body.get("pattern") or "")}

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
    print(f"CapCut 언어 복제 — http://127.0.0.1:{PORT}  (끄려면 이 창을 닫거나 Ctrl+C)", flush=True)
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
