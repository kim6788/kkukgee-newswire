# -*- coding: utf-8 -*-
"""꾹쥐 뉴스와이어 설정 — 피드·키워드·발송 규칙은 전부 여기서만 고치면 됨."""

# ─────────────────────────────────────────────
# 1) 언론사 RSS
#   ok=True  : 2026-08-20 기준 실제 파싱 검증된 피드
#   ok=False : 경로 패턴으로 넣은 미검증 피드 → 첫 실행 후 관리자 채팅으로 생존 여부 보고됨
# ─────────────────────────────────────────────
FEEDS = [
    # 경제지
    {"name": "한국경제",   "url": "https://www.hankyung.com/feed/all-news",                 "ok": True},
    {"name": "이투데이",   "url": "https://rss.etoday.co.kr/eto/etoday_news_all.xml",       "ok": True},
    {"name": "매일경제",   "url": "https://www.mk.co.kr/rss/30000001/",                     "ok": True},
    {"name": "매일경제",   "url": "https://www.mk.co.kr/rss/40300001/",                     "ok": False},  # 경제 섹션
    {"name": "머니투데이", "url": "http://rss.mt.co.kr/mt_news.xml",                        "ok": True},
    {"name": "서울경제",   "url": "https://www.sedaily.com/rss/newsall",                    "ok": True},
    {"name": "이데일리",   "url": "http://rss.edaily.co.kr/edaily_news.xml",                "ok": True},
    {"name": "아시아경제", "url": "https://view.asiae.co.kr/rss/all.htm",                   "ok": True},
    {"name": "파이낸셜뉴스","url": "https://www.fnnews.com/rss/r20/fn_realnews_all.xml",    "ok": True},
    {"name": "헤럴드경제", "url": "https://biz.heraldcorp.com/rss/google/newsAll",          "ok": True},
    {"name": "조선비즈",   "url": "https://biz.chosun.com/arc/outboundfeeds/rss/?outputType=xml", "ok": True},
    # 통신사
    {"name": "연합뉴스",   "url": "https://www.yna.co.kr/rss/news.xml",                     "ok": True},
    {"name": "뉴시스",     "url": "https://www.newsis.com/RSS/sokbo.xml",                   "ok": True},
    # IT·전자·전문
    {"name": "디일렉",     "url": "https://www.thelec.kr/rss/allArticle.xml",               "ok": False},
    {"name": "전자신문",   "url": "https://rss.etnews.com/Section901.xml",                  "ok": True},
    {"name": "지디넷코리아","url": "https://feeds.feedburner.com/zdkorea",                  "ok": True},
    {"name": "아이뉴스24", "url": "https://www.inews24.com/rss/news_all.xml",               "ok": True},
    {"name": "블로터",     "url": "https://cdn.bloter.net/rss/gns_allArticle.xml",          "ok": True},
    {"name": "테크M",      "url": "https://www.techm.kr/rss/allArticle.xml",                "ok": True},
    # 에너지·전력
    {"name": "전기신문",   "url": "https://www.electimes.com/rss/allArticle.xml",           "ok": False},
    {"name": "이투뉴스",   "url": "https://www.e2news.com/rss/allArticle.xml",              "ok": True},
    {"name": "투데이에너지","url": "https://www.todayenergy.kr/rss/allArticle.xml",          "ok": True},
]

# ─────────────────────────────────────────────
# 2) 구글뉴스 검색 RSS — RSS가 없거나 불안정한 곳 + 정책 보도 보강
#    (정책브리핑 korea.kr RSS는 2026-07-01 서비스 중단됨)
# ─────────────────────────────────────────────
GNEWS_QUERIES = [
    "site:thelec.kr",                      # 디일렉 직피드가 죽었을 때 대비
    "site:ddaily.co.kr",                   # 디지털데일리 (RSS 없음)
    "site:dt.co.kr",                       # 디지털타임스 (RSS 없음)
    "site:newspim.com 반도체 OR 데이터센터 OR 전력", # 뉴스핌 (RSS 없음)
    "과기정통부 AI",
    "산업통상부 반도체 OR 전력망 OR 데이터센터",
    "AI 데이터센터 정부 지원",
    "전력망 특별법 OR 분산에너지 특별법",
]
GNEWS_WINDOW = "1h"   # 최근 1시간 기사만

# ─────────────────────────────────────────────
# 3) 1차 키워드 필터 (제목 히트 2점, 요약 히트 1점, 테마별 가중치 곱)
#    영문 키워드는 단어 경계로 매칭 (AI가 MAIL에 걸리지 않게)
# ─────────────────────────────────────────────
THEMES = {
    "AIDC·전력": {"w": 1.5, "kw": [
        "AI데이터센터", "AI 데이터센터", "데이터센터", "AIDC", "하이퍼스케일",
        "전력망", "송전", "배전", "변압기", "초고압", "전력기기", "ESS", "SMR", "원전",
        "가스터빈", "연료전지", "액침", "냉각", "한전", "전력 수요", "전력수요", "PPA",
    ]},
    "반도체·기판": {"w": 1.5, "kw": [
        "반도체", "HBM", "D램", "DRAM", "낸드", "NAND", "파운드리", "패키징", "후공정",
        "기판", "PCB", "MLCC", "CCL", "유리기판", "CoWoS", "하이브리드 본딩", "하이브리드본딩",
        "EUV", "소부장", "웨이퍼", "TSMC", "마이크론", "엔비디아", "Nvidia", "CPO", "광통신",
    ]},
    "AI": {"w": 1.0, "kw": [
        "AI", "인공지능", "LLM", "GPU", "오픈AI", "OpenAI", "앤트로픽", "Anthropic",
        "피지컬 AI", "피지컬AI", "휴머노이드", "로봇",
    ]},
    "정책": {"w": 1.0, "kw": [
        "과기정통부", "산업통상부", "산업부", "기재부", "재정경제부", "금융위", "금감원",
        "대통령실", "국무회의", "특별법", "법안", "개정안", "예산", "보조금", "세액공제",
        "규제", "수출통제", "관세", "행정명령", "추경", "지원책", "로드맵",
    ]},
    "시장속보": {"w": 1.0, "kw": [
        "단독", "속보", "수주", "공급계약", "단일판매", "인수", "M&A", "유상증자",
        "어닝", "서프라이즈", "잠정실적", "상한가", "신고가", "최대 실적",
    ]},
}
PREFILTER_MIN = 3.0   # 이 점수 이상만 LLM 심사로 넘어감

# 제목에 하나라도 있으면 바로 버림
EXCLUDE = [
    "[포토]", "[사진]", "포토", "부고", "[인사]", "인사]", "운세", "날씨", "게시판",
    "신간", "경조사", "연예", "스포츠", "프로야구", "골프", "[오늘의", "이벤트",
    "[광고]", "AD]", "부음", "결혼",
]

# ─────────────────────────────────────────────
# 4) LLM 심사 (Claude API) — 제목 + RSS 요약문만 보내고 본문은 안 긁음
# ─────────────────────────────────────────────
LLM_MODEL = "claude-haiku-5-5"
LLM_MAX_BATCH = 40          # 한 번에 심사할 최대 기사 수
LLM_TIMEOUT = 60

# ─────────────────────────────────────────────
# 5) 발송 규칙
# ─────────────────────────────────────────────
SEND_NOW_MIN = 4             # 4~5점: 즉시 발송
DIGEST_MIN = 3               # 3점: 묶음으로 모았다가 정해진 시각에 발송
DIGEST_HOURS_KST = [7, 12, 18]
DIGEST_MAX_ITEMS = 15
QUIET_HOURS_KST = range(0, 6)  # 이 시간엔 5점(속보급)만 즉시, 4점은 07시 묶음으로
MAX_AGE_HOURS = 3            # 이보다 오래된 기사는 무시 (첫 실행·지연 대비)
SIMILAR_TITLE = 0.55         # 제목 유사도 이 이상이면 같은 기사로 보고 중복 제거
MAX_SEND_PER_RUN = 12        # 한 번 돌 때 즉시 발송 상한 (폭주 방지)
POLL_SECONDS = 60            # LOOP_MINUTES>0 일 때 한 실행 안에서 재수집 간격

# ─────────────────────────────────────────────
# 6) 피드 헬스 체크
# ─────────────────────────────────────────────
FEED_FAIL_ALERT = 6          # 연속 실패 n회면 관리자 채팅에 경고 (하루 1번)
HTTP_TIMEOUT = 12
USER_AGENT = "Mozilla/5.0 (compatible; kkukgee-newswire/1.0; +https://t.me/kkukgee)"
