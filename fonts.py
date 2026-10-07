"""언어별 글꼴 바꾸기 — 한국어 전용 CapCut 글꼴에는 일본어 글자가 없어 CapCut 이 아무 글꼴로 대신 그린다.

- 원본 글꼴(CapCut 글꼴 이름, 예: «도현»)마다 그 언어에서 쓸 글꼴 파일과 크기 배율을 정한다.
- 기본 짝은 원본과 모양을 직접 비교해 골랐다(docs/html/fonts-ja-compare.html). 설정 font_map 이 앞선다.
- 글꼴 파일은 무료(OFL/Apache) Google Fonts 를 data/fonts/<언어>/ 에 처음 쓸 때 내려받는다.
"""
from __future__ import annotations

import unicodedata
import urllib.request
from pathlib import Path

FONT_DIR = Path(__file__).parent / "data" / "fonts"
GOOGLE = "https://raw.githubusercontent.com/google/fonts/main/"

# 언어별로 고를 수 있는 글꼴: 파일 이름 → (표시 이름, google/fonts 저장소 안 경로)
CATALOG: dict[str, dict[str, tuple[str, str]]] = {
    "ja": {
        "MPLUS1p-Black.ttf": ("M PLUS 1p Black — 굵은 고딕", "ofl/mplus1p/MPLUS1p-Black.ttf"),
        "ZenKakuGothicNew-Black.ttf": ("Zen Kaku Gothic New Black — 굵은 고딕", "ofl/zenkakugothicnew/ZenKakuGothicNew-Black.ttf"),
        "DelaGothicOne-Regular.ttf": ("Dela Gothic One — 아주 두꺼운 간판체", "ofl/delagothicone/DelaGothicOne-Regular.ttf"),
        "ReggaeOne-Regular.ttf": ("Reggae One — 두꺼운 붓 느낌", "ofl/reggaeone/ReggaeOne-Regular.ttf"),
        "PottaOne-Regular.ttf": ("Potta One — 붓글씨 팝", "ofl/pottaone/PottaOne-Regular.ttf"),
        "MPLUSRounded1c-ExtraBold.ttf": ("Rounded M+ 1c ExtraBold — 둥근 굵은체", "ofl/mplusrounded1c/MPLUSRounded1c-ExtraBold.ttf"),
        "ZenMaruGothic-Black.ttf": ("Zen Maru Gothic Black — 둥근 굵은체", "ofl/zenmarugothic/ZenMaruGothic-Black.ttf"),
        "MochiyPopOne-Regular.ttf": ("Mochiy Pop One — 통통한 팝체", "ofl/mochiypopone/MochiyPopOne-Regular.ttf"),
        "RocknRollOne-Regular.ttf": ("RocknRoll One — 둥근 굵은 팝", "ofl/rocknrollone/RocknRollOne-Regular.ttf"),
        "YuseiMagic-Regular.ttf": ("Yusei Magic — 굵은 마커 손글씨", "ofl/yuseimagic/YuseiMagic-Regular.ttf"),
        "KiwiMaru-Medium.ttf": ("Kiwi Maru Medium — 부드러운 보통체", "ofl/kiwimaru/KiwiMaru-Medium.ttf"),
        "KosugiMaru-Regular.ttf": ("Kosugi Maru — 둥근 보통체", "apache/kosugimaru/KosugiMaru-Regular.ttf"),
        "KleeOne-SemiBold.ttf": ("Klee One SemiBold — 연필 손글씨", "ofl/kleeone/KleeOne-SemiBold.ttf"),
        "Yomogi-Regular.ttf": ("Yomogi — 가는 손글씨", "ofl/yomogi/Yomogi-Regular.ttf"),
        "ZenKurenaido-Regular.ttf": ("Zen Kurenaido — 붓펜 손글씨", "ofl/zenkurenaido/ZenKurenaido-Regular.ttf"),
        "HachiMaruPop-Regular.ttf": ("Hachi Maru Pop — 귀여운 손글씨", "ofl/hachimarupop/HachiMaruPop-Regular.ttf"),
    },
}

# 원본 CapCut 글꼴 이름 → 기본 짝 (원본과 나란히 그려 비교해 고름)
DEFAULT_MAP: dict[str, dict[str, dict]] = {
    "ja": {
        "도현": {"font": "MPLUS1p-Black.ttf", "scale": 1.0},
        "귀엽다": {"font": "MPLUSRounded1c-ExtraBold.ttf", "scale": 1.0},
        "연필": {"font": "KiwiMaru-Medium.ttf", "scale": 1.0},
        "KCC간판체": {"font": "DelaGothicOne-Regular.ttf", "scale": 0.92},  # 원본보다 글자 폭이 넓다
        "동해 독도": {"font": "YuseiMagic-Regular.ttf", "scale": 1.0},
        "7533442104639507729": {"font": "MochiyPopOne-Regular.ttf", "scale": 1.0},  # 이름 없는 템플릿 글꼴(«좋아 좋아»)
    },
}


def font_map(settings: dict, lang: str) -> dict[str, dict]:
    """원본 글꼴 이름(없으면 CapCut 글꼴 ID) → {"font": 파일 이름 또는 절대경로, "scale": 크기 배율}.
    설정의 font_map[lang] 이 기본값을 덮는다. font 를 비우면 그 글꼴은 바꾸지 않는다."""
    out = {k: dict(v) for k, v in DEFAULT_MAP.get(lang, {}).items()}
    for k, v in ((settings.get("font_map") or {}).get(lang) or {}).items():
        k = unicodedata.normalize("NFC", k)
        out[k] = {**out.get(k, {}), **(v or {})}
    return {k: v for k, v in out.items() if v.get("font")}


def choices(lang: str) -> list[dict]:
    """화면에서 고를 글꼴 목록 [{file, name, ready}] — ready = 이미 내려받음."""
    return [{"file": f, "name": n, "ready": (FONT_DIR / lang / f).is_file()}
            for f, (n, _) in CATALOG.get(lang, {}).items()]


# ─── 글자 폭 재기(표준 라이브러리만) ──────────────────────────────────────
# 글꼴마다 글자 폭이 크게 다르다(«도현» 은 좁고 «M PLUS 1p Black» 은 넓다) → 글자 수 어림 대신 실제 폭을 잰다.
_metrics: dict[str, tuple] = {}


def _load_metrics(path: str):
    """(unitsPerEm, 글자→글리프 함수, 글리프 폭 목록). TTF·OTF·TTC(첫 글꼴)."""
    if path in _metrics:
        return _metrics[path]
    import struct
    data = Path(path).read_bytes()
    base = struct.unpack(">I", data[12:16])[0] if data[:4] == b"ttcf" else 0
    n = struct.unpack(">H", data[base + 4:base + 6])[0]
    tables = {}
    for i in range(n):
        tag, _, off, ln = struct.unpack(">4sIII", data[base + 12 + 16 * i: base + 28 + 16 * i])
        tables[tag.decode("latin-1")] = off
    upem = struct.unpack(">H", data[tables["head"] + 18: tables["head"] + 20])[0]
    nhm = struct.unpack(">H", data[tables["hhea"] + 34: tables["hhea"] + 36])[0]
    hm = tables["hmtx"]
    adv = [struct.unpack(">H", data[hm + 4 * i: hm + 4 * i + 2])[0] for i in range(nhm)]
    cm = tables["cmap"]
    subs = {}
    for i in range(struct.unpack(">H", data[cm + 2: cm + 4])[0]):
        pid, eid, off = struct.unpack(">HHI", data[cm + 4 + 8 * i: cm + 12 + 8 * i])
        subs[(pid, eid)] = cm + off
    sub = next((subs[k] for k in ((3, 10), (0, 4), (3, 1), (0, 3), (0, 1), (0, 0)) if k in subs), None)
    fmt = struct.unpack(">H", data[sub: sub + 2])[0] if sub is not None else -1
    if fmt == 12:
        groups = [struct.unpack(">III", data[sub + 16 + 12 * i: sub + 28 + 12 * i])
                  for i in range(struct.unpack(">I", data[sub + 12: sub + 16])[0])]

        def glyph(cp):
            for a, b, g in groups:
                if a <= cp <= b:
                    return g + cp - a
            return 0
    elif fmt == 4:
        seg = struct.unpack(">H", data[sub + 6: sub + 8])[0] // 2
        arr = lambda o: struct.unpack(f">{seg}H", data[o: o + 2 * seg])  # noqa: E731
        ends, starts = arr(sub + 14), arr(sub + 16 + 2 * seg)
        deltas, ro_at = arr(sub + 16 + 4 * seg), sub + 16 + 6 * seg
        ros = arr(ro_at)

        def glyph(cp):
            for i in range(seg):
                if cp <= ends[i]:
                    if cp < starts[i]:
                        return 0
                    if ros[i] == 0:
                        return (cp + deltas[i]) & 0xFFFF
                    p = ro_at + 2 * i + ros[i] + 2 * (cp - starts[i])
                    g = struct.unpack(">H", data[p: p + 2])[0]
                    return (g + deltas[i]) & 0xFFFF if g else 0
            return 0
    else:
        def glyph(cp):
            return 0
    _metrics[path] = (upem, glyph, adv)
    return _metrics[path]


def text_em(path: str, text: str) -> float:
    """가장 긴 줄의 폭(em). 글꼴에 없는 글자는 전각 1em·반각 0.5em 으로 어림한다."""
    upem, glyph, adv = _load_metrics(path)
    best = 0.0
    for line in text.split("\n"):
        w = 0.0
        for ch in line:
            g = glyph(ord(ch))
            w += adv[min(g, len(adv) - 1)] / upem if g else (1.0 if ord(ch) >= 0x1100 else 0.5)
        best = max(best, w)
    return best


def ensure(lang: str, font: str) -> Path:
    """글꼴 파일 경로. 목록에 있는 이름이면 없을 때 내려받는다. 절대경로면 그대로."""
    p = Path(font)
    if p.is_absolute():
        if not p.is_file():
            raise RuntimeError(f"글꼴 파일이 없습니다: {font}")
        return p
    p = FONT_DIR / lang / font
    if p.is_file():
        return p
    entry = CATALOG.get(lang, {}).get(font)
    if not entry:
        raise RuntimeError(f"모르는 글꼴입니다: {font} (data/fonts/{lang}/ 에 넣거나 절대경로로 지정하세요)")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    with urllib.request.urlopen(GOOGLE + entry[1], timeout=120) as r:
        tmp.write_bytes(r.read())
    tmp.replace(p)
    return p
