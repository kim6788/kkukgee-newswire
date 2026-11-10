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

# 종목 해시태그 사전 — 제목·요약에 이름이 나오면 태그로 붙임 (LLM 결과와 합쳐 최대 4개)
# 왼쪽: 기사에 나오는 표기, 오른쪽: 붙일 태그. 필요하면 여기에 추가
STOCKS = {
    # 메모리·반도체
    "삼성전자": "#삼성전자", "SK하이닉스": "#SK하이닉스", "하이닉스": "#SK하이닉스",
    "한미반도체": "#한미반도체", "리노공업": "#리노공업", "ISC": "#ISC", "원익IPS": "#원익IPS",
    "주성엔지니어링": "#주성엔지니어링", "피에스케이": "#피에스케이", "이오테크닉스": "#이오테크닉스",
    "솔브레인": "#솔브레인", "동진쎄미켐": "#동진쎄미켐", "한솔케미칼": "#한솔케미칼",
    "하나마이크론": "#하나마이크론", "SKC": "#SKC", "티씨케이": "#티씨케이", "HPSP": "#HPSP",
    "케이씨텍": "#케이씨텍", "유진테크": "#유진테크", "에스티아이": "#에스티아이", "DB하이텍": "#DB하이텍",
    # 기판·부품
    "이수페타시스": "#이수페타시스", "대덕전자": "#대덕전자", "삼성전기": "#삼성전기", "LG이노텍": "#LG이노텍",
    "심텍": "#심텍", "코리아써키트": "#코리아써키트", "두산테스나": "#두산테스나", "티엘비": "#티엘비",
    # 전력·에너지
    "LS일렉트릭": "#LS일렉트릭", "HD현대일렉트릭": "#HD현대일렉트릭", "효성중공업": "#효성중공업",
    "일진전기": "#일진전기", "대한전선": "#대한전선", "LS전선": "#LS", "두산에너빌리티": "#두산에너빌리티",
    "한국전력": "#한국전력", "한전": "#한국전력", "가온전선": "#가온전선", "제룡전기": "#제룡전기",
    "비에이치아이": "#비에이치아이", "씨에스윈드": "#씨에스윈드", "SK이터닉스": "#SK이터닉스",
    "한전기술": "#한전기술", "현대건설": "#현대건설", "삼성물산": "#삼성물산", "삼성E&A": "#삼성E&A",
    # AI·플랫폼
    "네이버": "#NAVER", "NAVER": "#NAVER", "카카오": "#카카오", "삼성SDS": "#삼성SDS", "LG CNS": "#LGCNS",
    # 해외
    "엔비디아": "$NVDA", "Nvidia": "$NVDA", "TSMC": "$TSM", "마이크론": "$MU", "브로드컴": "$AVGO",
    "AMD": "$AMD", "인텔": "$INTC", "ASML": "$ASML", "마이크로소프트": "$MSFT", "MS ": "$MSFT",
    "구글": "$GOOGL", "알파벳": "$GOOGL", "아마존": "$AMZN", "메타플랫폼": "$META", "애플": "$AAPL",
    "오라클": "$ORCL", "테슬라": "$TSLA", "코어위브": "$CRWV", "버티브": "$VRT", "GE버노바": "$GEV",
    "오픈AI": "", "OpenAI": "",   # 비상장 — 태그 안 붙임
}
STOCKS = {k: v for k, v in STOCKS.items() if v}

# ─────────────────────────────────────────────
# 4) LLM 심사 (Claude API) — 제목 + RSS 요약문만 보내고 본문은 안 긁음
# ─────────────────────────────────────────────
LLM_MODEL = "claude-haiku-5-5"
LLM_MAX_BATCH = 40          # 한 번에 심사할 최대 기사 수
LLM_TIMEOUT = 60

# ─────────────────────────────────────────────
# 5) 발송 규칙
# ─────────────────────────────────────────────
SEND_NOW_MIN = 4             # 4~5점만 바로 발송. 3점은 묶음으로
SILENT_BELOW = 5             # 이 점수 미만은 무음 발송(알림 소리 X). 5점 [속보]만 소리 남
DIGEST_MIN = 3               # 3점 + 상한 넘친 것 → 묶음
DIGEST_HOURS_KST = [8, 12, 18]
DIGEST_MAX_ITEMS = 10
QUIET_HOURS_KST = range(0, 7)  # 00~07시엔 5점 [속보]만 즉시, 나머지는 08시 묶음으로
MAX_AGE_HOURS = 1            # 1시간 넘은 기사는 버림 (실행이 밀렸을 때 몰아서 쏟아지는 것 방지)
SIMILAR_TITLE = 0.5          # 제목 유사도 이 이상이면 같은 기사로 보고 중복 제거
MAX_SEND_PER_RUN = 3         # 한 바퀴(1분)에 즉시 발송 최대 3건
MAX_SEND_PER_HOUR = 6        # 1시간에 즉시 발송 최대 6건 — 넘치면 묶음으로
POLL_SECONDS = 60            # LOOP_MINUTES>0 일 때 한 실행 안에서 재수집 간격

# ─────────────────────────────────────────────
# 6) 피드 헬스 체크
# ─────────────────────────────────────────────
FEED_FAIL_ALERT = 6          # 연속 실패 n회면 관리자 채팅에 경고 (하루 1번)
HTTP_TIMEOUT = 12
USER_AGENT = "Mozilla/5.0 (compatible; kkukgee-newswire/1.0; +https://t.me/kkukgee)"
