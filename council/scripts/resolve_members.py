#!/usr/bin/env python3
"""
Resolve --members input (Korean names or slugs) to canonical agent slugs.

Deterministic so the coordinator never has to guess the spelling. Unknown
inputs get a closest-match suggestion instead of a silent wrong dispatch.

    python3 scripts/resolve_members.py "이순신,정약용,마키아벨리"
    python3 scripts/resolve_members.py yi-sunsin,warren-buffett

Prints one slug per line. Exit 0 if all resolved, 1 if any were not.
"""
import difflib
import sys

# Korean name -> slug. Slugs double as their own keys.
NAME_TO_SLUG = {
    "소크라테스": "socrates",
    "아리스토텔레스": "aristotle",
    "마르쿠스 아우렐리우스": "marcus-aurelius",
    "아우렐리우스": "marcus-aurelius",
    "노자": "lao-tzu",
    "알프레드 아들러": "alfred-adler",
    "아들러": "alfred-adler",
    "손자": "sun-tzu",
    "클라우제비츠": "carl-clausewitz",
    "마키아벨리": "niccolo-machiavelli",
    "이순신": "yi-sunsin",
    "정약용": "jeong-yakyong",
    "피터 드러커": "peter-drucker",
    "드러커": "peter-drucker",
    "대니얼 카너먼": "daniel-kahneman",
    "카너먼": "daniel-kahneman",
    "나심 탈레브": "nassim-taleb",
    "탈레브": "nassim-taleb",
    "클레이튼 크리스텐슨": "clayton-christensen",
    "크리스텐슨": "clayton-christensen",
    "짐 콜린스": "jim-collins",
    "콜린스": "jim-collins",
    "일론 머스크": "elon-musk",
    "머스크": "elon-musk",
    "샘 알트만": "sam-altman",
    "알트만": "sam-altman",
    "다리오 아모데이": "dario-amodei",
    "아모데이": "dario-amodei",
    "데미스 하사비스": "demis-hassabis",
    "하사비스": "demis-hassabis",
    "젠슨 황": "jensen-huang",
    "워런 버핏": "warren-buffett",
    "버핏": "warren-buffett",
    "찰리 멍거": "charlie-munger",
    "멍거": "charlie-munger",
    "캐시 우드": "cathie-wood",
    "레이 달리오": "ray-dalio",
    "달리오": "ray-dalio",
    "하워드 막스": "howard-marks",
    "막스": "howard-marks",
}
SLUGS = sorted(set(NAME_TO_SLUG.values()))


def resolve(token):
    t = token.strip()
    if t in NAME_TO_SLUG:
        return NAME_TO_SLUG[t], None
    if t in SLUGS:
        return t, None
    pool = list(NAME_TO_SLUG.keys()) + SLUGS
    near = difflib.get_close_matches(t, pool, n=1, cutoff=0.6)
    suggestion = NAME_TO_SLUG.get(near[0], near[0]) if near else None
    return None, suggestion


def main():
    if len(sys.argv) < 2:
        print("usage: resolve_members.py \"name1,name2,...\"", file=sys.stderr)
        sys.exit(2)
    tokens = [x for x in sys.argv[1].replace("，", ",").split(",") if x.strip()]
    ok = True
    for tok in tokens:
        slug, suggestion = resolve(tok)
        if slug:
            print(slug)
        else:
            ok = False
            hint = f" (did you mean {suggestion}?)" if suggestion else ""
            print(f"UNRESOLVED: {tok.strip()}{hint}", file=sys.stderr)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
