"""CapCut 드래프트 JSON 안의 텍스트를 꺼내고(extract) 번역문을 다시 넣는다(apply).

실측(CapCut 9.4, draft new_version 185.0.0):
- 텍스트는 draft["materials"]["texts"][*]
- content 는 대개 JSON 문자열 {"text": "...", "styles": [{"range": [s, e], ...}]}
  range 단위는 글자(코드포인트) — '🍒체리돌' 은 [0, 4]. 파이썬 len() 과 같다.
- 자동 자막(type == "subtitle")은 base_content(같은 모양) 와 words(단어별 타이밍)도 갖는다.
  번역하면 단어가 안 맞으므로 words 는 비운다.
- text_to_audio(글자 읽어주기) 오디오는 text_id 로 텍스트에 붙는다 — 음성은 원어 그대로 남는다.
"""
from __future__ import annotations

import json
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


def rebuild_content(inner: dict | None, new_text: str) -> str:
    """번역문을 content 문자열로. rich 면 styles range 를 새 길이에 맞춰 비율 보정."""
    if inner is None:
        return new_text
    inner = json.loads(json.dumps(inner))  # 원본 dict 를 건드리지 않는다
    old_len, new_len = len(inner.get("text") or ""), len(new_text)
    inner["text"] = new_text
    styles = inner.get("styles")
    if isinstance(styles, list) and old_len > 0:
        for st in styles:
            rng = st.get("range") if isinstance(st, dict) else None
            if isinstance(rng, list) and len(rng) == 2:
                s, e = rng
                if s <= 0 and e >= old_len:  # 전체를 덮던 스타일
                    st["range"] = [0, new_len]
                else:
                    st["range"] = [
                        max(0, min(new_len, round(s * new_len / old_len))),
                        max(0, min(new_len, round(e * new_len / old_len))),
                    ]
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


def apply(draft: dict, mapping: dict[str, str]) -> int:
    """mapping(원문 → 번역)을 draft 의 텍스트에 반영. 바뀐 텍스트 수를 반환."""
    changed = 0
    texts = ((draft or {}).get("materials") or {}).get("texts") or []
    for tm in texts:
        if not isinstance(tm, dict):
            continue
        text, inner = parse_content(tm.get("content"))
        new = mapping.get(text)
        if not new or new == text:
            continue
        tm["content"] = rebuild_content(inner, new)
        base_text, base_inner = parse_content(tm.get("base_content"))
        if base_text:
            tm["base_content"] = rebuild_content(base_inner, mapping.get(base_text, new))
        for key in ("words", "current_words"):
            if isinstance(tm.get(key), dict) and tm[key].get("text"):
                tm[key] = {"start_time": [], "end_time": [], "text": []}
        changed += 1
    return changed
