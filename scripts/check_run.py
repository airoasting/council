#!/usr/bin/env python3
"""
자문단 실행 결과에서 기계로 셀 수 있는 항목만 채점한다.

칸끼리 같은 결론을 가리키는지, 판단 규칙의 갈래가 서로 겹치는지 같은 사람의 판단이
필요한 기준은 tests/CASES.md 의 수동 기준으로 남는다. 문장을 읽어 선택지를 맞추는
검사(판단 규칙의 결과절, 한눈에의 권고, 멈춤 신호)는 읽지 못하면 REVIEW 로 넘긴다.
이 스크립트를 통과해도 사례가 합격한 것은 아니다. FAIL 이 나오면 그 사례는 불합격이다.

    python3 scripts/check_run.py out.md --case tests/cases/03.md
    python3 scripts/check_run.py out.json --case tests/cases/03.md      # claude -p --output-format json 결과
    python3 scripts/check_run.py first.md --case tests/cases/09.md --stage convene
    python3 scripts/check_run.py tests/runs/2026-10-31.md --split       # 한 파일에 여러 사례
    python3 scripts/check_run.py --print-prompt tests/cases/01.md      # 사례의 실행 입력을 찍는다
    python3 scripts/check_run.py out.md --case tests/cases/03.md --answers answers.md
    python3 scripts/check_run.py --answers answers.md --case tests/cases/03.md   # 위원 원답만 채점
    python3 scripts/check_run.py --self-test                           # 선택지·숫자 비교의 자체 시험

--answers 는 위원 원답 파일(형식은 tests/CASES.md 6-2절)을 받는다. 주면 두 가지가 바뀐다.
    1. 숫자 검사(S10)가 REVIEW 대신 PASS/FAIL 로 확정된다. 허용 숫자는 입력 전문과
       위원 답의 "생각을 바꿀 조건" 칸뿐이다(라운드 3의 "실패한다면 그 이유"는 넣지 않는다).
    2. 위원 원답 기준 M1(직답이 선택지 안), M2(라벨이 그 위원의 세 라벨과 글자까지 같음),
       M4("확인되면 ... 바꾼다" 꼴), M10(답변 언어), M12(확신도 값)를 자동으로 판정한다.

단계(--stage, 기본은 사례 파일의 check, 없으면 synthesis)
    synthesis   종합 의견 (제목, 한눈에, 라벨 누출, 금지어, 판단 규칙 닫힘, 멈춤 신호, 최종 조언,
                단서, 표결, 언어, 분량, 숫자)
    convene     소집 공개 (형식, 인원, 선택지 확인 질문, 전문가 선정 규칙)
    no-council  토론을 돌리지 않았는지 (사례 06)
    ask-first   0단계에서 되물었는지 (사례 07)

상태: PASS 통과, FAIL 필수 실패, WARN 권장 미달, REVIEW 사람이 확정, SKIP 해당 없음.
종료 코드: 0 = FAIL 없음, 1 = FAIL 하나 이상, 2 = 사용법 오류.
표준 라이브러리만 쓴다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
EM_DASH = "\u2014"

# ---------------------------------------------------------------- 정본에서 옮긴 목록

# references/voice-rules.md 1절 "셀 수 있는 규칙". 그 절을 고치면 여기도 고친다.
BANNED_KO = [
    "다양한", "효과적인", "혁신적", "획기적", "게임 체인저", "게임체인저", "압도적", "강력한",
    "중요한 것은",
    "이 글에서는", "앞서 살펴본 바와 같이", "정리하자면", "주목할 점은", "흥미로운 점은",
    "흥미롭게도", "다시 말해", "제 렌즈로 답하자면",
    "당신도 그런 적 있을 것이다", "누구나 한 번쯤은",
    "점수를 깎", "벌점", "감점",
    "되어지", "만들어지게 된다",
]
SENTENCE_START_KO = ["또한", "그러나", "한편", "더불어", "아울러", "이는 결국"]

# references/voice-rules.md 1절 "영어로 쓸 때의 금지어" 줄을 읽는다. 줄이 없으면 아래 기본값.
BANNED_EN_DEFAULT = ["Moreover", "Furthermore", "It's worth noting", "game-changer", "robust",
                     "delve", "In conclusion"]
_SENT_START = r"(?:^|[.?!]\s+|^\s*(?:[-*>]|\d+\.)\s+)"


def _en_pattern(item):
    """금지어 한 항목을 정규식으로. '(문장 첫머리)'는 문장 첫머리만, '(동사)'는 동사로 쓸 때만 잡는다."""
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", item)
    word, note = (m.group(1), m.group(2)) if m else (item, "")
    word = word.strip().strip('"“”')
    if not word or word.lower() in ("em dash", "em-dash"):
        return None
    esc = re.escape(word).replace("\\-", "[- ]?").replace("'", "['’]").replace("\\ ", r"\s+")
    if "첫머리" in note or "start" in note.lower():
        return rf"{_SENT_START}{esc}\b"
    if "동사" in note or "verb" in note.lower():
        stem = re.escape(word[:-1] if word.endswith("e") else word)
        return (rf"\b(?:to|will|can|could|should|would|must|we|they|you|I)\s+{esc}\b"
                rf"|\b{stem}(?:ed|es|ing)\b")
    if " " in word or "-" in word or "'" in word:
        return rf"\b{esc}"
    if word.endswith("e"):
        return rf"\b{re.escape(word[:-1])}(?:e|es|ed|ing)\b"
    return rf"\b{esc}(?:s|ed|ing|ly)?\b"


def load_banned_en():
    """(목록 출처, [(항목, 정규식)])"""
    path = ROOT / "references" / "voice-rules.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(r"^\s*-\s*\*\*영어로 쓸 때의 금지어\.?\*\*\s*(.+?)\s*$", text, re.M)
    if m:
        items, src = [x.strip() for x in m.group(1).rstrip(".").split(",") if x.strip()], "voice-rules"
    else:
        items, src = BANNED_EN_DEFAULT, "기본값(voice-rules에 영어 목록 없음)"
    out = []
    for it in items:
        pat = _en_pattern(it)
        if pat:
            out.append((it, pat))
    return src, out

# SKILL.md 종합 규칙 8, voice-rules 4절 "내부 용어 숨김".
PROGRESS_TERMS_KO = ["라운드", "관문", "반대 변호", "교차심문", "재진술"]
PROGRESS_TERMS_EN = [r"\bround\s*[123]\b", r"\bround (?:one|two|three)\b",
                     r"devil'?s advocate", r"\bgate\b", r"cross-examination"]

# SKILL.md 4단계 템플릿과 "다른 언어로 토론할 때"의 영어 제목.
HEADINGS = {
    "ko": [
        ("glance", "한눈에", True),
        ("vote", "(?:직답 )?표결", True),
        ("unresolved", "아직 안 풀린 질문", True),
        ("split", "서로 엇갈린 지점", True),
        ("agree", "전문가들이 동의한 지점", False),
        ("stop", "멈춰야 할 신호", True),
        ("rule", "판단 규칙", True),
        ("first", "첫 번째 행동", True),
        ("final", "AI ROASTING의 최종 조언", True),
        ("record", "라운드 기록", False),
    ],
    "en": [
        ("glance", "At a glance", True),
        ("vote", "Direct-answer vote", True),
        ("unresolved", "Still unresolved", True),
        ("split", "Where they split", True),
        ("agree", "Where they agree", False),
        ("stop", "Stop signals?", True),
        ("rule", "Decision rules?", True),
        ("first", "First move", True),
        ("final", "AI ROASTING['’]s final advice", True),
        ("record", "Round(?:-by-round| record| log| history)", False),
    ],
}
GLANCE_KO = ["권고:", "뒤집힐 조건:", "이번 주 할 일:"]

# SKILL.md 종합 규칙 11. 플래그 -> (단서 문장, 반드시 들어갈 확인 항목).
QUALIFIER = {
    "ko": (r"전문가의? ?(?:조언|상담)을? 대신하지 않습니다", {
        "investing": [r"계좌", r"세금|소득세|과세", r"(?:자산|재산)\s*배분"],
        "legal": [r"계약", r"정관", r"세금|소득세|과세"],
        "data": [r"고객\s*동의", r"처리\s*계약"],
        "hr": [r"근로\s*계약", r"노동법"],
    }),
    "en": (r"(?:does not|doesn't|do not|don't) replace|not a substitute", {
        "investing": [r"account", r"tax", r"allocation"],
        "legal": [r"contract", r"bylaws|articles", r"tax"],
        "data": [r"consent", r"processing agreement|data processing"],
        "hr": [r"employment contract", r"labou?r law"],
    }),
}

UNKNOWN_BRANCH = {
    # "기한까지 확인하지 못하면" 갈래. 확인 대신 측정, 대화 같은 동사를 써도 갈래로 본다.
    "ko": r"확인\s*못\s*하면|확인되지\s*않으면|[가-힣]지\s*못\s*하면|못\s*(?:받|얻|듣)으면|기한까지[^.。]*?(?:없으면|않으면|못하면)",
    "en": r"(?:can(?:no|')t|could not|couldn't|unable to|not able to|fail to)\s+"
          r"(?:confirm|verify|measure|establish|find out|get)"
          r"|(?:not|isn't|is not)\s+(?:confirmed|verified)\s+by"
          r"|(?:aren't|are not|isn't|is not)\s+(?:ready|available|in|done|finished|complete)\s+by"
          r"|none of (?:the|these|this)\b.*?\b(?:is|are)\s+(?:confirmed|verified|clear)"
          r"|not (?:checked|confirmed|verified|measured|done) by",
}

SYN_RE = re.compile(r"^[ \t]*(?:>[ \t]*)?#{1,3}[ \t]*AI ROASTING (?:종합 의견|Verdict)[ \t]*$", re.M)
CASE_HEAD_RE = re.compile(r"^#{1,3}[ \t]*(?:사례|Case)[ \t]*0?(\d+)", re.M)


# ---------------------------------------------------------------- 결과 모음

class Report:
    def __init__(self, title):
        self.title = title
        self.items = []

    def add(self, status, cid, name, detail=""):
        self.items.append((status, cid, name, detail))

    def failed(self):
        return any(s == "FAIL" for s, *_ in self.items)

    def show(self):
        print(f"== {self.title} ==")
        for status, cid, name, detail in self.items:
            line = f"{status:<6} {cid:<4} {name}"
            if detail:
                line += f": {detail}"
            print(line)
        counts = {}
        for s, *_ in self.items:
            counts[s] = counts.get(s, 0) + 1
        order = ["PASS", "FAIL", "WARN", "REVIEW", "SKIP"]
        print("요약: " + " · ".join(f"{k} {counts[k]}" for k in order if k in counts))
        print()


# ---------------------------------------------------------------- 사례 파일

def parse_case(path):
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit(f"사례 파일에 머리말(--- ... ---)이 없습니다: {path}")
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        meta.setdefault(key.strip(), []).append(val.strip())

    def one(key, default=""):
        vals = meta.get(key)
        return vals[0] if vals and vals[0] else default

    blocks = re.findall(r"^```text\n(.*?)^```", text, re.S | re.M)
    options = [o.strip() for o in one("options").split(" / ") if o.strip()]
    return {
        "path": str(path),
        "id": one("id"),
        "title": one("title"),
        "mode": one("mode"),
        "prefix": one("prefix"),
        "members": [x.strip() for x in one("members").split(",") if x.strip()],
        "options": options,
        "extra_options": [x for x in meta.get("extra_option", []) if x],
        "language": one("language", "ko"),
        "flags": {f.strip() for f in one("flags").split(",") if f.strip()},
        "check": one("check", "synthesis"),
        "confirm_options": one("confirm_options", "optional"),
        "convene_count": int(one("convene_count")) if one("convene_count").isdigit() else None,
        "auto_select": one("auto_select").lower() in ("yes", "true", "1"),
        "must_contain": [x for x in meta.get("must_contain", []) if x],
        "must_not_contain": [x for x in meta.get("must_not_contain", []) if x],
        "input": blocks[0].strip() if blocks else "",
        "all_inputs": "\n".join(b.strip() for b in blocks),
    }


def find_case_file(cases_dir, num):
    p = Path(cases_dir) / f"{int(num):02d}.md"
    return p if p.exists() else None


# ---------------------------------------------------------------- 입력 읽기

def load_text(path):
    raw = Path(path).read_text(encoding="utf-8")
    meta = {}
    stripped = raw.lstrip()
    if path.endswith(".json") or stripped.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "result" in data:
            usage = data.get("usage") or {}
            meta = {
                "duration_s": round((data.get("duration_ms") or 0) / 1000, 1),
                "cost_usd": data.get("total_cost_usd"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cache_read": usage.get("cache_read_input_tokens"),
                "session_id": data.get("session_id"),
            }
            return data.get("result") or "", meta
    return raw, meta


def split_blocks(text):
    """'## AI ROASTING 종합 의견'(또는 Verdict) 블록을 잘라 (사례 번호, 블록) 목록으로 돌려준다."""
    starts = [m.start() for m in SYN_RE.finditer(text)]
    out = []
    for i, s in enumerate(starts):
        limit = starts[i + 1] if i + 1 < len(starts) else len(text)
        seg = text[s:limit]
        nl = seg.find("\n")
        if nl >= 0:
            m = re.search(r"^(?:---[ \t]*|#{1,2} .*)$", seg[nl + 1:], re.M)
            if m:
                seg = seg[: nl + 1 + m.start()]
        heads = list(CASE_HEAD_RE.finditer(text[:s]))
        out.append((heads[-1].group(1) if heads else None, seg.rstrip()))
    return out


# ---------------------------------------------------------------- 종합 파싱

def clean(line):
    line = re.sub(r"^\s*>\s?", "", line)
    return line.rstrip()


def heading_key(line, lang):
    # "**Direct-answer vote** (A / B): ..."처럼 제목 뒤에 내용이 붙은 줄도 제목으로 읽는다.
    s = re.sub(r"^#+\s*", "", line.strip()).replace("**", "").strip()
    if s.startswith(("- ", "* ")):
        return None
    for key, pat, _ in HEADINGS[lang]:
        if re.match(rf"^(?:{pat})(?:\s*$|\s*\(|\s*:)", s, re.I if lang == "en" else 0):
            return key
    return None


def parse_sections(lines, lang):
    """제목 줄 위치로 칸을 나눈다. {key: {"head": 제목 줄, "lines": [본문 줄], "idx": 위치}}"""
    marks = []
    for i, ln in enumerate(lines):
        k = heading_key(ln, lang)
        if k and k not in [m[0] for m in marks]:
            marks.append((k, i))
    secs = {}
    for j, (k, i) in enumerate(marks):
        end = marks[j + 1][1] if j + 1 < len(marks) else len(lines)
        secs[k] = {"head": lines[i], "lines": lines[i + 1:end], "idx": i}
    return secs


def bullets(sec_lines):
    return [ln.strip()[2:].strip() for ln in sec_lines if re.match(r"^\s*[-*]\s+", ln)]


def sentences(text):
    parts = re.split(r"(?<=[.?!])\s+", text.strip())
    return [p for p in parts if re.search(r"[가-힣A-Za-z]", p)]


def norm(s):
    # 하이픈도 뗀다: "Stop under $5k"와 "Stop under-$5k clients"의 줄임을 같게 본다.
    return re.sub(r"[\s\"'“”‘’.,()*\-‐–]", "", s).lower()


# ---------------------------------------------------------------- 선택지 맞추기
#
# 선택지 문장을 핵심 낱말(어간)의 묶음으로 바꿔 비교한다. 앞 두 글자만 겹쳐도 같다고 보던
# 옛 기준은 "지금 넣는다"를 "한 번에 넣는다"로 받아 줬다. 지금 기준은 이렇다.
#   - 글자가 같거나, 줄임말이 정확히 한 선택지의 글자 안에 들어가면 같은 선택지.
#   - 아니면 핵심 낱말이 서로 충분히 겹쳐야 한다(이쪽 낱말의 60% 이상이 저쪽에 있고,
#     저쪽 낱말의 50% 이상이 이쪽에 있음). 부정("않", "안", "못")이 같아야 하고, 숫자는
#     단위까지 같아야 하며, 가장 잘 맞는 선택지가 하나여야 한다.

_PARTICLES = sorted(["에서는", "으로는", "에게서", "까지", "부터", "에서", "으로", "에게", "처럼", "보다",
                     "만큼", "은", "는", "이", "가", "을", "를", "에", "로", "만", "도", "의", "와", "과"],
                    key=len, reverse=True)
_NEG = {"않", "안", "못", "말", "not", "no", "don't", "dont", "never", "without"}
_STOP_EN = {"the", "a", "an", "it", "them", "to", "of", "for", "we", "our", "you", "your", "and",
            "or", "on", "in", "by", "with", "this", "that", "is", "are", "be"}
_STOP_KO = {"것", "수", "더", "그", "이", "등", "및"}


def _syl(ch):
    c = ord(ch) - 0xAC00
    return c if 0 <= c < 11172 else -1


def _drop_final(ch, finals):
    """마지막 음절의 받침이 finals(종성 번호) 안이면 받침을 뗀다. ㄴ=4, ㅂ=17."""
    c = _syl(ch)
    if c >= 0 and c % 28 in finals:
        return chr(ord(ch) - c % 28)
    return ch


def stem(tok):
    t = re.sub(r"[^\w~$%:'’.-]", "", tok.lower()).strip(".'’-")
    if not t:
        return ""
    if re.fullmatch(r"[a-z'’$%0-9~:.,k-]+", t):  # 영어나 숫자
        if t in _STOP_EN:
            return ""
        if re.fullmatch(r"[a-z]{4,}s", t) and not t.endswith("ss"):
            t = t[:-1]
        return t
    if t.startswith("않"):
        return "않"
    if t.endswith("습니다") and len(t) > 3:
        t = t[:-3]
    elif t.endswith("니다") and len(t) > 2:
        t = t[:-2]
        t = t[:-1] + _drop_final(t[-1], {17})
    elif t.endswith("는다") and len(t) > 2:
        t = t[:-2]
    elif t.endswith("다") and len(t) > 1:
        t = t[:-1]
        t = t[:-1] + _drop_final(t[-1], {4})
    elif t.endswith("지") and len(t) > 1 and not t[0].isdigit():
        t = t[:-1]
    else:
        for p in _PARTICLES:
            if t.endswith(p) and len(t) > len(p):
                t = t[: -len(p)]
                if t in _NEG:  # "안의", "안에"는 부정이 아니다
                    t += "쪽"
                break
    if len(t) > 1 and t.endswith("하") and not t[0].isdigit():  # 거절하 = 거절, 요구하 = 요구
        t = t[:-1]
    return "" if t in _STOP_KO else t


def stems(text):
    """괄호 안을 빼고, 순서를 지킨 어간 목록."""
    text = re.sub(r"\([^)]*\)", " ", text)
    out = []
    for raw in re.split(r"[\s/,]+", text):
        s = stem(raw)
        if s:
            out.append(s)
    return out


def _is_num(s):
    return bool(re.match(r"^\$?\d", s))


def _num_eq(a, b):
    """숫자 낱말 둘이 같은 양인지(단위 환산, 범위 포함)."""
    qa, qb = quantities(a), quantities(b)
    if not qa or not qb:
        return a == b
    return any(_q_match(x, [y]) for x in qa for y in qb) or any(_q_match(y, [x]) for x in qa for y in qb)


def _has(stem_list, s):
    if _is_num(s):
        return any(_is_num(x) and _num_eq(s, x) for x in stem_list)
    return s in stem_list


def _negative(stem_list):
    return any(s in _NEG for s in stem_list)


def option_ok(v, options):
    """표결 선택지 v가 사례 선택지 가운데 정확히 하나를 가리키는지."""
    return match_option(v, options) is not None


def match_option(v, options):
    """선택지 뒤 괄호 풀이("양쪽 베스팅 (지금 지분은 두되 ...)")는 떼고 맞춘다. 돌려주는 값은 원래 표기다."""
    bare = {re.sub(r"\s*\([^)]*\)", "", o).strip() or o: o for o in options}
    hit = _match_option(v, list(bare))
    return bare.get(hit) if hit is not None else None


def _match_option(v, options):
    nv = norm(v)
    if not nv:
        return None
    for o in options:
        if norm(o) == nv:
            return o
    sv = stems(v)
    inside = [o for o in options if nv in norm(o)]
    if len(inside) == 1 and len(nv) >= 2:
        # 줄임말은 다른 선택지에 없는 낱말을 하나 이상 지녀야 한다("옮긴다"는 "옮기지 않는다"와 겹친다).
        others = {s for o in options if o != inside[0] for s in stems(o)}
        if any(not _negative([s]) and not _has(list(others), s) for s in sv):
            return inside[0]
    if not sv:
        return None
    # 소집 공개의 짧은 이름("기존 제품 안 기능")이 위원의 긴 문구 안에 낱말째 다 들어 있고,
    # 그런 선택지가 하나뿐이면 그 선택지다.
    # "안"은 부정어 목록에도 있어 "제품 안 기능"의 "안"(안쪽)은 "안에"(안쪽)와 같게 본다.
    whole = [o for o in options if len(stems(o)) >= 2
             and all(_has(sv, x) or (x == "안" and "안쪽" in sv) for x in stems(o))]
    if len(whole) == 1:
        return whole[0]
    best, best_score, tie = None, 0.0, False
    for o in options:
        so = stems(o)
        if not so or _negative(sv) != _negative(so):
            continue
        if any(_is_num(x) and not _has(so, x) for x in sv):
            continue
        hit_v = sum(1 for x in sv if _has(so, x))
        hit_o = sum(1 for x in so if _has(sv, x))
        if hit_v / len(sv) < 0.6 or hit_o / len(so) < 0.5:
            continue
        # 겹친 낱말 가운데 하나는 같은 부정 여부의 다른 선택지에 없는 낱말이어야 한다.
        # "넣는다"처럼 모든 선택지에 있는 동사 하나로는 고르지 못한다.
        rivals = [s for o2 in options if o2 != o for s in [stems(o2)] if _negative(s) == _negative(so)]
        if not any(_has(so, x) and not any(_has(r, x) for r in rivals) for x in sv if x not in _NEG):
            continue
        score = hit_v / len(sv) + hit_o / len(so)
        if score > best_score:
            best, best_score, tie = o, score, False
        elif score == best_score:
            tie = True
    return None if tie else best


def mentions(clause, options):
    """판단 규칙의 결과절 같은 자유 문장이 어느 선택지를 말하는지. 가장 잘 맞는 선택지 목록
    (없으면 빈 목록, 동점이면 둘 이상)을 돌려준다. options 는 [(이름, [같은 선택지의 다른 표기...])]."""
    sc = stems(clause)
    if not sc:
        return []
    neg_after = {i for i in range(len(sc) - 1) if sc[i + 1] in _NEG}
    all_stems = [set(s for t in alts for s in stems(t)) for _, alts in options]
    scores = []
    for idx, (name, alts) in enumerate(options):
        others = set().union(*(all_stems[:idx] + all_stems[idx + 1:])) if len(options) > 1 else set()
        best = 0.0
        for alt in alts:
            so = stems(alt)
            if not so:
                continue
            o_neg = _negative(so)
            if o_neg and not _negative(sc):
                continue
            hits, distinct, plain = 0, 0, 0
            for s in so:
                if s in _NEG:
                    ok = _negative(sc)
                elif _is_num(s):
                    ok = any(_is_num(x) and _num_eq(s, x) for x in sc)
                else:
                    pos = [i for i, x in enumerate(sc) if x == s]
                    ok = bool(pos) and (o_neg or any(i not in neg_after for i in pos))
                if ok:
                    hits += 1
                    plain += s not in _NEG
                    distinct += (s not in others) if not _is_num(s) else \
                        (not any(_is_num(x) and _num_eq(s, x) for x in others))
            score = hits / min(len(so), 4)
            if score >= 0.5 and distinct >= 1 and plain >= 1:
                best = max(best, score)
        scores.append(best)
    top = max(scores) if scores else 0
    return [options[i][0] for i, s in enumerate(scores) if s and s == top]


_COND_RE = re.compile(r"(?<!측)(?<!전)(?<!화)(?<!방)(?<!표)(?<!국)(?<!장)(?<!대)(?<!외)(?<!정)(?<!반)"
                      r"면[\s,(]")


def result_clauses(bullet, lang):
    """판단 규칙 불릿에서 결과절(조건 뒤의 '그러면 무엇을 한다')을 문장마다 뽑는다."""
    b = re.sub(r"\([^)]*\)", " ", bullet)
    if "→" in b:
        return [b.rsplit("→", 1)[1].strip()]
    out = []
    for sent in re.split(r"(?<=[.?!])\s+", b.strip()):
        if lang == "en":
            s = sent.strip()
            if re.match(r"^(?:if|unless|when|otherwise|else|by)\b", s, re.I):
                out.append(s.rsplit(",", 1)[1] if "," in s else s)
            else:
                out.append(re.split(r"\s(?:if|unless|when)\b", s, maxsplit=1, flags=re.I)[0])
        else:
            ms = list(_COND_RE.finditer(sent))
            if ms:
                out.append(sent[ms[-1].end():].strip(" ,"))
    return [x.strip() for x in out if x.strip()] or [b.strip()]


# ---------------------------------------------------------------- 숫자와 단위
#
# S10 은 기준 숫자와 사실 주장 숫자만 센다. 숫자는 단위와 함께 (값, 차원)으로 바꿔 비교한다.
# 1년 = 12개월 = 4분기, 반년 = 6개월, 2주 = 14일, 20% = 20퍼센트 = 20 percent, 2억 = 200,000,000원.
# 순번(1~3일차, 1번째, 목록 번호, (6) 같은 칸 번호), 날짜, 표결(4 대 1, 5명 중 4명, n/n 응답),
# 진행 숫자(라운드 1, 1단계)는 세지 않는다. 한글로 쓴 수(두 분기, 열 곳)는 세지 않는다.

_EXCLUDE = [
    r"\d{4}\s*-\s*\d{1,2}\s*-\s*\d{1,2}",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?\b",
    r"(?<![\d,.$])\b(?:19|20)\d{2}\b(?!\s*(?:%|명|원|달러|개))",
    r"\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?",
    r"(?<![\d.])\d{1,2}\s*월(?:\s*\d{1,2}\s*일)?",
    r"(?<!\d)[1-4]\s*분기(?!\s*(?:동안|간|째))",
    r"\d+\s*~\s*\d+\s*일\s*[차째]|\d+\s*일\s*[차째]|\b[Dd]ays?\s+\d+(?:\s*[–~-]\s*\d+)?|\d+\s*번째|제\s*\d+|\d+\s*순위|\d+\s*단계|\d+\s*라운드",
    r"라운드\s*\d+|[Rr]ound\s*\d+|\b\d+(?:st|nd|rd|th)\b|\bQ[1-4]\b|(?<![\d.])\d+차(?!원)",
    r"\d+\s*대\s*\d+(?:\s*대\s*\d+)*",
    r"\d+\s*명\s*중\s*\d+\s*명|\b\d+\s+of\s+\d+\b",
    r"\(\s*\d+\s*/\s*\d+\s*(?:응답|responded)?\s*\)",
    r"^\s*\d+[.)]\s", r"\(\d\)",
]
_MULT = {"조": 1e12, "억": 1e8, "천만": 1e7, "백만": 1e6, "만": 1e4, "천": 1e3}
# (단위 정규식, 차원, 배수). 긴 것부터.
_UNITS = [
    (r"퍼센트|프로|%|\s?percent\b|\s?pct\b", "pct", 1),
    (r"개월|\s?months?\b|\s?mos?\b", "month", 1),
    (r"달(?!러)", "month", 1),
    (r"분기|\s?quarters?\b", "month", 3),
    (r"년|해(?!석|결|외)|\s?years?\b|\s?yrs?\b", "month", 12),
    (r"주(?![식가주의택소장])|\s?weeks?\b|\s?wks?\b", "day", 7),
    (r"일(?![차본반부어정])|\s?days?\b", "day", 1),
    (r"시간|\s?hours?\b|\s?hrs?\b", "hour", 1),
    (r"분(?![기의야석])|\s?minutes?\b|\s?mins?\b", "minute", 1),
    (r"명|인(?![상하수분생재지])|-?\s?(?:people|persons?|employees|staff)\b", "person", 1),
    (r"곳|\s?(?:sites?|places?)\b", "place", 1),
    (r"건|\s?(?:cases?|deals?)\b", "case", 1),
    (r"개(?!월)|\s?items?\b", "item", 1),
    (r"회|번(?!째)|\s?times\b", "times", 1),
    (r"배|x\b", "multiple", 1),
    (r"살|세(?![금대계부])", "age", 1),
    (r"원", "krw", 1),
    (r"달러|\s?dollars?\b|\s?usd\b", "usd", 1),
    (r"\s?clients?\b|\s?customers?\b|고객", "client", 1),
]
_UNIT_RE = [(re.compile(rf"^(?:{u})", re.I), d, f) for u, d, f in _UNITS]


class Q:
    __slots__ = ("raw", "value", "dim", "lo", "hi")

    def __init__(self, raw, value, dim, lo=None, hi=None):
        self.raw, self.value, self.dim, self.lo, self.hi = raw, value, dim, lo, hi

    def __repr__(self):
        return self.raw


def _unit_after(text, pos):
    rest = text[pos:pos + 12]
    if rest.startswith("+"):  # "6+ months"
        rest = rest[1:]
    for skip in (0, 1):  # "3억 원"처럼 숫자와 단위 사이 한 칸까지
        if skip and not rest.startswith(" "):
            break
        for rx, dim, fac in _UNIT_RE:
            m = rx.match(rest[skip:])
            if m and (skip == 0 or re.match(r"[가-힣]", rest[1:2])):
                return dim, fac, m.end() + skip
    return None, 1, 0


def _blank(text, patterns):
    for pat in patterns:
        text = re.sub(pat, lambda m: " " * len(m.group(0)), text, flags=re.M | re.I)
    return text


_EN_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def quantities(text, exclude=True):
    """text 의 숫자를 Q 목록으로. exclude=False 면 순번·날짜·표결도 그대로 센다(허용 목록용).
    영어 숫자 낱말("six months")은 숫자로 바꿔 센다."""
    text = re.sub(r"\b(" + "|".join(_EN_NUM) + r")\b(?=\s+(?:months?|weeks?|days?|years?|quarters?|"
                  r"clients?|projects?|people|percent))", lambda m: str(_EN_NUM[m.group(1).lower()]), text, flags=re.I)
    t = _blank(text, _EXCLUDE) if exclude else text
    out = []
    used = [False] * len(t)

    def take(a, b):
        for i in range(a, min(b, len(t))):
            used[i] = True

    for m in re.finditer(r"반\s*년|반기|\bhalf\s+a\s+year\b", t, re.I):
        out.append(Q(m.group(0), 6, "month"))
        take(m.start(), m.end())
    for m in re.finditer(r"(\d+)\s*년\s*반", t):
        out.append(Q(m.group(0), int(m.group(1)) * 12 + 6, "month"))
        take(m.start(), m.end())
    for m in re.finditer(r"(?<![\d.])(\d+)\s*:\s*(\d+)(?![\d:])", t):
        for g in (1, 2):
            out.append(Q(m.group(0), float(m.group(g)), "ratio"))
        take(m.start(), m.end())
    num = r"(\d+(?:,\d{3})*(?:\.\d+)?)"
    for m in re.finditer(rf"\$\s*{num}\s*([kKmM])?\b", t):
        if any(used[m.start():m.end()]):
            continue
        v = float(m.group(1).replace(",", "")) * {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)
        out.append(Q(m.group(0).strip(), v, "usd"))
        take(m.start(), m.end())
    for m in re.finditer(rf"(?<![\w.]){num}\s*(조|억|천만|백만|만|천)(?:\s*{num}\s*(억|천만|백만|만|천))?", t):
        if any(used[m.start():m.end()]):
            continue
        v = float(m.group(1).replace(",", "")) * _MULT[m.group(2)]
        if m.group(3):
            v += float(m.group(3).replace(",", "")) * _MULT[m.group(4)]
        dim, _, n = _unit_after(t, m.end())
        if dim is None and m.group(2) in ("조", "억"):
            dim = "krw"
        out.append(Q((m.group(0) + t[m.end():m.end() + n]).strip(), v, dim))
        take(m.start(), m.end() + n)
    for m in re.finditer(rf"(?<![\w.]){num}\s*~\s*{num}", t):
        if any(used[m.start():m.end()]):
            continue
        dim, fac, n = _unit_after(t, m.end())
        lo, hi = float(m.group(1).replace(",", "")) * fac, float(m.group(2).replace(",", "")) * fac
        raw = (m.group(0) + t[m.end():m.end() + n]).strip()
        out += [Q(raw, lo, dim, lo, hi), Q(raw, hi, dim, lo, hi)]
        take(m.start(), m.end() + n)
    for m in re.finditer(rf"(?<![\w.$]){num}", t):
        if any(used[m.start():m.end()]):
            continue
        dim, fac, n = _unit_after(t, m.end())
        if dim is None and t[m.end():m.end() + 1] in ("k", "K"):
            dim, fac, n = "usd", 1000, 1
        raw = (m.group(0) + t[m.end():m.end() + n]).strip()
        out.append(Q(raw, float(m.group(1).replace(",", "")) * fac, dim))
        take(m.start(), m.end() + n)
    return out


def _q_match(q, allowed):
    for a in allowed:
        same_dim = (q.dim == a.dim or q.dim is None or a.dim is None
                    or {q.dim, a.dim} == {"ratio", "pct"})
        if not same_dim:
            continue
        if abs(q.value - a.value) <= 1e-6 * max(1.0, abs(a.value)):
            return True
        if a.lo is not None and q.dim == a.dim and a.lo <= q.value <= a.hi:
            return True
    return False


def load_labels():
    """agents/*.md 의 "제가 결론을 내리는 법"에서 '- 라벨. 설명' 꼴의 라벨을 모은다."""
    labels = {}
    for f in sorted((ROOT / "agents").glob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^## 제가 결론을 내리는 법\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
        if not m:
            continue
        for ln in m.group(1).splitlines():
            mm = re.match(r"^-\s+\**(.+?)\**\.(?:\s|$)", ln)
            if mm:
                labels.setdefault(mm.group(1).strip(), set()).add(f.stem)
    return labels


def label_pattern(label):
    """긴 라벨은 어디서든, 짧은 라벨(공백 빼고 4자 이하)은 라벨 자리에서만 잡는다."""
    esc = re.escape(label)
    if len(label.replace(" ", "")) >= 5:
        return esc
    return rf"[(（]\s*{esc}\s*[,，)）]|{esc}\s*,\s*확신도"


def detect_lang(text, case):
    if case and case.get("language"):
        return case["language"]
    return "en" if re.search(r"AI ROASTING Verdict", text) else "ko"


# ---------------------------------------------------------------- 단계별 검사

def check_common(rep, text, case):
    if not case:
        return
    for pat in case["must_contain"]:
        ok = re.search(pat, text, re.M) is not None
        rep.add("PASS" if ok else "FAIL", "C1", f"사례 필수 문구 /{pat}/", "" if ok else "없음")
    for pat in case["must_not_contain"]:
        m = re.search(pat, text, re.M)
        rep.add("FAIL" if m else "PASS", "C2", f"사례 금지 문구 /{pat}/", f"'{m.group(0)}' 있음" if m else "")


def vote_options(secs):
    """종합의 직답 표결 줄 괄호 안 선택지 목록. 관문에서 선택지를 더했으면 사례 파일보다 많다."""
    if "vote" not in secs:
        return []
    m = re.search(r"\(([^)]*)\)", secs["vote"]["head"])
    return [x.strip() for x in m.group(1).split("/") if x.strip()] if m else []


def vote_counts(secs, opt_table):
    """표결 줄의 "{선택지} n명"(영어 "{option} n")에서 선택지별 표 수. 읽지 못한 선택지는 None."""
    if "vote" not in secs:
        return {}
    head = secs["vote"]["head"].replace("**", "")
    tail = head.split(")", 1)[1] if ")" in head else head
    out = {}
    for name, alts in opt_table:
        n = None
        for a in alts:
            # 표결 항목의 앞(줄 처음, 쉼표, 콜론 뒤)에서만 맞춘다. "수락"이 "조건 걸고 수락 1명"에 걸리지 않게.
            m = re.search(r"(?:^|[,:：]\s*)" + re.escape(a) + r"\s*[:：]?\s*(\d+)", tail.strip())
            if m:
                n = int(m.group(1))
                break
        out[name] = n
    # 표결 줄이 0명인 선택지를 적지 않았으면(다른 선택지는 셌으면) 0으로 본다.
    if any(v for v in out.values()):
        out = {k: (0 if v is None else v) for k, v in out.items()}
    return out


def option_table(secs, case):
    """[(이름, [같은 선택지의 표기들])]. 표결 줄의 표기와, 그것이 가리키는 사례 선택지를 묶는다."""
    case_opts = (case["options"] + case["extra_options"]) if case else []
    vote = vote_options(secs)
    table = []
    for v in vote or case_opts:
        alts = [v]
        o = match_option(v, case_opts) if case_opts else None
        if o and o != v:
            alts.append(re.sub(r"\s*\([^)]*\)", "", o).strip() or o)
        table.append((v, alts))
    return table


GLANCE_REC = {"ko": r"^권고\s*[:：]\s*", "en": r"^(?:Recommendation|Recommend(?:ed)?)\s*[:：]\s*"}
FINAL_POINTERS = {
    "ko": r"판단 규칙|갈래|멈춰야 할 신호|멈춤 신호|한눈에|첫 번째 행동|서로 엇갈린 지점|아직 안 풀린 질문",
    "en": r"decision rule|\bbranch(?:es)?\b|\b(?:first|second|third|last) (?:line|rule)\b|stop signal"
          r"|at a glance|first move|where they split",
}
REOPEN = {"ko": r"(?:이 )?질문을 접고.*다시 엽니다", "en": r"set (?:this|the) question aside|reopen"}
NOT_A_RESULT = {"ko": r"조사|재토론|다시 (?:판단|논의|토론|따져)|더 알아보|논의합니다|검토합니다",
                "en": r"research|revisit|re-?discuss|re-?evaluate|investigate|look into|decide later"}
DEFAULT_BRANCH = {"ko": r"어느 조건에도 들지 않|어디에도 (?:맞지|들지) 않",
                  "en": r"none of the (?:conditions|rules|lines|branches) (?:below )?(?:apply|fit|match)"}
BELOW_BAR = {"ko": r"못 미치|미달|기준 이하|기준보다 (?:낮|적)|넘지 못",
             "en": r"below|short of|falls? short|under the (?:bar|threshold)|not enough"}


def strip_tally(line):
    """권고 줄 끝의 표결 괄호 '(5명 중 4명)', '(3 대 1)', '(만장일치)'를 뗀다."""
    return re.sub(r"\s*\([^()]*(?:\d|만장일치|unanimous)[^()]*\)\s*$", "", line, flags=re.I)


def check_synthesis(rep, text, case, answers, labels):
    lang = detect_lang(text, case)
    lines = [clean(ln) for ln in text.splitlines()]
    secs = parse_sections(lines, lang)
    rec_idx = secs["record"]["idx"] if "record" in secs else len(lines)
    body_lines = lines[:rec_idx]
    body = "\n".join(body_lines)
    options = (case["options"] + case["extra_options"]) if case else []
    opt_table = option_table(secs, case)
    qual_re = QUALIFIER[lang][0]

    # S1 em dash
    n = text.count(EM_DASH)
    rep.add("PASS" if n == 0 else "FAIL", "S1", "em dash 0개", f"{n}개" if n else "")

    # S2 필수 제목
    req = [k for k, _, r in HEADINGS[lang] if r]
    missing = [dict((k, p) for k, p, _ in HEADINGS[lang])[k] for k in req if k not in secs]
    rep.add("PASS" if not missing else "FAIL", "S2", "필수 제목",
            "없음: " + ", ".join(m.replace("\\", "") for m in missing) if missing else "")

    # S3 한눈에 세 줄
    glance = [b.replace("**", "") for b in bullets(secs["glance"]["lines"])] if "glance" in secs else []
    if "glance" in secs:
        if lang == "ko":
            ok = len(glance) == 3 and all(b.startswith(p) for b, p in zip(glance, GLANCE_KO))
            want = " / ".join(GLANCE_KO)
        else:
            ok = len(glance) == 3 and all(re.match(r"^[^:]{2,40}:\s*\S", b) for b in glance)
            want = "'라벨: 내용' 꼴 세 줄"
        rep.add("PASS" if ok else "FAIL", "S3", "한눈에 세 줄",
                "" if ok else f"불릿 {len(glance)}개, 기대: {want}")
    else:
        rep.add("FAIL", "S3", "한눈에 세 줄", "한눈에 칸이 없음")

    # S19 라운드 기록이 맨 아래
    if "record" in secs:
        after = [k for k, s in secs.items() if s["idx"] > rec_idx]
        rep.add("PASS" if not after else "FAIL", "S19", "라운드 기록이 맨 아래",
                "" if not after else "뒤에 오는 칸: " + ", ".join(after))
    else:
        rep.add("FAIL", "S19", "라운드 기록이 맨 아래", "라운드 기록 칸이 없음")

    # S4 본문에 판정 라벨과 진행 용어가 새지 않음
    hits = []
    if lang == "ko":
        for lab, owners in labels.items():
            m = re.search(label_pattern(lab), body)
            if m:
                hits.append(f"라벨 '{lab}'({'/'.join(sorted(owners))})")
        for term in PROGRESS_TERMS_KO:
            if term in body:
                hits.append(f"진행 용어 '{term}'")
        rep.add("PASS" if not hits else "FAIL", "S4", "본문(라운드 기록 앞)에 라벨·진행 용어 0",
                "; ".join(hits))
    else:
        for pat in PROGRESS_TERMS_EN:
            m = re.search(pat, body, re.I)
            if m:
                hits.append(f"진행 용어 '{m.group(0)}'")
        rep.add("PASS" if not hits else "FAIL", "S4", "본문에 진행 용어 0", "; ".join(hits))
        rep.add("SKIP", "S4", "본문에 판정 라벨 0", "라벨 정본이 한국어라 영어 종합은 손으로 본다")

    # S5 금지어 (voice-rules 1절)
    if lang == "ko":
        found = [w for w in BANNED_KO if w in text]
        pat = r"(?:^|[.?!]\s+|^\s*(?:[-*>]|\d+\.)\s+)(" + "|".join(SENTENCE_START_KO) + r")(?=[\s,]|으로)"
        found += [f"문두 '{m.group(1)}'" for m in re.finditer(pat, text, re.M)]
        rep.add("PASS" if not found else "FAIL", "S5", "금지어 0 (voice-rules 1절)", ", ".join(found))
    else:
        src, banned = load_banned_en()
        found = []
        for item, pat in banned:
            m = re.search(pat, text, re.M | re.I)
            if m:
                found.append(f"{item} ('{m.group(0).strip()}')")
        rep.add("PASS" if not found else "FAIL", "S5", f"영어 금지어 0 (목록: {src}, {len(banned)}개)",
                ", ".join(found))

    # S6, S7 판단 규칙
    rule_bl = bullets(secs["rule"]["lines"]) if "rule" in secs else []
    branch_opts = []  # 불릿마다 결과절이 가리키는 선택지 목록
    if "rule" in secs:
        rule_text = "\n".join(secs["rule"]["lines"])
        ok = re.search(UNKNOWN_BRANCH[lang], rule_text, re.I) is not None
        rep.add("PASS" if ok else "FAIL", "S6", "판단 규칙에 '기한까지 확인하지 못하면' 갈래",
                "" if ok else "갈래 없음")
        if opt_table:
            for b in rule_bl:
                got = []
                for cl in result_clauses(b, lang):
                    for o in mentions(cl, opt_table):
                        if o not in got:
                            got.append(o)
                branch_opts.append(got)
            covered = {o for g in branch_opts for o in g}
            votes = vote_counts(secs, opt_table)
            # 아무도 고르지 않은 선택지(표결 0명)는 판단 규칙에서 빼도 된다(SKILL.md 종합 규칙 4).
            miss = [name for name, _ in opt_table if name not in covered and votes.get(name) != 0]
            rep.add("PASS" if not miss else "FAIL", "S7",
                    "판단 규칙 닫힘: 표결 선택지마다 결과로 가는 갈래가 있음",
                    "결과절에 한 번도 안 나온 선택지: " + ", ".join(miss) if miss else
                    f"선택지 {len(opt_table)}개 모두 결과절에 있음")
            stall = [b[:30] for b, g in zip(rule_bl, branch_opts) if not g and any(
                re.search(NOT_A_RESULT[lang], cl, re.I) for cl in result_clauses(b, lang))]
            if stall:
                rep.add("FAIL", "S7", "판단 규칙 닫힘: 결과가 재토론·추가 조사가 아님",
                        "; ".join(f"'{x}...'" for x in stall))
            loose = [b[:30] for b, g in zip(rule_bl, branch_opts) if len(g) != 1 and b[:30] not in stall]
            if loose:
                rep.add("REVIEW", "S7", "판단 규칙 닫힘: 갈래마다 결과가 선택지 하나",
                        f"{len(loose)}개 갈래의 결과절을 선택지 하나로 읽지 못함, 손으로 확인: "
                        + "; ".join(f"'{x}...'" for x in loose))
            if not re.search(BELOW_BAR[lang], rule_text, re.I):
                rep.add("REVIEW", "S7", "판단 규칙 닫힘: '확인됐지만 기준에 못 미침' 경우",
                        "그 경우를 다루는 갈래 문구를 찾지 못함, 다른 갈래가 덮는지 손으로 확인")
    else:
        rep.add("FAIL", "S6", "판단 규칙에 '기한까지 확인하지 못하면' 갈래", "판단 규칙 칸이 없음")

    # S21 한눈에의 권고: 선택지 하나를 고르는 문장, 판단 규칙의 기본 갈래와 같음
    if glance and opt_table:
        rec = re.sub(GLANCE_REC[lang], "", glance[0], flags=re.I)
        rec = strip_tally(rec)
        picked = mentions(rec, opt_table)
        if len(picked) == 1:
            rep.add("PASS", "S21", "한눈에 권고가 선택지 하나를 고름", picked[0])
        elif not picked:
            # 풀어 쓴 권고("기존 제품 안에 AI 기능부터 넣습니다")는 사람이 읽으면 어느 선택지인지 안다.
            rep.add("REVIEW", "S21", "한눈에 권고가 선택지 하나를 고름",
                    f"권고 줄에서 표결 선택지를 찾지 못함: '{rec[:40]}'")
        else:
            rep.add("REVIEW", "S21", "한눈에 권고가 선택지 하나를 고름",
                    "선택지 둘 이상이 같은 정도로 읽힘: " + ", ".join(picked))
        if re.search(r"다수|majority", rec, re.I):
            rep.add("REVIEW", "S21", "권고가 다수라는 사실만 적지 않음", "'다수' 표현이 있음, 선택을 말하는지 확인")
        # 기본 갈래 = "확인했고 아래 어느 조건에도 들지 않으면" 줄. 옛 꼴이면 "확인하지 못하면" 줄.
        default = [g for b, g in zip(rule_bl, branch_opts) if re.search(DEFAULT_BRANCH[lang], b, re.I)] or \
                  [g for b, g in zip(rule_bl, branch_opts) if re.search(UNKNOWN_BRANCH[lang], b, re.I)]
        if len(picked) == 1 and default and len(default[0]) == 1:
            same = default[0][0] == picked[0]
            rep.add("PASS" if same else "REVIEW", "S21", "권고 = 판단 규칙의 기본 갈래",
                    "" if same else f"권고 '{picked[0]}', 기본 갈래 '{default[0][0]}'. 의도한 차이인지 확인")

    # S10b 기준 방향: 판단 규칙 갈래의 "(X 기준)"마다 X의 생각을 바꿀 조건 문장 가운데 그 갈래의 숫자를
    # 담은 문장을 찾고, 그 문장이 바꾸겠다고 한 선택지와 갈래의 결과를 대조한다.
    #   다름(그리고 그 결과가 X 자신의 직답도 아님) -> FAIL, 숫자 문장을 못 찾고 X가 그 선택지를 말한 적도 없음 -> REVIEW.
    if answers and rule_bl and opt_table and lang == "ko":
        flips, unsure = [], []
        for b, g in zip(rule_bl, branch_opts):
            if len(g) != 1:
                continue
            b_nums = [q for q in quantities(re.sub(r"\([^()]*\)", " ", b)) if q.value]
            for par in re.findall(r"\(([^()]*?)\s*기준[^()]*\)", b):
                par = re.sub(r"^[^가-힣]*|[0-9%개월년명곳건배.,]+은?\s*", " ", par)
                for nm in [x.strip() for x in re.split(r"[·,/]|\s와\s|\s과\s|\s", par) if len(x.strip()) >= 2]:
                    blks = [x for x in answers if nm in x["member"]]
                    if not blks:
                        continue
                    own = set()
                    for x in blks:
                        for v in x["cells"].get("answer", []):
                            own.update(mentions(v, opt_table))
                    targets, said = set(), set()
                    for x in blks:
                        for v in x["cells"].get("change", []):
                            for sent in sentences(v) or [v]:
                                ms = mentions(sent, opt_table)
                                said.update(ms)
                                if b_nums and any(_q_match(q, quantities(sent, exclude=False)) for q in b_nums):
                                    if not re.search(r"바꾸|바꿉|바꾼", sent):
                                        continue
                                    # '직답을 "A"나 "B"로 바꿉니다'면 A, B 모두. 따옴표가 없으면 "직답을 ...로".
                                    # '"A"가 아니라 ...'처럼 부정된 따옴표는 목표가 아니다.
                                    cands = [m.group(1) for m in re.finditer(r"[\"“']([^\"”']+)[\"”']", sent)
                                             if not re.match(r"\s*(?:이|가)?\s*아니라", sent[m.end():])]
                                    if not cands:
                                        tm = re.search(r"직답을\s*(.+?)\s*(?:으로|로)\s*바", sent)
                                        cands = [tm.group(1)] if tm else []
                                    for c in cands:
                                        tv = re.sub(r"\s*\([^)]*\)", "", c).strip()
                                        hit = match_option(tv, [n for n, _ in opt_table]) if tv else None
                                        if hit:
                                            targets.add(hit)
                    # 기준 미달 쪽 갈래가 그 위원 자신의 직답이면 같은 숫자를 써도 된다(SKILL.md 종합 규칙 5).
                    below = re.search(r"미만|아래|이하|못 미치|않으면|없으면|못하면", b)
                    if targets and g[0] not in targets and not (g[0] in own and below):
                        flips.append(f"'{b[:26]}...' → {g[0]}, {nm}의 같은 숫자 조건은 → {', '.join(sorted(targets))}")
                    elif not targets and g[0] not in said and g[0] not in own:
                        unsure.append(f"'{b[:26]}...' → {g[0]} ({nm} 기준)")
        if flips:
            rep.add("FAIL", "S10b", "판단 규칙의 출처 전문가가 그 선택지를 말했는가", "방향이 다름: " + "; ".join(flips[:4]))
        elif unsure:
            rep.add("REVIEW", "S10b", "판단 규칙의 출처 전문가가 그 선택지를 말했는가",
                    "원답에서 찾지 못함, 방향을 뒤집어 옮기지 않았는지 확인: " + "; ".join(unsure[:4]))
        else:
            rep.add("PASS", "S10b", "판단 규칙의 출처 전문가가 그 선택지를 말했는가")

    # S9b 동의한 지점과 판단 규칙의 충돌: "X는 하지 않는다/끊지 않는다" 꼴의 동의가 있는데
    # 판단 규칙에 그 X로 가는 갈래가 있으면 확인한다.
    if "agree" in secs and rule_bl and opt_table:
        neg = r"않|말아|말고|don'?t|do not|not |never|no one"
        clash = []
        for ab in bullets(secs["agree"]["lines"]):
            if not re.search(neg, ab, re.I):
                continue
            for o in mentions(ab, opt_table):
                if any(o in g for g in branch_opts):
                    clash.append(f"'{ab[:26]}...' 대 갈래 결과 {o}")
        rep.add("REVIEW" if clash else "PASS", "S9b", "동의한 지점과 판단 규칙이 부딪치지 않음",
                "; ".join(clash[:3]) + " (정말 반대 결과인지 확인)" if clash else "")

    # S22 멈춤 신호의 결과
    if "stop" in secs and opt_table:
        bad = []
        for b in bullets(secs["stop"]["lines"]):
            if re.search(REOPEN[lang], b, re.I):
                continue
            got = {o for cl in result_clauses(b, lang) for o in mentions(cl, opt_table)}
            if len(got) != 1:
                bad.append(b[:30])
        rep.add("PASS" if not bad else "REVIEW", "S22",
                "멈춤 신호의 결과가 선택지 하나이거나 '질문을 접고 다시 엽니다'",
                "" if not bad else "손으로 확인: " + "; ".join(f"'{x}...'" for x in bad))

    # S12 최종 조언이 칸 이름이나 갈래 번호를 가리키지 않음
    if "final" in secs:
        ftxt = "\n".join(secs["final"]["lines"])
        m = re.search(FINAL_POINTERS[lang], ftxt, re.I)
        rep.add("FAIL" if m else "PASS", "S12", "최종 조언이 칸 이름·갈래 번호를 가리키지 않음",
                f"'{m.group(0)}' 있음, 가르는 사실을 평범한 말로 적는다" if m else "")

    # S15 직답 표결의 선택지가 사례 선택지 안
    if "vote" in secs and options:
        vote_opts = vote_options(secs)
        if vote_opts:
            bad = [v for v in vote_opts if not option_ok(v, options)]
            rep.add("PASS" if not bad else "FAIL", "S15", "직답 표결 선택지가 사례 선택지 안",
                    "" if not bad else "사례 선택지 하나로 읽히지 않는 것: " + ", ".join(bad))
        else:
            rep.add("FAIL", "S15", "직답 표결 선택지가 사례 선택지 안", "표결 줄에 (선택지 목록)이 없음")
    elif options:
        rep.add("FAIL", "S15", "직답 표결 선택지가 사례 선택지 안", "직답 표결 칸이 없음")
    else:
        rep.add("SKIP", "S15", "직답 표결 선택지", "사례 파일 없음")

    # S16 자격 단서
    flags = case["flags"] if case else set()
    if flags:
        common, table = QUALIFIER[lang]
        idx = next((i for i, ln in enumerate(lines) if re.search(common, ln, re.I)), None)
        # 단서가 "다음을 확인하는 편이 안전합니다:" 뒤에 목록으로 이어지면 끝까지 함께 본다.
        line = "\n".join(lines[idx:]) if idx is not None else None
        if not line:
            rep.add("FAIL", "S16", "자격 단서 문장", "단서 문장이 없음")
        for flag in sorted(flags):
            if not line or flag not in table:
                continue
            miss = [p for p in table[flag] if not re.search(p, line, re.I)]
            rep.add("PASS" if not miss else "FAIL", "S16", f"자격 단서의 확인 항목 ({flag})",
                    "" if not miss else "빠짐: " + ", ".join(p.replace("\\s*", " ") for p in miss))
    else:
        rep.add("SKIP", "S16", "자격 단서", "사례에 투자·법률·데이터·인사 플래그 없음")

    # S17 언어
    h = len(re.findall(r"[가-힣]", body))
    lat = len(re.findall(r"[A-Za-z]", body))
    ratio = h / (h + lat) if (h + lat) else 0
    if lang == "en":
        ok = ratio < 0.05
        rep.add("PASS" if ok else "FAIL", "S17", "언어 (영어, 한글 비율 5% 미만)", f"한글 비율 {ratio:.1%}")
    else:
        ok = ratio >= 0.6
        rep.add("PASS" if ok else "FAIL", "S17", "언어 (한국어, 한글 비율 60% 이상)", f"한글 비율 {ratio:.1%}")

    # S14 분량과 불릿 (voice-rules 4절). 공백 포함 글자 수. 빼는 것: 종합 제목 줄, 직답 표결 칸
    # (표결 줄과 그 아래 위원별 불릿), 라운드 기록, 자격 단서 한 줄, 빈 줄, 불릿 기호 "- ".
    skip_keys = {"vote", "record"}
    counted = []
    for k, s in secs.items():
        if k in skip_keys:
            continue
        counted.append(s["head"])
        counted += [ln for ln in s["lines"] if not re.search(qual_re, ln, re.I)]
    if lang == "ko":
        chars = sum(len(re.sub(r"^\s*[-*]\s+", "", ln).strip()) for ln in counted)
        st = "PASS" if chars <= 1800 else ("WARN" if chars <= 2200 else "FAIL")
        rep.add(st, "S14", "본문 분량 (공백 포함, 표결 칸·라운드 기록·자격 단서 제외, 2,200자 이하, "
                "권장 1,600자 안팎, 1,800자를 넘으면 WARN)", f"{chars}자")
    too_many, too_long = [], []
    for k, s in secs.items():
        if k in skip_keys:
            continue
        bl = bullets(s["lines"])
        limit = 3
        if k == "rule" and opt_table:
            limit = max(3, len(opt_table) + 2)
        if len(bl) > limit:
            too_many.append(f"{k} {len(bl)}개(한도 {limit})")
        if any(re.match(r"^\s{2,}[-*]\s+", ln) for ln in s["lines"]):
            too_many.append(f"{k} 하위 불릿")
        for b in bl:
            cap = 1 if k == "glance" else 3
            if len(sentences(b)) > cap:
                too_long.append(f"{k}: '{b[:24]}...'")
    rep.add("PASS" if not too_many else "FAIL", "S14",
            "칸마다 불릿 셋까지, 하위 불릿 없음 (판단 규칙은 선택지 수 + 2까지)", ", ".join(too_many))
    rep.add("PASS" if not too_long else "FAIL", "S14", "불릿 하나에 세 문장까지 (한눈에는 한 문장)",
            f"{len(too_long)}개: " + "; ".join(too_long[:4]) if too_long else "")

    # S10 지어낸 숫자 (기준 숫자와 사실 주장 숫자, 단위까지 비교)
    if case:
        source = " ".join([case["all_inputs"], case["prefix"], " ".join(options)])
        allowed = quantities(source, exclude=False)
        from_answers, from_any = [], []
        note = ""
        if answers is not None:
            cells = [c for blk in answers for c in blk["cells"].get("change", [])]
            # 사전 부검("실패한다면 그 이유")은 상상한 장면이라 뺀다(CASES.md 3절).
            # 라운드 2(교차심문, 반대 변론)처럼 칸이 없는 답은 본문 전체를 쓴다.
            from_any = quantities(" ".join(
                (" ".join(v for k, vs in blk["cells"].items() if k != "premortem" for v in vs)
                 if blk["cells"] else blk["text"]) for blk in answers), exclude=False)
            if cells:
                from_answers = quantities(" ".join(cells), exclude=False)
            else:
                note = " (원답 파일에서 '생각을 바꿀 조건' 칸을 하나도 읽지 못함, CASES.md 6-2절 형식 확인)"
        extra, unattributed = [], []
        for k, s in secs.items():
            if k in skip_keys:
                continue
            for ln in [s["head"]] + s["lines"]:
                if re.search(qual_re, ln, re.I):
                    continue
                scan = ln
                if k == "glance" and re.match(r"^\s*[-*]\s*" + GLANCE_REC[lang].lstrip("^"), ln, re.I):
                    scan = strip_tally(ln)
                strict = k in ("rule", "stop")
                for q in quantities(scan):
                    if q.value == 0:  # "0명", "한 건도 없으면"의 0은 지어낼 수 있는 기준이 아니다
                        continue
                    if _q_match(q, allowed):
                        continue
                    # 판단 규칙과 멈춤 신호 밖(첫 행동, 엇갈린 지점 등)은 위원 답 어디에 있던 숫자든 받는다.
                    if not strict and _q_match(q, from_any):
                        continue
                    if _q_match(q, from_answers):
                        # 한눈에는 60자 안팎의 요약이라 출처 괄호를 요구하지 않는다(판단 규칙 쪽에 있으면 된다).
                        if strict and not re.search(r"\([^)]*(?:기준|짐작|[가-힣]{2,}의|'s|test|bar)[^)]*\)", ln):
                            unattributed.append(q.raw)
                        continue
                    extra.append(q.raw)
        extra = list(dict.fromkeys(extra))
        if answers is None:
            rep.add("PASS" if not extra else "REVIEW", "S10",
                    "입력 전문에 없는 기준·사실 숫자 (단위 포함 비교)",
                    "" if not extra else ", ".join(extra)
                    + ". 위원 '생각을 바꿀 조건'에 있는지 손으로 확인 (--answers 로 자동화)")
        else:
            rep.add("PASS" if not extra else "FAIL", "S10",
                    "입력 전문과 위원 '생각을 바꿀 조건'에 없는 숫자" + note, ", ".join(extra))
            if unattributed:
                rep.add("FAIL", "S10", "위원 기준에서 온 숫자에 출처 괄호",
                        "괄호 출처 없음: " + ", ".join(dict.fromkeys(unattributed)))
    else:
        rep.add("SKIP", "S10", "지어낸 숫자", "사례 파일 없음")


def resolve_slug(name):
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import resolve_members  # noqa: E402
        slug, _ = resolve_members.resolve(name)
        return slug
    except Exception:  # noqa: BLE001
        return None


def tilt_lists():
    """SKILL.md 전문가 선정 4번의 세 기울기 목록."""
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    out = {}
    for key, pat in (("move", "움직이는 쪽"), ("stop", "멈추는 쪽")):
        m = re.search(rf"^[ \t]*-[ \t]*{pat}[^:\n]*:[ \t]*(.+)$", text, re.M)
        out[key] = set(re.findall(r"`([a-z-]+)`", m.group(1))) if m else set()
    return out


AI_LEADERS = {"elon-musk", "sam-altman", "dario-amodei", "demis-hassabis"}
SKEPTICS = {"socrates", "nassim-taleb", "jeong-yakyong"}


def check_convene(rep, text, case):
    lang = detect_lang(text, case)
    rep.add("PASS" if EM_DASH not in text else "FAIL", "P3", "em dash 0개",
            f"{text.count(EM_DASH)}개" if EM_DASH in text else "")
    if lang != "ko":
        rep.add("SKIP", "P3", "소집 공개 형식", "SKILL.md에 영어 소집 공개 형식이 없다. 손으로 본다")
        names = []
    else:
        head = re.search(r"^[ \t]*소집 전문가[ \t]*\((\d+)인\)[ \t]*·[ \t]*([^·\n]+?)[ \t]*·[ \t]*예상 시간 약[ \t]*\d+(?:[ \t]*~[ \t]*\d+)?[ \t]*분",
                         text, re.M)
        rep.add("PASS" if head else "FAIL", "P3", "첫 줄 '소집 전문가 (N인) · 모드 · 예상 시간 약 n분'",
                "" if head else "없음")
        for label in ("가를 선택지:", "이 조합인 이유:"):
            ok = re.search(rf"^[ \t]*{label}[ \t]*\S", text, re.M) is not None
            rep.add("PASS" if ok else "FAIL", "P3", f"'{label}' 줄", "" if ok else "없음")
        rep.add("PASS" if "패널" not in text else "FAIL", "P3", "'패널'이라는 말을 쓰지 않음")
        names = []
        m = re.search(r"^[ \t]*이 조합인 이유:.*$", text, re.M)
        if m:
            for ln in text[m.end():].splitlines()[1:]:
                if not ln.strip():
                    if names:
                        break
                    continue
                if not re.match(r"^\s*-\s+\S", ln):
                    break
                mm = re.match(r"^\s*-\s*([^:：\n]+?)\s*[:：]\s*\S", ln)
                if mm:
                    names.append(mm.group(1).strip())
                else:
                    names.append(re.split(r"\s[-–]\s", ln.strip()[1:].strip())[0].strip())
        dash_join = re.search(r"^[ \t]*-[ \t]*[^:\n]+[ \t][-–][ \t]", text, re.M)
        rep.add("FAIL" if dash_join else "PASS", "P3", "이름과 이유를 콜론으로 잇기",
                f"'{dash_join.group(0).strip()}'" if dash_join else "")
        if head:
            n = int(head.group(1))
            rep.add("PASS" if n == len(names) else "FAIL", "P3", "N인과 위원 줄 수 일치",
                    f"N={n}, 위원 줄 {len(names)}개")
            if case and case["convene_count"] is not None:
                ok = n == case["convene_count"]
                rep.add("PASS" if ok else "FAIL", "P3", "소집 인원이 사례 기대와 같음",
                        f"{n}명, 기대 {case['convene_count']}명")
            if case and case["mode"] in ("전체", "빠른", "듀오", "트라이어드"):
                words = {"전체": ["전체", "full"], "빠른": ["빠른", "quick"],
                         "듀오": ["듀오", "duo"], "트라이어드": ["트라이어드", "triad"]}[case["mode"]]
                ok = any(w in head.group(2).lower() for w in words)
                rep.add("PASS" if ok else "FAIL", "P3", f"모드 표기 ({case['mode']})", head.group(2))

    # P2 선택지 확인 질문
    if case and case["confirm_options"] == "required":
        pat = r"빠진 안|이 선택지로 시작" if lang == "ko" else r"missing|other option|anything (?:else|we)"
        ok = re.search(pat, text, re.I) is not None
        rep.add("PASS" if ok else "FAIL", "P2", "코디네이터가 짠 선택지를 한 번 확인", "" if ok else "확인 질문 없음")

    # R-SEL 전문가 선정 (명단을 주지 않은 사례)
    if case and case["auto_select"]:
        slugs = [s for s in (resolve_slug(n) for n in names) if s]
        tl = tilt_lists()
        rep.add("PASS" if 0 < len(slugs) <= 7 else "FAIL", "E7-5", "소집 7명 이하 (R-SEL-5)", f"{len(slugs)}명")
        mv = [s for s in slugs if s in tl["move"]]
        sp = [s for s in slugs if s in tl["stop"]]
        rep.add("PASS" if mv and sp else "FAIL", "E7-5", "양쪽 앉히기 (R-SEL-4)",
                f"움직이는 쪽 {mv or '없음'}, 멈추는 쪽 {sp or '없음'}")
        ai = [s for s in slugs if s in AI_LEADERS]
        rep.add("PASS" if len(ai) <= 3 else "FAIL", "E7-5", "AI 영역 리더 3명 이하 (R-SEL-5)", f"{ai}")
        sk = [s for s in slugs if s in SKEPTICS]
        rep.add("PASS" if sk else "WARN", "E7-6", "다른 영역 회의론자 (R-SEL-3, 권장)", f"{sk or '없음'}")


def check_no_council(rep, text):
    for pat, name in ((r"소집 전문가", "소집 공개 없음"), (r"직답 표결|Direct-answer vote", "직답 표결 없음"),
                      (r"AI ROASTING (?:종합 의견|Verdict)", "종합 제목 없음")):
        m = re.search(pat, text)
        rep.add("FAIL" if m else "PASS", "E6", name, f"'{m.group(0)}' 있음" if m else "")


def check_ask_first(rep, text):
    check_no_council(rep, text)
    ok = re.search(r"\?|주세요|알려 주|말씀해", text) is not None
    rep.add("PASS" if ok else "FAIL", "E7-1", "사용자에게 되묻는 문장이 있음", "" if ok else "질문 없음")


# ---------------------------------------------------------------- 위원 원답 파일 (tests/CASES.md 6-2절)
#
#   ### 레이 달리오 · 라운드 1
#   (1) 한 줄 읽기: ...
#   (2) 직답: 옮기지 않는다
#   ...
# 칸은 번호가 아니라 이름으로 찾는다. 번호와 구분 기호(":" 또는 ".")는 있어도 없어도 된다.

ANS_HEAD = re.compile(r"^#{2,4}[ \t]*(.+?)[ \t]*[·|][ \t]*(라운드[ \t]*\d|재질문[^\n]*|관문 뒤[^\n]*"
                      r"|Round[ \t]*\d|Re-?ask[^\n]*)[ \t]*$", re.M | re.I)
CELL_NAMES = [
    ("orig", r"원래 질문으로는|In the original question|Original question"),
    ("changed", r"(?:라운드 1과 )?달라진 점|What changed"),
    ("answer", r"(?:최종 )?직답|(?:Final )?direct answer"),
    ("label", r"(?:최종 |판정 )?라벨|(?:Final )?(?:verdict )?label"),
    ("read", r"한 줄 읽기|One-line read(?:ing)?"),
    ("reason", r"(?:그 입장을 떠받치는 )?가장 강한 이유(?: 하나)?|(?:Single )?[Ss]trongest (?:single )?reason"),
    ("confidence", r"확신도|Confidence"),
    ("change", r"생각을 바꿀 (?:조건|단 하나)|(?:The one thing that )?(?:[Ww]hat )?would change (?:my|your) (?:mind|answer)"),
    ("first", r"(?:이번 주 )?첫 행동|First (?:move|action)"),
    ("premortem", r"실패한다면 그 이유|사전 부검|If it fails|Pre-?mortem"),
    ("open", r"그래도 못 푸는 질문(?: 하나)?|(?:Still )?(?:unresolved|open) question"),
]
# "(1) 칸: 값", "**(1) 칸.** 값", "**칸**: 값" 모두 받는다.
CELL_RE = re.compile(r"^\s*(?:\*\*)?\s*(?:\(\d+\)\s*)?(?:\*\*)?(" + "|".join(f"(?P<{k}>{p})" for k, p in CELL_NAMES)
                     + r")(?:\*\*)?\s*(?:[.:：]\s*(?:\*\*)?\s*|$)", re.I)


def parse_answers(text):
    """{사례 번호 또는 None: [블록]}. 블록 = {member, stage, cells: {칸: [값...]}, text}."""
    by_case = {}
    case_heads = [(m.start(), m.group(1)) for m in CASE_HEAD_RE.finditer(text)]
    heads = list(ANS_HEAD.finditer(text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.search(r"^#{1,2}[ \t]", text[m.end():end], re.M)
        if nxt:
            end = m.end() + nxt.start()
        body = text[m.end():end]
        # 칸 여럿이 한 줄에 붙어 오면("(3) Verdict label: X (4) Single strongest reason: ...") 칸마다 줄을 나눈다.
        body = re.sub(r"(?<=\S)[ \t]+(?=\*{0,2}\(\d\)[ \t]*\*{0,2}[^\s(])", "\n", body)
        cells, cur = {}, None
        for ln in body.splitlines():
            cm = CELL_RE.match(ln)
            if cm:
                cur = next(k for k, _ in CELL_NAMES if cm.group(k))
                cells.setdefault(cur, []).append(ln[cm.end():].strip())
            elif cur and ln.strip() and not ln.lstrip().startswith(("```", "#")):
                cells[cur][-1] = (cells[cur][-1] + " " + ln.strip()).strip()
        num = None
        for pos, n in case_heads:
            if pos < m.start():
                num = n
        stage = m.group(2).strip()
        by_case.setdefault(num, []).append({
            "member": m.group(1).strip().strip("*"), "stage": stage,
            "round3": bool(re.search(r"3", stage)), "cells": cells, "text": body,
        })
    return by_case


def answers_for(by_case, num):
    """그 사례의 원답 블록. 원답 파일이 '## 사례 N'으로 나뉘어 있는데 이 사례가 없으면 None
    (원답 없음, 숫자 검사는 REVIEW로 남는다). 나뉘어 있지 않으면 파일 전체."""
    if by_case is None:
        return None
    keyed = {int(k): v for k, v in by_case.items() if k}
    if not keyed:
        return [b for v in by_case.values() for b in v]
    if num is not None and int(num) in keyed:
        return keyed[int(num)] + by_case.get(None, [])
    return None


def _clean_value(v):
    v = re.sub(r"^\*\*|\*\*$", "", v.strip())
    return v.strip().rstrip(".").strip().strip('"“”').strip()


def labels_by_slug(labels):
    out = {}
    for lab, owners in labels.items():
        for s in owners:
            out.setdefault(s, []).append(lab)
    return out


ESCAPE_ANSWER = r"조건부|정보가 더 필요|더 알아보|conditional|need more (?:info|information|data)|depends"
CHANGE_FORM = {
    # "확인되면"이 정석이지만 "~로 나오면", "~이면"처럼 관찰 조건을 단 꼴도 받는다. 관찰 가능한지는 사람이 본다.
    "ko": r"(?:확인되면|드러나면|나오면|밝혀지면|[가-힣]면)[\s,(].*(?:바꾼다|바꿉니다|바꾸겠습니다|바꿀 것)",
    "en": r"\bif\b.*\b(?:confirm|verif|show|turn|prove)\w*\b.*\b(?:switch|change|move|flip)\w*\b"
          r"|\bconfirmed\b.*\b(?:switch|change|move|flip)\w*\b",
}
SAME = r"^(?:같음|같습니다|라운드 1과 같음|same|unchanged|no change)\b"


def check_answers(rep, blocks, case, labels):
    lang = case["language"] if case else "ko"
    options = (case["options"] + case["extra_options"]) if case else []
    lab_map = labels_by_slug(labels)
    if not blocks:
        rep.add("FAIL", "M", "원답 블록", "'### {위원 이름} · 라운드 1' 꼴 제목을 하나도 찾지 못함 (CASES.md 6-2절)")
        return
    for blk in blocks:
        who = f"{blk['member']} · {blk['stage']}"
        cells = {k: _clean_value(v[0]) for k, v in blk["cells"].items() if v}

        # M1 직답이 선택지 안
        if "answer" in cells:
            a = cells["answer"]
            if not options:
                rep.add("SKIP", "M1", f"{who} 직답", "사례 선택지 없음")
            elif re.search(ESCAPE_ANSWER, a, re.I) and not match_option(a, options):
                # "조건부 인수"처럼 선택지 이름에 "조건부"가 든 경우는 회피 답이 아니다.
                rep.add("FAIL", "M1", f"{who} 직답이 선택지 안", f"'{a}': 조건부·정보 부족으로 빠짐")
            else:
                o = match_option(a, options)
                rep.add("PASS" if o else "FAIL", "M1", f"{who} 직답이 선택지 안",
                        o if o else f"'{a}' 이 사례 선택지 하나로 읽히지 않음")
        elif re.search(r"라운드\s*[13]|Round\s*[13]", blk["stage"], re.I):
            rep.add("FAIL", "M1", f"{who} 직답", "직답 칸 없음")

        # M2 라벨이 그 위원의 세 라벨과 글자까지 같음
        if "label" in cells:
            slug = resolve_slug(blk["member"])
            own = lab_map.get(slug or "", [])
            # 영어 답의 "보완 (the direction is right...)"처럼 붙은 뜻풀이와 끝 마침표는 떼고 대조한다.
            lab = re.sub(r"\s*\([^)]*\)\s*$", "", cells["label"]).strip().rstrip(".")
            if not slug:
                rep.add("REVIEW", "M2", f"{who} 라벨", f"위원 이름 '{blk['member']}' 을 슬러그로 풀지 못함")
            elif lab in own:
                rep.add("PASS", "M2", f"{who} 라벨이 세 라벨 안", lab)
            elif lang != "ko" and not re.search(r"[가-힣]", lab):
                rep.add("REVIEW", "M2", f"{who} 라벨", f"'{lab}': 라벨 정본이 한국어라 손으로 대조 ({' / '.join(own)})")
            else:
                rep.add("FAIL", "M2", f"{who} 라벨이 세 라벨 안", f"'{lab}' 은 {' / '.join(own)} 가운데 없음")

        # M4 생각을 바꿀 조건의 꼴 (관찰 가능한 사실인지는 사람이 본다)
        if "change" in cells:
            c = cells["change"]
            if blk["round3"] and re.match(SAME, c, re.I):
                rep.add("PASS", "M4", f"{who} 생각을 바꿀 조건", "같음")
            elif not re.search(CHANGE_FORM[lang], c, re.I | re.S):
                want = "'X가 확인되면 직답을 Y로 바꾼다'" if lang == "ko" else "'If X is confirmed, I switch to Y'"
                rep.add("FAIL", "M4", f"{who} 생각을 바꿀 조건의 꼴", f"{want} 꼴이 아님: '{c[:40]}'")
            else:
                # '직답을 "A"가 아니라 "B"로 바꿉니다'면 B를 본다(바꾸는 말 바로 앞의 따옴표).
                ym = (re.search(r"[\"“']([^\"”']+)[\"”']\s*(?:으로|로)\s*바꿉?", c)
                      or re.search(r"직답을\s*[\"“']?(.+?)[\"”']?\s*(?:으로|로)\s*바꿉?", c))
                if ym and options and not option_ok(ym.group(1), options):
                    rep.add("FAIL", "M4", f"{who} 바꿀 직답이 선택지", f"'{ym.group(1)}' 이 선택지가 아님")
                else:
                    rep.add("PASS", "M4", f"{who} 생각을 바꿀 조건의 꼴", "관찰 가능한 사실인지는 손으로")
        elif re.search(r"라운드\s*[13]|Round\s*[13]", blk["stage"], re.I):
            rep.add("FAIL", "M4", f"{who} 생각을 바꿀 조건", "칸 없음")

        # M10 답변 언어 (영어 답은 라벨 칸을 빼고 잰다. 라벨 정본이 한국어다)
        txt = " ".join(v[0] for k, v in blk["cells"].items() if v and (lang == "ko" or k != "label"))
        h = len(re.findall(r"[가-힣]", txt))
        lat = len(re.findall(r"[A-Za-z]", txt))
        if h + lat:
            r = h / (h + lat)
            ok = r >= 0.6 if lang == "ko" else r < 0.05
            rep.add("PASS" if ok else "FAIL", "M10", f"{who} 답변 언어 ({lang})", f"한글 비율 {r:.0%}")

        # M12 확신도 값 (권장)
        if "confidence" in cells:
            c = cells["confidence"]
            m = re.match(r"^(높음|중간|낮음|high|medium|low)(?:입니다)?(?![가-힣A-Za-z])[\s.,:;()·-]*(.*)$", c, re.I)
            if not m:
                rep.add("WARN", "M12", f"{who} 확신도", f"'{c[:20]}': 높음·중간·낮음(high/medium/low)이 아님")
            elif len(m.group(2).strip()) < 4:
                rep.add("WARN", "M12", f"{who} 확신도", f"{m.group(1)}, 이유 한 줄 없음")
            else:
                rep.add("PASS", "M12", f"{who} 확신도", m.group(1))


# ---------------------------------------------------------------- 자체 시험 (--self-test)
#
# 선택지 맞추기와 숫자 비교의 오탐·미탐 사례. 기준을 고치면 이 표가 먼저 깨진다.

_O3 = ["한 번에 넣는다", "1년에 나눠 넣는다", "일부는 지금 넣고 나머지는 나눠 넣는다"]
_O1 = ["15명을 옮긴다", "3~5명 별도 팀만 뗀다", "옮기지 않는다", "기존 제품 안의 기능으로 넣는다"]
_O4 = ["지금 재조정을 요구한다", "지금은 요구하지 않는다", "두 사람 모두에게 기간 조건을 건다"]
_O5 = ["Stop taking clients under $5k next quarter", "Keep taking them"]
SELF_OPTION = [
    # 소집 공개의 짧은 이름 대 위원의 긴 문구, 괄호 풀이가 붙은 선택지 (2026-10-31 실측에서 나온 꼴)
    ("신제품 없이 기존 제품 안에 AI 기능으로 넣기",
     ["15명 이동", "5~7명 소규모 팀", "기존 제품 안 기능", "지금은 하지 않음"], "기존 제품 안 기능"),
    ("양쪽 베스팅 새로 걸기",
     ["70:30 제안", "50:50 유지", "양쪽 베스팅 새로 걸기 (지금 지분은 두되, 기간 조건을 거는 안)"],
     "양쪽 베스팅 새로 걸기 (지금 지분은 두되, 기간 조건을 거는 안)"),
    ("지금 넣는다", _O3, None),            # 옛 기준이 "한 번에 넣는다"로 받아 준 오탐
    ("넣는다", _O3, None),                 # 모든 선택지에 있는 동사 하나
    ("나눠 넣는다", _O3, None),            # 중간안도 품고 있어 어느 쪽인지 모름
    ("나눠 넣는다", _O3[:2], _O3[1]),
    ("12개월에 나눠 넣는다", _O3, _O3[1]),  # 1년 = 12개월
    ("6개월에 나눠 넣는다", _O3, None),
    ("한 번에 넣는다", _O3, _O3[0]),
    ("15명", _O1, _O1[0]),
    ("10명을 옮긴다", _O1, None),
    ("팀을 옮긴다", _O1, None),            # 두 선택지의 낱말을 섞음
    ("3~5명 별도 팀", _O1, _O1[1]),
    ("옮기지 않는다", _O1, _O1[2]),
    ("기능으로 넣는다", _O1, _O1[3]),
    ("지금 요구한다", _O4, _O4[0]),
    ("요구하지 않는다", _O4, _O4[1]),
    ("기간 조건", _O4, _O4[2]),
    ("Stop", _O5, _O5[0]),
    ("Keep", _O5, _O5[1]),
    ("Stop taking them", _O5, None),
]
SELF_NUMBER = [  # (입력, 종합의 숫자, 같은 숫자로 보는가)
    ("지분을 70:30으로", "30분", False),
    ("지분을 70:30으로", "30%", True),
    ("1년에 걸쳐", "12개월", True),
    ("반년 안에", "6개월", True),
    ("1년에 걸쳐", "2분기 동안", False),
    ("3~5명 별도 팀", "4명", True),
    ("퇴직금 3억 원", "300,000,000원", True),
    ("20퍼센트 넘게", "20%", True),
    ("under $5k", "$4k", False),
    ("주 2일만", "2주", False),
]
SELF_EXCLUDED = [
    "by Nov 14, 2026", "in 2026",
    "check before Nov 14", "3~4일차: 앱에서 찾습니다","1~3일차", "2027년 3월", "5명 중 4명", "4 대 1", "라운드 1", "(6)", "3분기", "(5/5 응답)"]
SELF_CLAUSE = [
    ("기한까지 아래 어느 것도 확인되지 않으면 → **기존 제품 안 기능**",
     ["15명 이동", "5~7명 팀", "기존 제품 안 기능", "지금은 하지 않음"], ["기존 제품 안 기능"]),
    ("AI가 없어서 놓친 비율이 3분의 1 이상이면 → **5~7명 팀** (콜린스 기준)",
     ["15명 이동", "5~7명 팀", "기존 제품 안 기능", "지금은 하지 않음"], ["5~7명 팀"]),  # (판단 규칙 불릿, 선택지 묶음, 결과절이 가리키는 선택지)
    ("분기 말까지 확인하지 못하면 팀을 접고 옮기지 않습니다.", _O1[:3], [_O1[2]]),
    ("견적서가 나오면 15명을 옮깁니다(머스크의 기준).", _O1[:3], [_O1[0]]),
    ("견적서가 나오면 15명을 옮기지 않습니다.", _O1[:3], [_O1[2]]),
    ("틀린 처리가 기준 이하면 3~5명 팀을 한 분기 더 둡니다.", _O1[:3], [_O1[1]]),
    ("확인되면 팀을 띄우지 않습니다.", _O1[:3], []),
    ("If you cannot measure hours by the end of the quarter, keep taking them.", _O5, [_O5[1]]),
]


def self_test():
    bad = []
    for v, opts, want in SELF_OPTION:
        got = match_option(v, opts)
        if got != want:
            bad.append(f"선택지 '{v}': {got!r}, 기대 {want!r}")
    for src, s, want in SELF_NUMBER:
        qs = quantities(s)
        got = bool(qs) and all(_q_match(q, quantities(src, exclude=False)) for q in qs)
        if got != want:
            bad.append(f"숫자 '{s}' (입력 '{src}'): {got}, 기대 {want}")
    for s in SELF_EXCLUDED:
        if quantities(s):
            bad.append(f"셈에서 빼야 할 '{s}' 를 숫자로 셈: {quantities(s)}")
    for b, opts, want in SELF_CLAUSE:
        lang = "en" if re.search(r"[A-Za-z]{3}", b) and not re.search(r"[가-힣]", b) else "ko"
        tbl = [(o, [o]) for o in opts]
        got = [o for cl in result_clauses(b, lang) for o in mentions(cl, tbl)]
        if got != want:
            bad.append(f"결과절 '{b[:24]}...': {got}, 기대 {want}")
    n = len(SELF_OPTION) + len(SELF_NUMBER) + len(SELF_EXCLUDED) + len(SELF_CLAUSE)
    if bad:
        print(f"FAIL  자체 시험 {n}개 중 {len(bad)}개 실패")
        for x in bad:
            print("  -", x)
        return 1
    print(f"PASS  자체 시험 {n}개 (선택지 맞추기 {len(SELF_OPTION)}, 숫자 {len(SELF_NUMBER) + len(SELF_EXCLUDED)}, "
          f"결과절 {len(SELF_CLAUSE)})")
    return 0


# ---------------------------------------------------------------- 실행

def run_one(title, text, case, stage, answers, labels, meta):
    rep = Report(title)
    if meta:
        bits = [f"{meta['duration_s']}초"]
        if meta.get("input_tokens") is not None:
            bits.append(f"토큰 입력 {meta['input_tokens']} / 출력 {meta['output_tokens']}"
                        + (f" / 캐시 읽기 {meta['cache_read']}" if meta.get("cache_read") else ""))
        if meta.get("cost_usd") is not None:
            bits.append(f"비용 ${meta['cost_usd']:.4f}")
        rep.add("SKIP", "T", "시간·토큰 (메인 세션 기준, 기록 양식에 옮겨 적음)", ", ".join(bits))
    if stage == "synthesis":
        check_synthesis(rep, text, case, answers, labels)
    elif stage == "convene":
        check_convene(rep, text, case)
    elif stage == "no-council":
        check_no_council(rep, text)
    elif stage == "ask-first":
        check_ask_first(rep, text)
    elif stage == "manual":
        rep.add("SKIP", "-", "이 사례는 수동 채점", "종합을 채점하려면 --stage synthesis")
    else:
        raise SystemExit(f"알 수 없는 단계: {stage}")
    if case and stage == case["check"]:
        check_common(rep, text, case)
    rep.show()
    return rep


def run_answers(title, blocks, case, labels):
    rep = Report(title)
    check_answers(rep, blocks, case, labels)
    rep.show()
    return rep


def main():
    ap = argparse.ArgumentParser(description="자문단 실행 결과의 기계 채점")
    ap.add_argument("file", nargs="?", help="채점할 결과 파일 (.md, 또는 claude -p --output-format json 결과)")
    ap.add_argument("--case", help="사례 파일 (tests/cases/NN.md)")
    ap.add_argument("--cases-dir", default=str(ROOT / "tests" / "cases"),
                    help="--split 에서 '사례 N' 제목으로 사례 파일을 찾을 폴더")
    ap.add_argument("--split", action="store_true", help="종합 의견 블록마다 따로 채점")
    ap.add_argument("--stage", choices=["synthesis", "convene", "no-council", "ask-first", "manual"])
    ap.add_argument("--answers", help="위원 원답 파일(CASES.md 6-2절 형식). 주면 숫자 검사를 확정하고 "
                                      "M1, M2, M4, M10, M12 를 자동 판정한다. 결과 파일 없이 이것만 줘도 된다")
    ap.add_argument("--options", help="실행에서 확정된 선택지('A / B / C'). 코디네이터가 0단계에서 "
                                      "선택지를 고쳤으면 사례 파일 대신 이것으로 대조한다")
    ap.add_argument("--print-prompt", metavar="CASE", help="사례 파일의 실행 입력(prefix + 입력 전문)을 찍고 끝냄")
    ap.add_argument("--self-test", action="store_true", help="선택지 맞추기와 숫자 비교의 자체 시험만 돌림")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.print_prompt:
        c = parse_case(args.print_prompt)
        print((c["prefix"] + " " + c["input"]).strip())
        return 0
    if not args.file and not args.answers:
        ap.print_usage(sys.stderr)
        return 2

    case = parse_case(args.case) if args.case else None
    if case is not None and args.options:
        case["options"] = [o.strip() for o in args.options.split(" / ") if o.strip()]
        case["extra_options"] = []
    by_case = parse_answers(Path(args.answers).read_text(encoding="utf-8")) if args.answers else None
    labels = load_labels()
    reports = []

    def case_for(num):
        if case is not None or not num:
            return case, ""
        p = find_case_file(args.cases_dir, num)
        return (parse_case(p), f", {Path(p).name}") if p else (None, "")

    if args.file:
        text, meta = load_text(args.file)
        if args.split:
            blocks = split_blocks(text)
            if not blocks:
                print("종합 의견 블록을 찾지 못했습니다 ('## AI ROASTING 종합 의견' 또는 '## AI ROASTING Verdict').",
                      file=sys.stderr)
                return 2
            for i, (num, block) in enumerate(blocks, 1):
                c, src = case_for(num)
                title = f"블록 {i} (사례 {num or '?'}{src})"
                reports.append(run_one(title, block, c, args.stage or "synthesis",
                                       answers_for(by_case, num), labels, meta))
        else:
            stage = args.stage or (case["check"] if case else "synthesis")
            if stage == "synthesis":
                blocks = split_blocks(text)
                if len(blocks) > 1:
                    print(f"종합 의견 블록이 {len(blocks)}개입니다. --split 을 쓰세요.", file=sys.stderr)
                    return 2
                if blocks:
                    text = blocks[0][1]
            title = Path(args.file).name + (f" (사례 {case['id']}, {stage})" if case else f" ({stage})")
            reports.append(run_one(title, text, case, stage,
                                   answers_for(by_case, case["id"] if case else None), labels, meta))

    if by_case is not None:
        keys = [k for k in by_case if k] if (args.split or case is None) and any(by_case) else [None]
        for k in keys:
            c, src = case_for(k) if k else (case, "")
            blocks = answers_for(by_case, k) if k else [b for v in by_case.values() for b in v]
            title = f"위원 원답 {Path(args.answers).name}" + (f" (사례 {k}{src})" if k else
                                                           (f" (사례 {case['id']})" if case else ""))
            reports.append(run_answers(title, blocks, c, labels))

    failed = [r.title for r in reports if r.failed()]
    print(f"전체: {len(reports)}개 중 FAIL 있는 것 {len(failed)}개" + (f" ({', '.join(failed)})" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
