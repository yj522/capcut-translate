# CapCut Translate

CapCut 프로젝트를 **통째로 복제**하면서 화면 글자(텍스트·자동 자막)를 다른 언어로 바꾼다.
원본은 건드리지 않는다. Windows·macOS 둘 다, 혼자 로컬에서 쓰는 도구.

## 실행

| OS | 방법 |
|---|---|
| Windows | `실행.bat` 더블클릭 |
| macOS | `실행.command` 더블클릭 (처음 한 번 «확인되지 않은 개발자» 경고가 나오면 우클릭 → 열기) |
| 공통 | `python app.py` (mac 은 `python3 app.py`) |

필요한 것: Python 3.9 이상뿐이고 설치할 패키지는 없다. 브라우저가 `http://127.0.0.1:3177` 로 열린다.

번역 엔진은 둘 중 하나를 쓴다.
- **OpenAI API 키**: 화면의 «설정»에 넣는다. 빠르다(기본 모델 `gpt-4.1-mini`).
- **codex CLI**: 키가 없으면 로그인 세션으로 번역한다(`codex login`).

## 쓰는 법

1. **CapCut 을 닫는다.** CapCut 은 종료할 때 프로젝트 목록 파일을 다시 쓰므로, 켜 둔 채 만들면 목록에서 사라진다. 화면 위쪽 표시가 «CapCut 꺼짐»이어야 만들 수 있다.
2. 왼쪽 목록에서 프로젝트를 고른다.
3. 만들 언어를 고른다(여러 개 가능).
4. «번역 미리보기» → 표에서 문장을 고친다. 고친 문장은 저장돼 복제에 그대로 쓰인다(선택 단계).
5. «N개 언어로 복제 만들기» → CapCut 을 켜면 `원래이름 [EN]` 같은 프로젝트가 보인다.

사본은 목록에서 원본 아래에 묶여 보이고, 상세 화면에서 «삭제»할 수 있다(이 앱이 만든 사본만).

## 고치기

빌드 단계가 없다. `.py` 를 저장하면 서버가 저절로 다시 뜨고, `ui/` 는 브라우저 새로고침만 하면 된다.

| 바꾸고 싶은 것 | 파일 |
|---|---|
| 화면 | `ui/index.html` · `ui/app.js` · `ui/style.css` |
| 번역 말투·프롬프트·언어 목록 | `translate.py` |
| 어떤 글자를 바꾸는지, 스타일 범위 보정 | `localize.py` |
| 폴더 찾기·복제·CapCut 목록 등록 | `drafts.py` |
| 번역 음성(Typecast) | `tts.py` |
| API | `app.py` |

테스트: `python -m unittest discover tests`

`data/`(git 제외)에는 설정, 번역 캐시(`translations.json`), 사본 대장, `root_meta_info` 백업이 쌓인다.

## CapCut 파일 규칙 (실측: CapCut 9.4 Windows, draft new_version 185.0.0)

- 프로젝트 폴더: Win `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft`,
  mac `~/Movies/CapCut/User Data/Projects/com.lveditor.draft`(App Store 판·剪映 도 후보). 못 찾으면 «설정»에서 지정한다.
- 본문 `draft_content.json` 은 **평문 JSON**이다. 같은 본문이 `.bak`·`template-2.tmp` 에도 있고, `Timelines/<id>/` 에도 한 벌 더 있다. 여섯 벌 모두 바꾼다.
- 폴더 안 소재 경로는 `##_draftpath_placeholder_<uuid>_##` 자리표시자라 복사해도 고치지 않는다.
- 폴더 절대경로·이름·ID 가 박힌 곳: `draft_meta_info.json`(다시 씀), `root_meta_info.json`(새 항목 추가), `Timelines/*/attachment/patch/mini_draft.json`(클라우드 동기 캐시 — 사본에서는 지운다).
- 텍스트 `content` 의 `styles[].range` 는 UTF-16 단위다(이모지 🍒 = 2칸 — 틀리면 마지막 글자가 스타일 밖으로 빠져 크게 나온다). 번역문 길이에 맞춰 비율로 보정한다.
- 자동 자막(`type: subtitle`)은 `base_content` 도 같이 바꾸고, 단어별 타이밍 `words` 는 비운다(번역하면 단어가 안 맞는다).

## 아직 안 되는 것

- 글자 읽어주기(TTS) 음성은 **Typecast API 키가 있을 때만** 번역 언어로 새로 만들어 바꾼다(«④ 음성»에서 CapCut 목소리마다 Typecast 목소리를 고른다). 키가 없거나 목소리를 정하지 않은 음성은 원어 그대로 남는다. 길어진 음성은 재생 속도를 최대 1.15배(`tts_max_speed`)까지 올리고, 그래도 넘치면 그 지점에서 영상을 늘려 뒤를 민다(내레이션 구간 자막은 같은 비율로 펼친다).
- 폰트 자동 교체를 하지 않는다. 한글 전용 폰트에 일본어·태국어 등을 넣으면 CapCut 이 대체 글꼴로 그리거나 글자가 빠질 수 있다.
- 글자가 길어져 넘치는 경우의 자동 축소를 하지 않는다.
