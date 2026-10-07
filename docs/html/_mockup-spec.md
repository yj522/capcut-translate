# CapCut Translate — 디자인 시안 공통 사양

로컬 전용 데스크톱 웹앱(브라우저, 1280~1600px 폭이 주 사용). 한국어 UI. CapCut 영상 프로젝트를 폴더째 복제하면서 화면 글자를 다른 언어로 번역한 사본을 만든다.

## 시안이 보여 줄 화면 (정적 HTML 한 장, 가짜 데이터, 동작 최소)
1. **상단 바**: 앱 이름 «CapCut Translate» + 로고, 상태 2개(«CapCut 꺼짐» = 정상/초록, «번역: codex CLI»), 오른쪽 버튼 «새로고침», «프로젝트 폴더», «설정».
2. **왼쪽 목록(사이드바)**: 검색창, «프로젝트 1 · 사본 1» 머리글,
   - 원본: 표지 썸네일(9:16), 이름 «폼클렌징으로 브러시빨지 마세요!장윤주 메이크업 쌤의세척법», «9월 9일 오후 08:21 · 0:46», 사본 언어 배지 EN — **선택된 상태**
   - 그 아래 들여쓴 사본: «… [EN]», 배지 EN
   - 목록이 비어 보이지 않게 가짜 원본 프로젝트 3~4개 더 추가해도 됨(예: «여름 캠핑 브이로그 쇼츠», «홈카페 라떼아트 3분 정리», «강아지 산책 루틴» — 일부는 JA·ZH 사본 배지)
3. **오른쪽 상세(원본 선택 상태)**:
   - 머리: 표지 큰 이미지(`assets/cover.jpg`, 9:16), 날짜·길이, 제목, 숫자 3개(화면 글자 21 / 번역할 문장 20 / 자동 자막 18), «폴더 열기» 버튼
   - 경고 한 줄: «글자 읽어주기(TTS) 음성 2개는 번역되지 않고 원래 언어 음성으로 남습니다.»
   - ① **만들 언어**: 칩 14개(English EN, 日本語 JA, 简体中文 ZH, 繁體中文 ZH-TW, Español ES, Français FR, Deutsch DE, Português PT, Русский RU, Tiếng Việt VI, Indonesia ID, ไทย TH, العربية AR, हिन्दी HI). English·日本語 선택됨. «2개 선택됨», «모두 해제».
   - ② **사본 이름**: 입력칸 `{name} [{lang}]` + 미리보기 줄 2개(EN: «… [EN]» 옆에 «이미 있음 — 하나 더 만듭니다» 경고, JA: «… [JA]»)
   - ③ **번역 확인·수정**: 언어별 진행률(English 20/20 완료, 日本語 6/20), «번역 안 된 것만» 체크, «번역 미리보기» 버튼. 표: 번호 | 원문 | English | 日本語 (편집 가능한 칸처럼 보이게, 일본어 일부 칸은 비어 «번역 전»)
     - 1. «폼클렌징으로 브러시\n빨지 마세요!\n장윤주 메이크업 쌤의\n세척법» → «Don’t wash your brushes\nwith face wash!\nJang Yoon-ju’s makeup artist\nshares her cleaning hack» / «洗顔料でブラシを\n洗わないで！»
     - 2. «🍒 체리돌» → «🍒 Cherry-dol» / «🍒 チェリードール»
     - 3. «박창수\n오늘자 송도 도로에서 벌어진 일.\n밤 10시 신호 대기 중인 오토바이.» → «Park Chang-su\nWhat happened on a Songdo road today.\nA motorcycle waiting at a red light at 10 PM.» / (비어 있음)
     - 4. «클렌징으로 하면 잘 안 되더라» → «Face wash never really gets them clean» / (비어 있음)
     - 5. «그 비누 있어요» → «You know that soap?» / «あの石けん、あるよ»
     - 6. «아이 깨끗해 비누로» → «I use Ai-Kkaekkeuthae hand soap» / (비어 있음)
   - **이 프로젝트의 사본**: 한 줄(EN 배지, «… [EN]», «10월 3일 오전 10:53», 보기·폴더·삭제)
   - **하단 고정 실행 바**: «원본은 그대로 두고 2개의 새 프로젝트를 만듭니다. 번역 안 된 문장은 자동으로 번역합니다.» + 큰 주 버튼 «2개 언어로 복제 만들기»

## 기술 조건
- 한 파일에 CSS·JS 인라인. 외부는 웹폰트 링크만 허용(실패해도 대체 폰트로 깨지지 않게). 한글 폰트 대체: Pretendard → "Apple SD Gothic Neo", "Malgun Gothic", sans-serif. Pretendard: `https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css`
- 이미지는 `assets/cover.jpg`(상대경로)만. 다른 썸네일은 CSS 그라디언트로.
- 언어 칩 클릭 토글 정도의 가벼운 JS는 괜찮음. 실제 API 호출 없음.
- 화면 오른쪽 아래에 작게 시안 이름 표기(예: «시안 A · shadcn»).
- 1400×900 화면에서 첫 화면에 상단 바·사이드바·상세 머리·①언어가 보여야 한다. 상세 영역만 스크롤, 하단 실행 바는 상세 영역 아래에 고정.
