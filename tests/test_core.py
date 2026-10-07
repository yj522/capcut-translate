"""핵심 로직 검증 — 실측한 CapCut 9.4 폴더 모양을 본뜬 가짜 드래프트로.

실행: python -m unittest discover tests
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import drafts  # noqa: E402
import localize  # noqa: E402

PH = "##_draftpath_placeholder_0E685133-18CE-45ED-8CB8-2904A212EC80_##"
TID = "81608B93-401B-4321-AE88-0221B03C2BEC"


def rich(text, ranges):
    return json.dumps({"text": text, "styles": [{"range": r, "size": 10.0} for r in ranges]}, ensure_ascii=False)


def make_draft():
    sub = rich("클렌징으로 하면 잘 안 되더라", [[0, 16]])
    return {
        "id": TID,
        "materials": {
            "texts": [
                {"id": "t0", "type": "text", "content": rich("폼클렌징으로 브러시\n빨지 마세요!", [[0, 10], [10, 11], [11, 18]]),
                 "font_path": f"{PH}/fonts/DoHyeon-Regular.ttf"},
                {"id": "t1", "type": "text", "content": rich("🍒체리돌", [[0, 4]])},
                {"id": "t2", "type": "subtitle", "content": sub, "base_content": sub,
                 "recognize_text": "클렌징으로 하면 잘 안 되더라", "language": "ko-KR",
                 "words": {"start_time": [0, 720], "end_time": [720, 960], "text": ["클렌징으로", "하면"]}},
                {"id": "t3", "type": "text", "content": rich("2026", [[0, 4]])},
            ],
            "videos": [{"path": f"{PH}/materials/video.mp4"}],
            "audios": [{"type": "text_to_audio", "text_id": "t0"}],
        },
    }


def make_root(tmp: Path, name="원본 프로젝트") -> Path:
    root = tmp / "com.lveditor.draft"
    proj = root / name
    tl = proj / "Timelines" / TID
    (tl / "attachment" / "patch").mkdir(parents=True)
    draft = make_draft()
    for d in (proj, tl):
        for f in ("draft_content.json", "draft_content.json.bak", "template-2.tmp"):
            (d / f).write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    (proj / "Timelines" / "project.json").write_text(json.dumps({"main_timeline_id": TID}), encoding="utf-8")
    (tl / "attachment" / "patch" / "mini_draft.json").write_text(f'{{"p":"{drafts.fwd(proj)}"}}', encoding="utf-8")
    (proj / "draft_cover.jpg").write_bytes(b"\xff\xd8")
    meta = {"draft_id": "BD558137-C658-45d7-BC08-3963E8BD93DD", "draft_name": name,
            "draft_fold_path": drafts.fwd(proj), "draft_root_path": drafts.fwd(root),
            "tm_draft_create": 1, "tm_draft_modified": 2, "tm_duration": 45633333, "draft_cover": "draft_cover.jpg"}
    (proj / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (root / "root_meta_info.json").write_text(json.dumps({
        "all_draft_store": [{"draft_id": meta["draft_id"], "draft_fold_path": drafts.fwd(proj),
                             "draft_name": name, "draft_is_ai_shorts": False}],
        "draft_ids": 20, "root_path": drafts.fwd(root)}, ensure_ascii=False), encoding="utf-8")
    return root


MAPPING = {
    "폼클렌징으로 브러시\n빨지 마세요!": "Don't wash brushes\nwith foam cleanser!",
    "🍒체리돌": "🍒Cherrydol",
    "클렌징으로 하면 잘 안 되더라": "Cleanser just doesn't cut it",
}


class LocalizeTest(unittest.TestCase):
    def test_extract_skips_numbers_only_for_translation(self):
        items = localize.extract(make_draft())
        self.assertEqual(len(items), 4)
        self.assertFalse(localize.needs_translation("2026"))
        self.assertTrue(localize.needs_translation("🍒체리돌"))

    def test_apply_rewrites_content_ranges_base_and_words(self):
        d = make_draft()
        self.assertEqual(localize.apply(d, MAPPING), 3)
        t0, t1, t2, t3 = d["materials"]["texts"]
        inner = json.loads(t0["content"])
        self.assertEqual(inner["text"], MAPPING["폼클렌징으로 브러시\n빨지 마세요!"])
        ranges = [s["range"] for s in inner["styles"]]
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], len(inner["text"]))  # 마지막 스타일이 끝까지
        self.assertTrue(all(a[1] <= b[0] + 1 for a, b in zip(ranges, ranges[1:])))
        self.assertEqual(json.loads(t1["content"])["styles"][0]["range"], [0, len("🍒Cherrydol")])
        self.assertEqual(json.loads(t2["base_content"])["text"], "Cleanser just doesn't cut it")
        self.assertEqual(t2["words"]["text"], [])
        self.assertEqual(json.loads(t3["content"])["text"], "2026")  # 매핑 없으면 그대로
        self.assertEqual(localize.tts_linked_count(d), 1)


def tts_draft(slot_us):
    """실측 모양: text_to_audio 오디오 + 오디오 트랙 구간 + 구간이 가리키는 speed 재료."""
    return {
        "materials": {
            "texts": [{"id": "T1", "type": "text", "content": rich("박창수\n오늘자 송도", [[0, 10]])}],
            "audios": [{"id": "A1", "type": "text_to_audio", "tone_type": "따뜻한 남자", "text_id": "T1",
                        "duration": slot_us, "path": f"{PH}/textReading/old.wav", "name": "박창수"}],
            "speeds": [{"id": "S1", "type": "speed", "mode": 0, "speed": 1.0, "curve_speed": None}],
        },
        "tracks": [{"type": "audio", "segments": [{
            "id": "G1", "material_id": "A1", "speed": 1.0, "extra_material_refs": ["S1"],
            "source_timerange": {"start": 0, "duration": slot_us},
            "target_timerange": {"start": 2_000_000, "duration": slot_us}}]}],
    }


class TtsTest(unittest.TestCase):
    def test_tts_items_links_text(self):
        items = localize.tts_items(tts_draft(5_000_000))
        self.assertEqual(items, [{"id": "A1", "tone": "따뜻한 남자", "duration": 5_000_000,
                                  "text_id": "T1", "text": "박창수\n오늘자 송도"}])

    def test_longer_voice_speeds_up_to_fit_slot(self):
        d = tts_draft(5_000_000)
        warns = localize.apply_tts(d, {"A1": {"file": "new.wav", "duration": 6_000_000, "name": "Park"}}, max_speed=1.4)
        a, seg, sp = d["materials"]["audios"][0], d["tracks"][0]["segments"][0], d["materials"]["speeds"][0]
        self.assertEqual(warns, [])
        self.assertEqual(a["path"], f"{PH}/textReading/new.wav")
        self.assertEqual(a["duration"], 6_000_000)
        self.assertEqual(seg["speed"], 1.2)
        self.assertEqual(sp["speed"], 1.2)
        self.assertEqual(seg["source_timerange"], {"start": 0, "duration": 6_000_000})
        self.assertEqual(seg["target_timerange"], {"start": 2_000_000, "duration": 5_000_000})

    def test_too_long_voice_caps_speed_and_warns(self):
        d = tts_draft(2_000_000)
        warns = localize.apply_tts(d, {"A1": {"file": "n.wav", "duration": 4_000_000}}, max_speed=1.4, extend=False)
        seg = d["tracks"][0]["segments"][0]
        self.assertEqual(seg["speed"], 1.4)
        self.assertEqual(seg["target_timerange"]["duration"], round(4_000_000 / 1.4))
        self.assertEqual(len(warns), 1)

    def test_shorter_voice_keeps_normal_speed(self):
        d = tts_draft(5_000_000)
        localize.apply_tts(d, {"A1": {"file": "n.wav", "duration": 3_000_000}})
        seg = d["tracks"][0]["segments"][0]
        self.assertEqual(seg["speed"], 1.0)
        self.assertEqual(seg["target_timerange"]["duration"], 3_000_000)


class NarrationTest(unittest.TestCase):
    """실측(«원희_립»): materials/audio/narration.mp3 한 파일을 두 구간에 잘라 쓰고, 대본은 겹치는 자막."""

    def draft(self):
        subs = [("S1", 0, 1_000_000, "다른 사람 말"), ("S2", 5_600_000, 800_000, "먼저 광택감이"),
                ("S3", 6_400_000, 700_000, "너무 예쁜"), ("S4", 12_700_000, 900_000, "좋아!")]
        return {
            "materials": {
                "texts": [{"id": i, "type": "subtitle", "content": rich(t, [[0, len(t)]])} for i, _, _, t in subs],
                "audios": [{"id": "N", "type": "extract_music", "name": "narration.mp3",
                            "path": f"{PH}/materials/audio/narration.mp3", "duration": 4_966_666},
                           {"id": "B", "type": "extract_music", "name": "bgm.mp3", "path": f"{PH}/bgm.mp3"}],
                "speeds": [{"id": "SP1", "speed": 1.0}, {"id": "SP2", "speed": 1.0}],
            },
            "tracks": [
                {"type": "text", "segments": [{"id": "g" + i, "material_id": i,
                                               "target_timerange": {"start": s, "duration": d}} for i, s, d, _ in subs]},
                {"type": "audio", "segments": [
                    {"id": "A1", "material_id": "N", "extra_material_refs": ["SP1"],
                     "source_timerange": {"start": 233_333, "duration": 2_500_000},
                     "target_timerange": {"start": 5_600_000, "duration": 2_500_000}},
                    {"id": "A2", "material_id": "N", "extra_material_refs": ["SP2"],
                     "source_timerange": {"start": 2_866_666, "duration": 1_900_000},
                     "target_timerange": {"start": 12_700_000, "duration": 1_900_000}},
                    {"id": "A3", "material_id": "B", "target_timerange": {"start": 0, "duration": 20_000_000}}]},
            ],
        }

    def test_items_join_overlapping_subtitles_and_skip_bgm(self):
        items = localize.narration_items(self.draft())
        self.assertEqual([(i["id"], i["text"]) for i in items], [("A1", "먼저 광택감이 너무 예쁜"), ("A2", "좋아!")])

    def test_items_list_subtitle_parts(self):
        items = localize.narration_items(self.draft())
        self.assertEqual(items[0]["parts"], [{"material_id": "S2", "text": "먼저 광택감이"},
                                             {"material_id": "S3", "text": "너무 예쁜"}])

    def test_overrides_replace_only_those_subtitles(self):
        d = self.draft()
        d["materials"]["texts"].append({"id": "S9", "type": "subtitle", "content": rich("너무 예쁜", [[0, 5]])})
        localize.apply(d, {"너무 예쁜": "めっちゃ可愛い"}, {"S2": "まずはツヤ感が", "S3": "超かわいい"})
        got = {t["id"]: localize.parse_content(t["content"])[0] for t in d["materials"]["texts"]}
        self.assertEqual(got["S2"], "まずはツヤ感が")
        self.assertEqual(got["S3"], "超かわいい")  # 같은 원문이라도 내레이션 구간 것만 음성 문장 조각
        self.assertEqual(got["S9"], "めっちゃ可愛い")  # 다른 곳은 보통 번역

    def test_even_split_keeps_sentence_and_katakana_words(self):
        import translate
        parts = translate._even_split("まずはツヤ感が超かわいいヌーディーリップを塗って", ["먼저 광택감이", "너무 예쁜", "누디한", "입을 바르고"])
        self.assertEqual(len(parts), 4)
        self.assertEqual("".join(parts), "まずはツヤ感が超かわいいヌーディーリップを塗って")
        self.assertFalse(any(p.endswith("ヌー") for p in parts))

    def test_each_segment_gets_its_own_file(self):
        d = self.draft()
        localize.apply_narration(d, {"A1": {"file": "cl_ja_1.wav", "duration": 3_000_000},
                                     "A2": {"file": "cl_ja_2.wav", "duration": 1_500_000}}, max_speed=1.4)
        seg = {s["id"]: s for s in d["tracks"][1]["segments"]}
        mats = {a["id"]: a for a in d["materials"]["audios"]}
        self.assertEqual(mats[seg["A1"]["material_id"]]["path"], f"{PH}/materials/audio/cl_ja_1.wav")
        self.assertEqual(mats[seg["A2"]["material_id"]]["path"], f"{PH}/materials/audio/cl_ja_2.wav")
        self.assertEqual(seg["A1"]["speed"], 1.2)  # 3.0초를 2.5초 자리에
        self.assertEqual(seg["A1"]["source_timerange"], {"start": 0, "duration": 3_000_000})
        self.assertEqual(seg["A2"]["speed"], 1.0)
        self.assertEqual(seg["A3"]["material_id"], "B")  # 배경음악은 그대로
        self.assertEqual(mats["N"]["path"], f"{PH}/materials/audio/narration.mp3")  # 원래 재료도 그대로


    def test_too_long_narration_grows_video_and_pushes_later_items(self):
        d = self.draft()
        d["materials"]["videos"] = [{"id": "V", "duration": 100_000_000}]
        d["tracks"].insert(0, {"type": "video", "segments": [
            {"id": "v1", "material_id": "V", "speed": 1.0, "source_timerange": {"start": 0, "duration": 5_600_000},
             "target_timerange": {"start": 0, "duration": 5_600_000}},
            {"id": "v2", "material_id": "V", "speed": 1.0, "source_timerange": {"start": 28_800_000, "duration": 2_500_000},
             "target_timerange": {"start": 5_600_000, "duration": 2_500_000}},
            {"id": "v3", "material_id": "V", "speed": 2.0, "source_timerange": {"start": 50_000_000, "duration": 9_000_000},
             "target_timerange": {"start": 8_100_000, "duration": 4_500_000}}]})
        d["tracks"].append({"type": "sticker", "segments": [{"id": "title", "material_id": "x",
                                                             "target_timerange": {"start": 0, "duration": 20_000_000}}]})
        d["duration"] = 20_000_000
        warns = localize.apply_narration(d, {"A1": {"file": "a.wav", "duration": 4_200_000}}, max_speed=1.4)  # 2.5초 자리에 4.2초
        seg = {s["id"]: s for t in d["tracks"] for s in t["segments"]}
        grow = 3_000_000 - 2_500_000  # 1.4배로 3.0초 → 0.5초 넘침
        self.assertEqual(seg["A1"]["target_timerange"], {"start": 5_600_000, "duration": 3_000_000})
        self.assertEqual(seg["v2"]["target_timerange"]["duration"], 2_500_000 + grow)  # 내레이션 밑 장면을 늘림
        self.assertEqual(seg["v2"]["source_timerange"]["duration"], 2_500_000 + grow)  # 원본에서 더 이어 붙임
        self.assertEqual(seg["v3"]["target_timerange"]["start"], 8_100_000 + grow)  # 다음 장면은 밀림
        self.assertEqual(seg["gS4"]["target_timerange"]["start"], 12_700_000 + grow)  # 뒤 자막도 밀림
        self.assertEqual(seg["A2"]["target_timerange"]["start"], 12_700_000 + grow)  # 뒤 내레이션도 밀림
        # 내레이션 안 자막(5.6~7.1초)은 2.5→3.0초 비율(1.2배)로 펼쳐진다 — 겹치지도, 비지도 않게
        self.assertEqual(seg["gS2"]["target_timerange"], {"start": 5_600_000, "duration": 960_000})
        self.assertEqual(seg["gS3"]["target_timerange"], {"start": 6_560_000, "duration": 840_000})
        self.assertEqual(seg["gS1"]["target_timerange"]["start"], 0)  # 앞은 그대로
        self.assertEqual(seg["title"]["target_timerange"]["duration"], 20_000_000 + grow)  # 전체 제목은 길게
        self.assertEqual(d["duration"], 20_000_000 + grow)
        self.assertTrue(any("늘림" in w for w in warns))

    def test_grow_slows_shot_when_source_runs_out(self):
        d = {"materials": {"videos": [{"id": "V", "duration": 3_000_000}], "speeds": []},
             "tracks": [{"type": "video", "segments": [
                 {"id": "v", "material_id": "V", "speed": 1.0, "source_timerange": {"start": 1_000_000, "duration": 2_000_000},
                  "target_timerange": {"start": 0, "duration": 2_000_000}}]}], "duration": 2_000_000}
        notes = localize.insert_time(d, 2_000_000, 1_000_000)
        seg = d["tracks"][0]["segments"][0]
        self.assertEqual(seg["target_timerange"]["duration"], 3_000_000)
        self.assertEqual(seg["source_timerange"]["duration"], 2_000_000)  # 원본 끝까지만
        self.assertAlmostEqual(seg["speed"], 0.6667, places=3)
        self.assertEqual(len(notes), 1)


class RangeUnitTest(unittest.TestCase):
    def test_emoji_counts_two_in_utf16_ranges(self):
        # 실측(«원희_립»): «🍒체리돌» 은 [0, 5]. «🍒チェリードル» 이면 [0, 8] 이어야 마지막 «ル» 까지 스타일이 덮는다
        out = json.loads(localize.rebuild_content({"text": "🍒체리돌", "styles": [{"range": [0, 5]}]}, "🍒チェリードル"))
        self.assertEqual(out["styles"][0]["range"], [0, 8])

    def test_codepoint_ranges_are_kept_as_codepoints(self):
        out = json.loads(localize.rebuild_content({"text": "🍒체리돌", "styles": [{"range": [0, 4]}]}, "🍒チェリードル"))
        self.assertEqual(out["styles"][0]["range"], [0, 7])

    def test_split_never_lands_inside_emoji(self):
        out = json.loads(localize.rebuild_content(
            {"text": "🍒체리", "styles": [{"range": [0, 2]}, {"range": [2, 4]}]}, "🍒チェ"))
        self.assertEqual([s["range"] for s in out["styles"]], [[0, 2], [2, 4]])


class FontTest(unittest.TestCase):
    """실측(«원희_립»): 제목은 CapCut 글꼴 «도현»(ID 7616…), fonts 목록에 이름이 적혀 있다."""

    def draft(self):
        title = json.dumps({"text": "원희의 다이소립과\n궁합좋은 립템", "styles": [
            {"range": [0, 9], "size": 22.0, "font": {"id": "F1", "path": "C:/cache/F1/font.ttf"}},
            {"range": [9, 17], "size": 22.0, "font": {"id": "F1", "path": "C:/cache/F1/font.ttf"}}]}, ensure_ascii=False)
        sub = json.dumps({"text": "오늘 입술", "styles": [
            {"range": [0, 5], "size": 19.0, "font": {"id": "F2", "path": "C:/cache/F2/Pencil KR.ttf"}}]}, ensure_ascii=False)
        return {"materials": {"texts": [
            {"id": "T", "type": "text", "content": title, "font_size": 22.0, "font_path": "C:/cache/F1/font.ttf",
             "font_resource_id": "F1", "fonts": [{"resource_id": "F1", "title": "도현"}]},
            {"id": "S", "type": "subtitle", "content": sub, "font_size": 19.0,
             "fonts": [{"resource_id": "F2", "title": "연필"}]}]}}

    def test_used_fonts_by_name(self):
        got = {f["key"]: (f["count"], f["sizes"]) for f in localize.used_fonts(self.draft())}
        self.assertEqual(got, {"도현": (2, [22.0]), "연필": (1, [19.0])})

    def test_long_title_shrinks_but_subtitles_do_not(self):
        d = self.draft()
        localize.apply(d, {"원희의 다이소립과\n궁합좋은 립템": "ウォニのダイソーリップと\n相性抜群のリップ",
                           "오늘 입술": "今日の唇はかわいすぎるって"}, fit=True)
        t, s = d["materials"]["texts"]
        self.assertEqual(t["font_size"], 15.83)  # 12칸 × 크기가 화면 폭(190)을 넘음 → 190/12
        self.assertEqual({st["size"] for st in localize.parse_content(t["content"])[1]["styles"]}, {15.83})
        self.assertEqual(s["font_size"], 19.0)  # 자막 조각은 크기를 바꾸지 않는다

    def test_short_label_keeps_size_when_it_still_fits(self):
        self.assertEqual(localize.fit_scale("🍒체리돌", "🍒チェリードル", 12), 1.0)  # 7칸 × 12 = 84 < 화면 폭

    def test_fit_measures_real_width_after_font_swap(self):
        d = self.draft()
        d["tracks"] = [{"type": "text", "segments": [{"material_id": "T", "clip": {"scale": {"x": 1.0}}}]}]
        before = localize.snapshot_texts(d)
        localize.apply(d, {"원희의 다이소립과\n궁합좋은 립템": "ウォニのダイソーリップと\n相性抜群のリップ",
                           "오늘 입술": "今日の唇はかわいすぎるって"})
        localize.apply_fonts(d, {"도현": {"path": "NEW", "scale": 1.0}})
        widths = {"C:/cache/F1/font.ttf": 6.44, "NEW": 12.0}  # 실측: «도현» 6.44em, M PLUS 1p Black 12em
        notes = localize.fit_texts(d, before, lambda path, text: widths[path])
        t, s = d["materials"]["texts"]
        self.assertEqual(t["font_size"], 18.7)  # 크기 줄이기는 85% 까지만(먼저 짧게 다시 번역한다) → 22 × 0.85
        self.assertEqual(len(notes), 1)
        self.assertEqual(s["font_size"], 19.0)  # 자막 조각은 그대로

    def test_extra_line_shrinks_a_little(self):
        d = self.draft()
        before = localize.snapshot_texts(d)
        localize.apply(d, {"원희의 다이소립과\n궁합좋은 립템": "ウォニの\nダイソーリップ\n相性いいリップ"})
        notes = localize.fit_texts(d, before, lambda path, text: 7.0)  # 폭은 화면 안
        self.assertEqual(d["materials"]["texts"][0]["font_size"], 18.7)  # 2줄 → 3줄: 22 × 0.85
        self.assertEqual(len(notes), 1)

    def test_apply_fonts_swaps_file_and_scales(self):
        d = self.draft()
        localize.apply_fonts(d, {"도현": {"path": "D:/fonts/MPLUS1p-Black.ttf", "scale": 0.9}})
        t, s = d["materials"]["texts"]
        st = localize.parse_content(t["content"])[1]["styles"]
        self.assertEqual({x["font"]["path"] for x in st}, {"D:/fonts/MPLUS1p-Black.ttf"})
        self.assertEqual({x["font"]["id"] for x in st}, {""})
        self.assertEqual(t["font_size"], 19.8)
        self.assertEqual((t["font_path"], t["font_resource_id"], t["fonts"]), ("D:/fonts/MPLUS1p-Black.ttf", "", []))
        self.assertEqual(localize.parse_content(s["content"])[1]["styles"][0]["font"]["id"], "F2")  # 짝 없는 글꼴은 그대로


class CloneTest(unittest.TestCase):
    def test_clone_registers_new_project_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_root(Path(td))
            src = root / "원본 프로젝트"
            before = (src / "draft_content.json").read_text(encoding="utf-8")
            res = drafts.clone(root, src, "원본 프로젝트 [EN]", transform=lambda d: localize.apply(d, MAPPING))
            dest = root / res["folder"]

            # 원본 무변경
            self.assertEqual((src / "draft_content.json").read_text(encoding="utf-8"), before)
            # 메타
            meta = drafts.read_json(dest / "draft_meta_info.json")
            self.assertEqual(meta["draft_id"], res["id"])
            self.assertNotEqual(meta["draft_id"], "BD558137-C658-45d7-BC08-3963E8BD93DD")
            self.assertEqual(meta["draft_fold_path"], drafts.fwd(dest))
            self.assertEqual(meta["draft_name"], "원본 프로젝트 [EN]")
            # 본문 6벌 모두 번역 반영, 자리표시자 경로는 그대로
            files = drafts.all_content_files(dest)
            self.assertEqual(len(files), 6)
            for p in files:
                d = drafts.read_json(p)
                self.assertEqual(json.loads(d["materials"]["texts"][1]["content"])["text"], "🍒Cherrydol")
                self.assertTrue(d["materials"]["videos"][0]["path"].startswith(PH))
            # 클라우드 패치 캐시 제거
            self.assertFalse((dest / "Timelines" / TID / "attachment" / "patch").exists())
            # root_meta_info 등록
            rm = drafts.read_json(root / "root_meta_info.json")
            self.assertEqual(rm["all_draft_store"][0]["draft_id"], res["id"])
            self.assertEqual(rm["all_draft_store"][0]["draft_fold_path"], drafts.fwd(dest))
            self.assertEqual(len(rm["all_draft_store"]), 2)
            self.assertEqual(rm["draft_ids"], 21)
            # 임시 폴더 안 남음
            self.assertFalse([p for p in root.iterdir() if p.name.startswith(".cl-tmp")])
            # 목록에 둘 다
            self.assertEqual(len(drafts.list_projects(root)), 2)

            drafts.remove(root, res["folder"])
            self.assertFalse(dest.exists())
            self.assertEqual(len(drafts.read_json(root / "root_meta_info.json")["all_draft_store"]), 1)

    def test_failure_leaves_no_partial_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_root(Path(td))

            def boom(_):
                raise RuntimeError("boom")
            with self.assertRaises(RuntimeError):
                drafts.clone(root, root / "원본 프로젝트", "실패 사본", transform=boom)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["root_meta_info.json", "원본 프로젝트"])

    def test_duplicate_name_gets_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_root(Path(td))
            a = drafts.clone(root, root / "원본 프로젝트", "사본")
            b = drafts.clone(root, root / "원본 프로젝트", "사본")
            self.assertEqual((a["folder"], b["folder"]), ("사본", "사본 (2)"))


if __name__ == "__main__":
    unittest.main()
