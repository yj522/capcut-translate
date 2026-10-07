"""CapCut 드래프트 폴더 다루기 — 찾기·목록·복제·등록·삭제.

실측(CapCut 9.4, Windows) 폴더 구성:
  <root>/root_meta_info.json          모든 프로젝트 목록(all_draft_store) — CapCut 이 종료 때 다시 씀
  <root>/<이름>/draft_meta_info.json  draft_id · draft_name · draft_fold_path · draft_root_path
  <root>/<이름>/draft_content.json    본문. .bak · template-2.tmp 도 같은 본문
  <root>/<이름>/Timelines/<tid>/      같은 본문 3벌 + attachment/patch/mini_draft.json(클라우드 동기 캐시)
폴더 안 소재 경로는 '##_draftpath_placeholder_<uuid>_##/...' 자리표시자라 복사해도 안 고친다.
폴더 절대경로·이름이 박힌 곳은 draft_meta_info.json · root_meta_info.json · mini_draft.json 뿐.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# 본문(draft_content) 사본들 — 루트와 Timelines/<tid>/ 양쪽에 있다.
CONTENT_FILES = ("draft_content.json", "draft_content.json.bak", "template-2.tmp", "template.tmp")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def fwd(p: Path | str) -> str:
    """CapCut 이 JSON 에 쓰는 경로 모양(슬래시)."""
    return str(p).replace("\\", "/")


def long_path(p: Path) -> str:
    """Windows MAX_PATH(260) 회피용 \\\\?\\ 접두. 다른 OS 는 그대로."""
    s = str(p.resolve())
    if IS_WIN and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s


def read_json(p: Path) -> dict:
    with open(long_path(p), encoding="utf-8") as f:
        return json.load(f)


def write_json(p: Path, data: dict) -> None:
    """CapCut 처럼 공백 없는 한 줄 JSON 으로. 임시 파일에 쓰고 바꿔치기."""
    tmp = p.with_name(p.name + ".cl-tmp")
    with open(long_path(tmp), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(long_path(tmp), long_path(p))


# ─── 찾기 ──────────────────────────────────────────────────────────────────
def candidate_roots() -> list[Path]:
    home = Path.home()
    tail = Path("User Data") / "Projects" / "com.lveditor.draft"
    if IS_WIN:
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return [base / "CapCut" / tail, base / "JianyingPro" / tail]
    if IS_MAC:
        return [
            home / "Movies" / "CapCut" / tail,
            home / "Library" / "Containers" / "com.lemon.lvoverseas" / "Data" / "Movies" / "CapCut" / tail,
            home / "Movies" / "JianyingPro" / tail,
        ]
    return [home / "CapCut" / tail]


def find_root(saved: str | None = None) -> Path | None:
    if saved and Path(saved).is_dir():
        return Path(saved)
    for c in candidate_roots():
        if c.is_dir():
            return c
    return None


def capcut_running() -> bool:
    """CapCut 이 켜져 있으면 종료할 때 root_meta_info.json 을 덮어써 등록이 사라진다."""
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace",
                                 creationflags=0x08000000).stdout.lower()
            return '"capcut.exe"' in out or '"jianyingpro.exe"' in out
        out = subprocess.run(["pgrep", "-ix", "capcut|jianyingpro|videofusion"],
                             capture_output=True, text=True).stdout
        return bool(out.strip())
    except Exception:
        return False


def open_folder(p: Path) -> None:
    if IS_WIN:
        _open_folder_win(p)
    elif IS_MAC:
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def _open_folder_win(p: Path) -> bool:
    """탐색기로 열고 그 창을 앞으로 가져온다. 돌려주는 값: 앞으로 왔는지.

    서버는 백그라운드 프로세스라 그냥 열면 Windows 포그라운드 잠금 때문에 창이 브라우저 뒤에 숨는다.
    → 새로 생긴 탐색기 창(없으면 같은 이름 창)을 찾아 현재 앞 창의 입력 스레드에 붙어 SetForegroundWindow.
    """
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    def explorer_windows() -> dict[int, str]:
        found: dict[int, str] = {}
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(hwnd, cls, 64)
            if cls.value == "CabinetWClass" and u32.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(512)
                u32.GetWindowTextW(hwnd, title, 512)
                found[hwnd] = title.value
            return True
        u32.EnumWindows(proc(cb), 0)
        return found

    target = str(p.resolve())
    before = explorer_windows()
    subprocess.Popen(["explorer.exe", target], creationflags=0x08000000)

    hwnd = None
    for _ in range(40):  # 최대 4초
        time.sleep(0.1)
        now = explorer_windows()
        new = [h for h in now if h not in before]
        if new:
            hwnd = new[0]
            break
    if not hwnd:  # 이미 열려 있던 창을 탐색기가 재사용한 경우 — 제목(폴더 이름 또는 전체 경로)으로 찾는다
        hwnd = next((h for h, t in explorer_windows().items() if t in (p.name, target)), None)
    if not hwnd:
        return False

    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = u32.GetForegroundWindow()
    me = k32.GetCurrentThreadId()
    other = u32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(other and other != me and u32.AttachThreadInput(me, other, True))
    try:
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            u32.AttachThreadInput(me, other, False)
    if u32.GetForegroundWindow() != hwnd:  # 그래도 막히면 Alt 키를 한 번 눌러 잠금을 푼다
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)
        u32.SetForegroundWindow(hwnd)
    return u32.GetForegroundWindow() == hwnd


# ─── 목록 ──────────────────────────────────────────────────────────────────
def main_content_path(folder: Path) -> Path:
    """CapCut 9.x 는 Timelines/<main_timeline_id>/draft_content.json 이 주 본문.
    없으면(옛 버전) 루트 draft_content.json."""
    pj = folder / "Timelines" / "project.json"
    if pj.is_file():
        try:
            tid = read_json(pj).get("main_timeline_id")
            p = folder / "Timelines" / str(tid) / "draft_content.json"
            if tid and p.is_file():
                return p
        except Exception:
            pass
    return folder / "draft_content.json"


def all_content_files(folder: Path) -> list[Path]:
    out = [folder / n for n in CONTENT_FILES if (folder / n).is_file()]
    tl = folder / "Timelines"
    if tl.is_dir():
        for sub in tl.iterdir():
            if sub.is_dir():
                out += [sub / n for n in CONTENT_FILES if (sub / n).is_file()]
    return out


def list_projects(root: Path) -> list[dict]:
    items = []
    for d in root.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta_p = d / "draft_meta_info.json"
        if not meta_p.is_file():
            continue
        try:
            meta = read_json(meta_p)
        except Exception:
            continue
        items.append({
            "id": meta.get("draft_id") or d.name,
            "folder": d.name,
            "name": nfc(meta.get("draft_name") or d.name),
            "modified": int(meta.get("tm_draft_modified") or 0) // 1_000_000,
            "duration": round(int(meta.get("tm_duration") or 0) / 1_000_000, 1),
            "has_cover": (d / "draft_cover.jpg").is_file(),
        })
    items.sort(key=lambda x: x["modified"], reverse=True)
    return items


def folder_of(root: Path, draft_id: str) -> Path:
    for it in list_projects(root):
        if it["id"] == draft_id:
            return root / it["folder"]
    raise KeyError(f"프로젝트를 찾을 수 없습니다: {draft_id}")


# ─── 복제 ──────────────────────────────────────────────────────────────────
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_folder_name(root: Path, name: str) -> str:
    base = _BAD.sub("_", nfc(name)).strip().rstrip(".") or "copy"
    base = base[:80]
    cand, n = base, 2
    while (root / cand).exists():
        cand, n = f"{base} ({n})", n + 1
    return cand


def new_draft_id() -> str:
    return str(uuid.uuid4()).upper()


def clone(root: Path, src: Path, new_name: str, transform=None, progress=None,
          extra_files: dict[str, Path] | None = None) -> dict:
    """src 프로젝트를 root 아래 새 폴더로 복제한다. 원본은 읽기만 한다.

    transform(draft_dict) 가 주어지면 모든 본문 사본에 적용한다(번역 반영).
    extra_files = {사본 폴더 안 상대경로: 원본 파일} 은 복사 뒤 넣는다(번역 음성 wav).
    임시 폴더에서 끝낸 뒤 이름을 바꾸므로 실패해도 반쯤 된 프로젝트가 남지 않는다.
    """
    step = progress or (lambda *_: None)
    folder = safe_folder_name(root, new_name)
    dest = root / folder
    tmp = root / f".cl-tmp-{uuid.uuid4().hex[:8]}"
    try:
        step("copy", f"폴더 복사 중 · {src.name}")
        shutil.copytree(long_path(src), long_path(tmp))
        for rel, f in (extra_files or {}).items():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(long_path(f), long_path(tmp / rel))

        step("rewrite", "프로젝트 정보 다시 쓰는 중")
        old_fold = fwd(src)
        new_fold = fwd(dest)
        new_id = new_draft_id()
        now_us = int(time.time() * 1_000_000)
        meta_p = tmp / "draft_meta_info.json"
        meta = read_json(meta_p)
        old_name = meta.get("draft_name") or src.name
        meta.update({
            "draft_id": new_id,
            "draft_name": nfc(new_name),
            "draft_fold_path": new_fold,
            "draft_root_path": fwd(root),
            "tm_draft_create": now_us,
            "tm_draft_modified": now_us,
            "draft_cloud_last_action_download": False,
            "tm_draft_cloud_completed": "",
            "tm_draft_cloud_entry_id": -1,
            "tm_draft_cloud_modified": 0,
            "tm_draft_cloud_parent_entry_id": -1,
            "tm_draft_cloud_space_id": -1,
            "tm_draft_cloud_user_id": -1,
        })
        write_json(meta_p, meta)

        # 클라우드 동기 캐시는 원본 경로·이름·옛 글자를 들고 있다 — 사본에선 지운다(CapCut 이 다시 만든다).
        tl = tmp / "Timelines"
        if tl.is_dir():
            for patch in tl.glob("*/attachment/patch"):
                shutil.rmtree(long_path(patch), ignore_errors=True)

        if transform:
            files = all_content_files(tmp)
            for i, p in enumerate(files, 1):
                step("apply", f"텍스트 반영 중 · {i}/{len(files)} · {p.relative_to(tmp)}")
                try:
                    data = read_json(p)
                except Exception:
                    continue  # JSON 이 아닌 사본(드물게 비어 있음)은 건너뜀
                transform(data)
                write_json(p, data)

            # 음성이 길어 영상을 늘렸으면 목록에 보이는 길이도 맞춘다
            try:
                dur = int(read_json(main_content_path(tmp)).get("duration") or 0)
            except Exception:
                dur = 0
            if dur and dur != meta.get("tm_duration"):
                meta["tm_duration"] = dur
                write_json(meta_p, meta)

        step("register", "CapCut 목록에 등록 중")
        os.rename(long_path(tmp), long_path(dest))
        register(root, dest, meta, old_fold)
        return {"id": new_id, "folder": folder, "name": nfc(new_name), "old_name": old_name}
    except Exception:
        shutil.rmtree(long_path(tmp), ignore_errors=True)
        raise


def register(root: Path, dest: Path, meta: dict, old_fold: str) -> None:
    """root_meta_info.json 의 all_draft_store 맨 앞에 새 항목을 넣는다(백업 후)."""
    rp = root / "root_meta_info.json"
    if not rp.is_file():
        return  # 없으면 CapCut 이 폴더를 훑어 만든다
    data = read_json(rp)
    backup_dir = Path(__file__).parent / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rp, backup_dir / f"root_meta_info.{time.strftime('%Y%m%d-%H%M%S')}.json")

    store = data.setdefault("all_draft_store", [])
    template = next((e for e in store if e.get("draft_fold_path") == old_fold), None)
    entry = dict(template) if template else {}
    fold = fwd(dest)
    entry.update({
        "draft_cover": f"{fold}\\draft_cover.jpg" if IS_WIN else f"{fold}/draft_cover.jpg",
        "draft_fold_path": fold,
        "draft_id": meta["draft_id"],
        "draft_json_file": f"{fold}\\draft_content.json" if IS_WIN else f"{fold}/draft_content.json",
        "draft_name": meta["draft_name"],
        "draft_root_path": fwd(root),
        "tm_draft_create": meta["tm_draft_create"],
        "tm_draft_modified": meta["tm_draft_modified"],
        "tm_draft_removed": 0,
        "tm_duration": meta.get("tm_duration", entry.get("tm_duration", 0)),
        "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False,
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
    })
    store.insert(0, entry)
    if isinstance(data.get("draft_ids"), int):
        data["draft_ids"] += 1
    write_json(rp, data)


def remove(root: Path, folder: str) -> None:
    """앱이 만든 사본 삭제: 폴더 + root_meta_info 항목."""
    dest = root / folder
    fold = fwd(dest)
    rp = root / "root_meta_info.json"
    if rp.is_file():
        data = read_json(rp)
        data["all_draft_store"] = [e for e in data.get("all_draft_store", [])
                                   if e.get("draft_fold_path") != fold]
        write_json(rp, data)
    if dest.is_dir():
        shutil.rmtree(long_path(dest))
