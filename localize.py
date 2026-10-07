"""CapCut 드래프트 JSON 안의 텍스트를 꺼내고(extract) 번역문을 다시 넣는다(apply).

실측(CapCut 9.4, draft new_version 185.0.0):
- 텍스트는 draft["materials"]["texts"][*]
- content 는 대개 JSON 문자열 {"text": "...", "styles": [{"range": [s, e], ...}]}
  range 단위는 UTF-16 — '🍒체리돌' 은 [0, 5](이모지가 2칸). 코드포인트로 적힌 옛 글자도 있어 글자마다 판단한다.
- 자동 자막(type == "subtitle")은 base_content(같은 모양) 와 words(단어별 타이밍)도 갖는다.
  번역하면 단어가 안 맞으므로 words 는 비운다.
- text_to_audio(글자 읽어주기) 오디오는 text_id 로 텍스트에 붙는다 — 음성은 원어 그대로 남는다.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any


def parse_content(content: Any) -> tuple[str, dict | None]:
    """content → (보이는 글자, rich dict 또는 None). 평문이면 inner 가 None."""
    if isinstance(content, str):
        s = content.strip()
        if s.startswith("{") and '"text"' in s:
            try:
                inner = json.loads(s)
                if isinstance(inner, dict) and isinstance(inner.get("text"), str):
                    return inner["text"], inner
            except ValueError:
                pass
        return content, None
    return "", None


def u16len(s: str) -> int:
    """UTF-16 길이 — 이모지 같은 BMP 밖 글자는 2칸."""
    return len(s.encode("utf-16-le")) // 2


def _range_unit(old: str, styles: list) -> str:
    """styles range 가 세는 단위. 실측: CapCut 9.4 는 UTF-16(«🍒체리돌» = [0, 5]).
    옛 글자가 코드포인트로 끝나 있으면(«🍒체리돌» = [0, 4]) 그 단위를 따른다. 이모지가 없으면 둘은 같다."""
    ends = {st["range"][1] for st in styles if isinstance(st, dict) and isinstance(st.get("range"), list)
            and len(st["range"]) == 2}
    if len(old) != u16len(old) and len(old) in ends and u16len(old) not in ends:
        return "cp"
    return "u16"


def rebuild_content(inner: dict | None, new_text: str) -> str:
    """번역문을 content 문자열로. rich 면 styles range 를 새 길이에 맞춰 비율 보정."""
    if inner is None:
        return new_text
    inner = json.loads(json.dumps(inner))  # 원본 dict 를 건드리지 않는다
    old = inner.get("text") or ""
    styles = inner.get("styles")
    unit = _range_unit(old, styles) if isinstance(styles, list) else "u16"
    size = u16len if unit == "u16" else len
    old_len, new_len = size(old), size(new_text)
    # 새 글자에서 끊어도 되는 자리(글자 경계) — UTF-16 이면 이모지 반쪽에서 끊지 않게
    edges, pos = [0], 0
    for ch in new_text:
        pos += size(ch)
        edges.append(pos)
    snap = lambda x: min(edges, key=lambda b: (abs(b - x), -b))  # noqa: E731
    inner["text"] = new_text
    if isinstance(styles, list) and old_len > 0:
        for st in styles:
            rng = st.get("range") if isinstance(st, dict) else None
            if isinstance(rng, list) and len(rng) == 2:
                s, e = rng
                if s <= 0 and e >= old_len:  # 전체를 덮던 스타일
                    st["range"] = [0, new_len]
                else:
                    st["range"] = [snap(max(0, min(new_len, round(s * new_len / old_len)))),
                                   snap(max(0, min(new_len, round(e * new_len / old_len))))]
        # 비율 보정 뒤 생긴 빈 구간·끝 누락을 메운다(마지막 스타일이 끝까지 덮도록).
        ranged = [st for st in styles if isinstance(st, dict) and isinstance(st.get("range"), list)]
        if ranged:
            ranged[-1]["range"][1] = new_len
    return json.dumps(inner, ensure_ascii=False)


def needs_translation(text: str) -> bool:
    """글자가 하나라도 있어야 번역. 숫자·기호·이모지만이면 그대로 둔다."""
    return any(ch.isalpha() for ch in (text or ""))


def extract(draft: dict) -> list[dict[str, Any]]:
    """번역 대상 텍스트 목록: [{id, type, text}] (빈 글자 제외)."""
    out: list[dict[str, Any]] = []
    texts = ((draft or {}).get("materials") or {}).get("texts") or []
    for tm in texts:
        if not isinstance(tm, dict):
            continue
        text, _ = parse_content(tm.get("content"))
        if text and text.strip():
            out.append({"id": tm.get("id"), "type": tm.get("type") or "text", "text": text})
    return out


def tts_linked_count(draft: dict) -> int:
    """글자 읽어주기(TTS) 오디오 개수 — 번역해도 음성은 원어로 남는다는 경고용."""
    audios = ((draft or {}).get("materials") or {}).get("audios") or []
    return sum(1 for a in audios if isinstance(a, dict) and a.get("type") == "text_to_audio")


def tts_items(draft: dict) -> list[dict[str, Any]]:
    """글자 읽어주기 음성 목록: [{id, tone, duration(us), text_id, text}]. text 는 연결된 글자의 원문."""
    m = (draft or {}).get("materials") or {}
    texts = {t.get("id"): parse_content(t.get("content"))[0] for t in m.get("texts") or [] if isinstance(t, dict)}
    out = []
    for a in m.get("audios") or []:
        if isinstance(a, dict) and a.get("type") == "text_to_audio":
            out.append({"id": a.get("id"), "tone": a.get("tone_type") or a.get("tone_effect_name") or "",
                        "duration": int(a.get("duration") or 0), "text_id": a.get("text_id"),
                        "text": texts.get(a.get("text_id"), "")})
    return out


def apply_tts(draft: dict, repl: dict[str, dict], max_speed: float = 1.15, extend: bool = True) -> list[str]:
    """음성 바꿔 끼우기. repl = {오디오 material id: {"file": 새 wav 파일명, "duration": us, "name": 표시 이름}}.

    새 wav 는 프로젝트 폴더의 textReading/ 에 들어 있다고 본다(경로는 기존 자리표시자 접두를 그대로 쓴다).
    원래 구간보다 길면 CapCut 재생 속도를 올려 원래 길이에 맞춘다 — max_speed 를 넘으면 그만큼 길어진다.
    돌려주는 값: 원래 길이에 못 맞춘 음성 설명 목록.
    """
    m = (draft or {}).get("materials") or {}
    speeds = {s.get("id"): s for s in m.get("speeds") or [] if isinstance(s, dict)}
    warnings: list[str] = []
    grow: list | None = [] if extend else None
    for a in m.get("audios") or []:
        r = repl.get(a.get("id")) if isinstance(a, dict) else None
        if not r:
            continue
        folder = str(a.get("path") or "").replace("\\", "/").rsplit("/", 1)[0]
        a["path"] = f"{folder}/{r['file']}"
        a["duration"] = new = int(r["duration"])
        if r.get("name"):
            a["name"] = r["name"][:24]
        a["wave_points"] = []
        for seg in _segments_of(draft, a.get("id")):
            _fit_segment(seg, new, speeds, max_speed, r.get("name") or a.get("id"), warnings, grow)
    _grow_timeline(draft, grow or [], warnings)
    return warnings


NARRATION_HINTS = ("narration", "narr", "나레이션", "내레이션", "voice", "voiceover", "녹음", "tts", "더빙")


def _segments_of(draft: dict, material_id: str) -> list[dict]:
    return [s for t in draft.get("tracks") or [] for s in t.get("segments") or []
            if s.get("material_id") == material_id]


def narration_items(draft: dict) -> list[dict[str, Any]]:
    """직접 넣은 내레이션 음성 파일(예: materials/audio/narration.mp3)의 구간 목록.

    이름에 narration·내레이션 등이 들어간 오디오(또는 type == record 녹음)만 본다 — 배경음악과 구분.
    대본 = 그 구간과 시간이 겹치는(가운데가 구간 안에 있는) 자막·글자를 시간순으로 이은 것.
    한 파일을 여러 구간에 잘라 쓰므로 구간(segment)마다 한 항목: [{id(구간), material_id, tone, duration, text}].
    """
    m = (draft or {}).get("materials") or {}
    texts = {t.get("id"): t for t in m.get("texts") or [] if isinstance(t, dict)}
    spans = []  # (시작, 끝, 글자)
    for t in draft.get("tracks") or []:
        for s in t.get("segments") or []:
            tm = texts.get(s.get("material_id"))
            tr = s.get("target_timerange") or {}
            if tm and tr.get("duration"):
                text = parse_content(tm.get("content"))[0].strip()
                if text:
                    spans.append((tr["start"], tr["start"] + tr["duration"], text, tm.get("id")))
    spans.sort()
    out = []
    for a in m.get("audios") or []:
        if not isinstance(a, dict) or a.get("type") == "text_to_audio":
            continue
        name = (a.get("name") or str(a.get("path") or "").rsplit("/", 1)[-1]).lower()
        if a.get("type") != "record" and not any(h in name for h in NARRATION_HINTS):
            continue
        for seg in _segments_of(draft, a.get("id")):
            tr = seg.get("target_timerange") or {}
            s0, s1 = tr.get("start", 0), tr.get("start", 0) + tr.get("duration", 0)
            # 구간 안에 가운데가 있고 구간보다 많이 길지 않은 글자(제목처럼 영상 전체에 걸친 건 뺌)
            parts, seen = [], set()
            for b, e, txt, mid in spans:
                if s0 <= (b + e) / 2 <= s1 and e - b <= (s1 - s0) + 500_000 and mid not in seen:
                    seen.add(mid)
                    parts.append({"material_id": mid, "text": txt})
            words = [x["text"] for x in parts]
            out.append({"id": seg.get("id"), "material_id": a.get("id"), "kind": "narration", "parts": parts,
                        "tone": a.get("name") or "내레이션", "duration": int(tr.get("duration") or 0),
                        "start": s0, "text": " ".join(" ".join(words).split())})
    return out


FRAME = 34_000  # 1프레임(30fps) 남짓 — 이보다 작은 차이는 같은 시각으로 본다


def _fit_segment(seg: dict, new: int, speeds: dict, max_speed: float, label: str, warnings: list[str],
                 grow: list | None = None) -> None:
    """구간 길이(slot)에 맞춰 재생 속도를 올린다(최대 max_speed).
    그래도 넘치면 grow 가 있으면 «영상 늘리기» 목록에 넣고(나중에 _grow_timeline), 없으면 warnings 에 남긴다."""
    tr = seg.setdefault("target_timerange", {"start": 0})
    slot = int(tr.get("duration") or new)
    speed = min(max_speed, new / slot) if new > slot > 0 else 1.0
    seg["speed"] = round(speed, 4)
    seg["source_timerange"] = {"start": 0, "duration": new}
    tr["duration"] = int(round(new / speed))
    for ref in seg.get("extra_material_refs") or []:
        if ref in speeds:
            speeds[ref]["speed"] = round(speed, 4)
    over = tr["duration"] - slot
    if over > FRAME:
        if grow is not None:
            grow.append({"seg": seg, "at": int(tr.get("start", 0)) + slot, "delta": over, "label": label})
        elif over > 100_000:  # 0.1초 넘게 삐져나올 때만 알린다
            warnings.append(f"«{label}» {new / 1e6:.1f}초 → {max_speed}배로도 {slot / 1e6:.1f}초에 못 맞춰 "
                            f"{tr['duration'] / 1e6:.1f}초가 됨")


def insert_time(draft: dict, at: int, delta: int, keep: tuple = ()) -> list[str]:
    """at 지점에 delta(us) 만큼 시간을 끼워 넣는다(리플 편집). 돌려주는 값: 알릴 말.

    - at 이후에 시작하는 구간은 모두 delta 만큼 뒤로 민다(자막·장면이 영상과 계속 맞도록).
    - at 을 가로지르는 구간(제목·스티커·배경음악 등)은 delta 만큼 길게 한다.
    - 가로지르는 구간이 없는 영상 트랙은 at 에서 끝나는 장면을 원본에서 더 이어 붙여 늘린다.
      원본이 모자라면 그 장면을 느리게 해서 채운다.
    keep 에 든 구간(늘어난 내레이션 자신)은 건드리지 않는다.
    """
    m = (draft or {}).get("materials") or {}
    lengths = {x.get("id"): int(x.get("duration") or 0)
               for k in ("videos", "audios") for x in m.get(k) or [] if isinstance(x, dict)}
    speeds = {x.get("id"): x for x in m.get("speeds") or [] if isinstance(x, dict)}
    notes: list[str] = []

    def lengthen(seg: dict) -> None:
        tr = seg["target_timerange"]
        tr["duration"] += delta
        src = seg.get("source_timerange")
        if not src:
            return
        speed = float(seg.get("speed") or 1.0)
        want = int(round(tr["duration"] * speed))
        have = lengths.get(seg.get("material_id"), 0) - int(src.get("start", 0))
        if have <= 0 or want <= have:
            src["duration"] = want
            return
        src["duration"] = have  # 원본이 모자라다 → 느리게 늘려 채운다
        slow = round(have / tr["duration"], 4)
        seg["speed"] = slow
        for ref in seg.get("extra_material_refs") or []:
            if ref in speeds:
                speeds[ref]["speed"] = slow
        notes.append(f"{tr['start'] / 1e6:.1f}초 장면은 원본이 모자라 {slow}배로 느리게 늘림")

    for track in draft.get("tracks") or []:
        segs = [x for x in track.get("segments") or []
                if x.get("target_timerange") and not any(x is k for k in keep)]
        spanning = [x for x in segs if x["target_timerange"]["start"] < at - FRAME
                    and x["target_timerange"]["start"] + x["target_timerange"]["duration"] > at + FRAME]
        ending = [x for x in segs if abs(x["target_timerange"]["start"] + x["target_timerange"]["duration"] - at) <= FRAME
                  and x["target_timerange"]["start"] < at - FRAME]
        for x in segs:
            if x["target_timerange"]["start"] >= at - FRAME:
                x["target_timerange"]["start"] += delta
        for x in spanning:
            lengthen(x)
        if not spanning and track.get("type") == "video":
            for x in ending:
                lengthen(x)
    if draft.get("duration"):
        draft["duration"] = int(draft["duration"]) + delta
    return notes


def _grow_timeline(draft: dict, grow: list, warnings: list[str]) -> None:
    """넘친 음성마다 영상을 늘린다. 뒤쪽부터 처리해야 앞쪽 지점이 밀리지 않는다."""
    for g in sorted(grow, key=lambda g: g["at"], reverse=True):
        start = int(g["seg"]["target_timerange"].get("start", 0))
        inside = [x for t in draft.get("tracks") or [] if t.get("type") == "text"
                  for x in t.get("segments") or [] if x.get("target_timerange")
                  and x["target_timerange"]["start"] >= start - FRAME
                  and x["target_timerange"]["start"] + x["target_timerange"]["duration"] <= g["at"] + FRAME]
        warnings.extend(insert_time(draft, g["at"], g["delta"], keep=(g["seg"], *inside)))
        # 내레이션 구간 안 자막은 늘어난 음성 길이에 맞춰 같은 비율로 펼친다(빈 자막 구간이 생기지 않게)
        k = (g["at"] - start + g["delta"]) / max(1, g["at"] - start)
        for x in inside:
            tr = x["target_timerange"]
            end = start + round((tr["start"] + tr["duration"] - start) * k)
            tr["start"] = start + round((tr["start"] - start) * k)
            tr["duration"] = end - tr["start"]
        warnings.append(f"«{g['label']}» 이 길어 {g['at'] / 1e6:.1f}초 지점에서 영상을 {g['delta'] / 1e6:.1f}초 늘림")


def apply_narration(draft: dict, repl: dict[str, dict], max_speed: float = 1.15, extend: bool = True) -> list[str]:
    """내레이션 구간 바꿔 끼우기. repl = {구간 id: {"file", "duration", "name"}}.
    구간마다 새 오디오 재료를 만들어(원래 재료를 복사, 경로만 새 파일) 구간이 그것을 가리키게 한다.
    새 파일은 원래 파일과 같은 폴더에 있다고 본다."""
    import uuid
    m = (draft or {}).get("materials") or {}
    audios = m.setdefault("audios", [])
    by_id = {a.get("id"): a for a in audios if isinstance(a, dict)}
    speeds = {s.get("id"): s for s in m.get("speeds") or [] if isinstance(s, dict)}
    warnings: list[str] = []
    grow: list | None = [] if extend else None
    for t in draft.get("tracks") or []:
        for seg in t.get("segments") or []:
            r = repl.get(seg.get("id"))
            src = by_id.get(seg.get("material_id")) if r else None
            if not src:
                continue
            new_mat = json.loads(json.dumps(src))
            folder = str(src.get("path") or "").replace("\\", "/").rsplit("/", 1)[0]
            # 본문 사본 6벌이 같은 id 를 갖도록 구간 id 에서 정해진 값으로 만든다
            new_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cl-narration:{seg.get('id')}:{r['file']}")).upper()
            new_mat.update(id=new_id, path=f"{folder}/{r['file']}", name=r["file"],
                           duration=int(r["duration"]), wave_points=[])
            audios.append(new_mat)
            seg["material_id"] = new_mat["id"]
            _fit_segment(seg, int(r["duration"]), speeds, max_speed, r.get("name") or r["file"], warnings, grow)
    _grow_timeline(draft, grow or [], warnings)
    return warnings


def apply(draft: dict, mapping: dict[str, str], overrides: dict[str, str] | None = None,
          fit: bool = False) -> int:
    """mapping(원문 → 번역)을 draft 의 텍스트에 반영. 바뀐 텍스트 수를 반환.
    overrides = {글자 material id: 넣을 글자} 는 mapping 보다 앞선다 — 내레이션 구간 자막을
    음성 문장 조각으로 맞출 때(같은 «진짜» 라도 그 구간 것만 바꿔야 하므로 id 로)."""
    changed = 0
    texts = ((draft or {}).get("materials") or {}).get("texts") or []
    for tm in texts:
        if not isinstance(tm, dict):
            continue
        text, inner = parse_content(tm.get("content"))
        new = (overrides or {}).get(tm.get("id")) or mapping.get(text)
        if not new or new == text:
            continue
        tm["content"] = rebuild_content(inner, new)
        base_text, base_inner = parse_content(tm.get("base_content"))
        if base_text:
            tm["base_content"] = rebuild_content(base_inner, new if tm.get("id") in (overrides or {})
                                                 else mapping.get(base_text, new))
        for key in ("words", "current_words"):
            if isinstance(tm.get(key), dict) and tm[key].get("text"):
                tm[key] = {"start_time": [], "end_time": [], "text": []}
        if fit and tm.get("type") != "subtitle":  # 자막 조각마다 크기가 들쭉날쭉하면 더 어색하다 — 제목·글자만
            k = fit_scale(text, new, float(tm.get("font_size") or 0))
            if k < 0.98:
                scale_text(tm, k)
        changed += 1
    return changed


# ─── 넘침 줄이기 · 글꼴 바꾸기 ─────────────────────────────────────────────
FIT_MIN = 0.7  # 이보다 작게는 줄이지 않는다(읽기 어렵다)


def text_width(s: str) -> float:
    """화면 폭 어림: 한글·한자·가나·전각 = 1, 영문·숫자·공백 = 0.5."""
    return sum(1.0 if ord(c) >= 0x1100 and not 0xFF61 <= ord(c) <= 0xFFDC else 0.5 for c in s)


FIT_LIMIT = 190.0  # «한 줄 칸 수 × 글자 크기» 가 이쯤이면 세로 영상 폭을 꽉 채운다(실측: 원본 제목 8.5칸 × 22)


def fit_scale(old: str, new: str, size: float = 0) -> float:
    """번역문의 가장 긴 줄이 화면 폭을 넘을 때만 그만큼 줄인다(최소 FIT_MIN).
    폭 한도 = 원문 줄 폭과 FIT_LIMIT 중 큰 쪽 — 짧은 글자는 자리가 남으니 길어져도 그대로 둔다."""
    wo = max((text_width(x) for x in old.split("\n")), default=0)
    wn = max((text_width(x) for x in new.split("\n")), default=0)
    if wo <= 0 or wn <= wo * 1.05:
        return 1.0
    if size <= 0:
        return max(FIT_MIN, wo / wn)
    limit = max(wo * size, FIT_LIMIT)
    return 1.0 if wn * size <= limit * 1.02 else max(FIT_MIN, limit / (wn * size))


SCREEN_EM = 177.0  # 세로 영상 폭 = «글자 폭(em) × 글자 크기 × 상자 배율» 177 쯤(실측: «도현» 제목 6.44em × 22 가 폭의 80%)
FIT_FILL = 0.9     # 번역 글자는 화면 폭의 90% 까지
FIT_MIN_MEASURED = 0.85  # 크기 줄이기는 마지막 수단 — 먼저 짧게 다시 번역하고(app.fit_translations) 조금만 줄인다


def snapshot_texts(draft: dict) -> dict[str, tuple[str, str, float]]:
    """바꾸기 전 글자: {material id: (글자, 첫 글꼴 파일, 글자 크기)} — fit_texts 가 원래 폭과 비교할 때 쓴다."""
    out = {}
    for tm in ((draft or {}).get("materials") or {}).get("texts") or []:
        text, inner = parse_content(tm.get("content"))
        path = next(((st.get("font") or {}).get("path") for st in (inner or {}).get("styles") or []
                     if (st.get("font") or {}).get("path")), tm.get("font_path") or "")
        out[tm.get("id")] = (text, path, float(tm.get("font_size") or 0))
    return out


def fit_texts(draft: dict, before: dict, measure, extra_line_scale: float = 0.85) -> list[str]:
    """번역·글꼴 바꾸기 뒤, 화면 폭을 넘는 제목·글자를 실제 글꼴 폭으로 재서 줄인다(자막 조각은 제외).
    짧게 다시 번역하며 줄이 원문보다 늘었으면 늘어난 줄마다 extra_line_scale 배로 줄여 전체 높이를 비슷하게 둔다.
    measure(글꼴 파일, 글자) → 가장 긴 줄의 em 폭. 못 재면 글자 수 어림(fit_scale)으로 한다. 돌려주는 값: 알릴 말."""
    scale_of = {}
    for t in draft.get("tracks") or []:
        for s in t.get("segments") or []:
            scale_of[s.get("material_id")] = float(((s.get("clip") or {}).get("scale") or {}).get("x") or 1.0)
    notes = []
    for tm in ((draft or {}).get("materials") or {}).get("texts") or []:
        if tm.get("type") == "subtitle" or tm.get("id") not in before:
            continue
        old_text, old_path, old_size = before[tm["id"]]
        new_text, inner = parse_content(tm.get("content"))
        if not inner or new_text == old_text:
            continue
        new_path = next(((st.get("font") or {}).get("path") for st in inner.get("styles") or []
                         if (st.get("font") or {}).get("path")), tm.get("font_path") or "")
        extra = new_text.count("\n") - old_text.count("\n")
        if extra > 0 and extra_line_scale < 1:  # 2줄 → 3줄이면 글자를 조금 줄여 위아래로 넘치지 않게
            k = max(0.6, extra_line_scale ** extra)
            scale_text(tm, k)
            notes.append(f"«{new_text.splitlines()[0][:12]}…» 가 {old_text.count(chr(10)) + 1}줄 → "
                         f"{new_text.count(chr(10)) + 1}줄이라 글자 크기를 {round(k * 100)}%로 줄임")
        size, clip = float(tm.get("font_size") or 0), scale_of.get(tm["id"], 1.0)
        try:
            old_w = measure(old_path, old_text) * old_size * clip
            new_w = measure(new_path, new_text) * size * clip
        except Exception:  # noqa: BLE001 — 글꼴 파일을 못 읽으면 글자 수로 어림
            k = fit_scale(old_text, new_text, size)
            if k < 0.98:
                scale_text(tm, k)
            continue
        limit = max(old_w, SCREEN_EM * FIT_FILL)
        if new_w > limit * 1.02:
            k = max(FIT_MIN_MEASURED, limit / new_w)
            scale_text(tm, k)
            notes.append(f"«{new_text.splitlines()[0][:12]}…» 가 화면보다 넓어 글자 크기를 {round(k * 100)}%로 줄임")
    return notes


def _scale_content(content: Any, k: float, font: dict | None = None) -> Any:
    text, inner = parse_content(content)
    if inner is None:
        return content
    for st in inner.get("styles") or []:
        if isinstance(st, dict):
            if isinstance(st.get("size"), (int, float)):
                st["size"] = round(st["size"] * k, 2)
            if font is not None and st.get("font", {}).get("id") in font:
                st["font"] = {"id": "", "path": font[st["font"]["id"]]}
    return json.dumps(inner, ensure_ascii=False)


def scale_text(tm: dict, k: float) -> None:
    """글자 크기를 k 배로(본문 styles · base_content · font_size 모두)."""
    for key in ("content", "base_content"):
        if tm.get(key):
            tm[key] = _scale_content(tm[key], k)
    if isinstance(tm.get("font_size"), (int, float)):
        tm["font_size"] = round(tm["font_size"] * k, 2)


def font_titles(draft: dict) -> dict[str, str]:
    """CapCut 글꼴 ID → 이름(예: «도현»). 글자 재료의 fonts 목록에 적혀 있다."""
    out: dict[str, str] = {}
    for tm in ((draft or {}).get("materials") or {}).get("texts") or []:
        for f in tm.get("fonts") or []:
            if f.get("resource_id") and f.get("title"):
                out[f["resource_id"]] = unicodedata.normalize("NFC", f["title"])  # CapCut 은 자모 분리형(NFD)으로 적기도 한다
    return out


def used_fonts(draft: dict) -> list[dict[str, Any]]:
    """이 프로젝트 글자에 쓰인 글꼴: [{key(이름 없으면 ID), title, id, count, sizes, sample}] — 많이 쓴 순."""
    titles, seen = font_titles(draft), {}
    for tm in ((draft or {}).get("materials") or {}).get("texts") or []:
        text, inner = parse_content(tm.get("content"))
        for st in (inner or {}).get("styles") or []:
            fid = (st.get("font") or {}).get("id")
            if not fid:
                continue
            e = seen.setdefault(fid, {"key": titles.get(fid) or fid, "title": titles.get(fid, ""), "id": fid,
                                      "count": 0, "sizes": set(), "sample": text.replace("\n", " ")[:20]})
            e["count"] += 1
            if st.get("size"):
                e["sizes"].add(st["size"])
    return sorted(({**e, "sizes": sorted(e["sizes"])} for e in seen.values()), key=lambda e: -e["count"])


def apply_fonts(draft: dict, chosen: dict[str, dict]) -> int:
    """글꼴 바꾸기. chosen = {원본 글꼴 이름 또는 ID: {"path": 새 글꼴 파일 절대경로, "scale": 크기 배율}}.
    styles 의 font 를 새 파일로(CapCut 글꼴 ID 는 비움), 크기는 배율만큼. 바꾼 글자 수를 돌려준다."""
    titles = font_titles(draft)
    by_id = {}
    for fid in {(st.get("font") or {}).get("id") for tm in (draft.get("materials") or {}).get("texts") or []
                for st in (parse_content(tm.get("content"))[1] or {}).get("styles") or []}:
        c = chosen.get(titles.get(fid, "")) or chosen.get(fid)
        if fid and c:
            by_id[fid] = c
    changed = 0
    for tm in (draft.get("materials") or {}).get("texts") or []:
        _, inner = parse_content(tm.get("content"))
        ids = [(st.get("font") or {}).get("id") for st in (inner or {}).get("styles") or []]
        hit = [by_id[i] for i in ids if i in by_id]
        if not hit:
            continue
        paths = {i: by_id[i]["path"] for i in ids if i in by_id}
        k = float(hit[0].get("scale") or 1.0)  # 한 글자 안에서는 첫 글꼴의 배율을 따른다
        for key in ("content", "base_content"):
            if tm.get(key):
                tm[key] = _scale_content(tm[key], k, paths)
        if isinstance(tm.get("font_size"), (int, float)):
            tm["font_size"] = round(tm["font_size"] * k, 2)
        main = hit[0]["path"]
        tm.update(font_path=main, font_resource_id="", font_id="", fonts=[], font_title="none",
                  font_name=Path(main).stem)
        changed += 1
    return changed
