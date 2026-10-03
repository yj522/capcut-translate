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
