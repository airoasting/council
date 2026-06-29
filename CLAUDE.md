# CLAUDE.md — AI ROASTING 자문단 랜딩 페이지

이 폴더는 AI ROASTING 자문단(`/council` 스킬)을 소개하는 단일 페이지 `index.html`이다. 이 문서는 다음 작업자가 이 페이지를 이어서 수정할 때의 작업 지침이다.

## 무엇인가

- 산출물: `index.html` 한 파일(외부 의존성은 Google Fonts, Pretendard CDN, `../../assets/avatar/NN.png` 초상 이미지뿐).
- 주제: 25인의 거장(소크라테스부터 젠슨 황까지)을 5영역으로 묶어, 어려운 결정을 토론에 부치는 도구.
- 현재 디자인: Earth Archive(Stencil & Tablet) 시스템. 종이톤 + 어스 7색 + 스텐실 디스플레이 + 굵은 잉크 보더 + 라운디드 카드.

## 파일

- `index.html`: 정본(현재 = v12).
- `v1.html ~ v12.html`: 라운드별 백업. 되돌릴 일이 있으면 여기서 꺼낸다.
  - v11: 직전 다크 테마 + 회전목마 버전.
  - v12: Earth Archive 재스킨(현재).
- `EVALUATION.md`: 초기 web-builder 루프의 평가 로그.
- `.claude/launch.json`(상위 폴더): 미리보기 서버 설정.

## 페이지 구조 (뼈대, 보존)

위에서 아래로 다섯 구역이다. DOM 구조와 JS 훅(클래스·id)은 보존한다.

1. `nav#nav`: 고정 헤더. 스크롤하면 `.scrolled`로 본 배경 + 잉크 텍스트 전환.
2. `header.hero#top`: 풀블리드 블랙. 좌측 텍스트 + 우측 원자(canvas 궤도 + DOM 노드 점). 데스크톱은 좌우 분할 그리드, 모바일은 세로 스택.
3. `.zone-dark > #why`(`.cover`): 회전목마. 스크롤 구동 3D 실린더 캐러셀. 6장(영역 카드 5 + 로스팅 선언 카드 1).
4. `.page-light > #council`(`.block`): 자문단 25인. 영역별 원형 아바타 디스크 그리드.
5. `.zone-dark > #modes`(`.block`): 토론 모드 5종. 페이퍼 카드 + 노트 알약.
6. `footer.zone-black`: 풀블리드 블랙. 닫는 문장 + 칩 + 콜로폰.

> 참고: `.zone-dark` / `.page-light`는 v12에서 모두 본(`--bone`) 배경으로 재정의됐다. 이름만 과거 다크 시절의 잔재다.

## 디자인 토큰 (Earth Archive, 불변)

색은 아래 11색만 쓴다. 새 hex 도입 금지.

```
--bone #E2DCC9  본 종이 (밝은 배경)
--paper #F4EFE0 페이퍼 (카드 fill)
--ink #0A0A0A   잉크 (본문, 보더)
--black #000    풀블리드 블랙 (히어로, 푸터)
--sienna #A06A3C  --magenta #C73B7A  --orange #EE7A2E
--teal #2D7E73    --blue #3F73B7     --mustard #D8A93B  --olive #6F7A2E
```

도메인 → 색 매핑(JS `DOMAINS[].c`, 원자 점·캐러셀 띠·디스크에 동시 적용):

- 철학과 관점 = 시에나, 전략과 통치 권력 = 마젠타, 경영과 의사결정 = 머스타드, 기술과 AI = 틸, 투자와 자산 = 블루.
- 오렌지는 메인 액센트(헤드라인 `<em>`, 로스팅 선언 카드, CTA, 세그먼트).

폰트:

- 디스플레이/헤딩: `Stardos Stencil` (`--display`). 한글은 글리프가 없어 Pretendard로 폴백되고, 숫자·영문만 스텐실로 강조된다.
- 라벨/칩: `Barlow Condensed` (`--label`), 대문자 + 자간.
- 본문: `Pretendard` (`--sans`).
- `Bowlby One`(`--quote`)은 import만 되어 있고 현재 미사용(인용 컴포넌트 추가 시 사용).

## 콘텐츠 규칙 (보존)

- 헤드라인은 스텐실 본체 + 한 구절만 `<em>` 색 강조. `<em>`은 색만 바꾸고 이탤릭은 CSS가 normal로 강제(`i,em,.italic{font-style:normal}`). 새 이탤릭 금지.
- em dash(U+2014) 금지. 끊어 읽기는 쉼표·마침표·줄바꿈·콜론으로.
- 본문 종결은 `~합니다` / `~입니다`로 통일.
- 라운디드 카드 22~26px, 솔리드 잉크 보더가 시그니처. 직각·점선 카드 금지.

## 데이터 (JS 상단)

- `DOMAINS`(5): name, en, c(어스색).
- `PEOPLE`(25): d(도메인 인덱스), kr(전체 이름), s(짧은 이름, 원자 라벨용), en, p(한 줄 관점). 순서가 곧 아바타 번호(`card-0` ~ `card-24`, 이미지 `01.png` ~ `25.png`).
- `MODES`(5): cmd, t, d.
- 데이터를 고치면 원자·캐러셀·카드가 함께 갱신된다(빌더가 같은 배열을 읽음).

## 인터랙션 / 구현 메모

- 원자(ATOM ORBIT): 도메인당 궤도 1개(총 5개). canvas로 궤도선, DOM `.node`로 점. 점 hover → 캡션 갱신, 클릭 → 해당 자문단 카드로 스크롤 + `.flash`. 히어로가 화면 밖이면 rAF 정지.
- 회전목마: `#why`를 `460vh`로 키우고 `.cf-pin`을 `position:sticky`로 고정. 스크롤 진행도를 실린더 회전각으로 매핑. 표준 3D carousel 공식(트랙 `translateZ(-R) rotateY(θ)`, 카드 `rotateY(i·θ) translateZ(R)`).
  - sticky가 동작하려면 `body{overflow-x:clip}`이 필요하다(`hidden`은 스크롤 컨테이너를 만들어 sticky를 깬다). 바꾸지 말 것.
  - `scrollToIndex`는 `offsetTop`이 아니라 절대 페이지 좌표(`scrollY + getBoundingClientRect().top`)로 계산한다. 상위에 positioned 요소(`.zone-dark`)가 있어 `offsetTop`은 0이 나오기 때문.
- 자문단 카드: 스크롤 진입 시 70ms 간격 페이드 등장(IntersectionObserver).
- `prefers-reduced-motion`이면 원자는 정적 한 프레임, 카드 등장·전환 비활성.

## 미리보기 (중요)

- 상위 `.claude/launch.json`의 서버는 라이브 폴더가 아니라 별도 스크래치패드 스냅샷 경로에서 서빙한다. 편집한 `index.html`을 그 경로의 `output/council-landing/index.html`에 복사해야 미리보기에 반영된다.
- 큰 뷰포트(예: 1280)에서 스크롤한 스크린샷이 검게 잡히는 미리보기 버그가 있다. 검증은 모바일 폭(예: 414)에서 하면 안정적이다.
- 미리보기 탭이 비활성화되면 CSS 전환이 멈춰 캡처가 흐릴 수 있다. 실제 포커스된 브라우저에서는 정상 동작한다.

## 다음 작업 시 체크리스트

1. 색은 어스 11색만. 새 hex·새 폰트·새 그라데이션 도입 금지.
2. `<em>`은 한 헤드라인에 한 곳, 색만.
3. 카드 라운디드 + 솔리드 잉크 보더 유지.
4. em dash 0개, 본문 종결 통일.
5. JS 훅 클래스·id(`.node .pt .nm`, `.cf-card .cf-name .cf-list`, `.ccard .disc .cidx .cname`, `#cf-track #cf-cur #cf-prev`, `#domains #modes-grid`, `.domain` 등) 보존.
6. 슬라이드 라벨이 아니라 스크롤 페이지다. 슬라이드 덱으로 바꾸지 말 것(과거 요청 오해로 만들었다가 철회함).
