# -*- coding: utf-8 -*-
"""
꾹쥐 뉴스와이어 — 국내 언론 RSS 실시간 수집 → 키워드 1차 → Claude 2차 심사 → 텔레그램 발송
표준 라이브러리만 사용 (pip 설치 불필요). GitHub Actions 5분 cron 기준으로 설계.

환경변수
  TELEGRAM_BOT_TOKEN  (필수)  @BotFather 토큰
  TELEGRAM_CHAT_ID    (필수)  @채널아이디 또는 -100xxxxxxxxxx
  ANTHROPIC_API_KEY   (선택)  없으면 키워드 점수만으로 동작 (요약·종목 태그 없음)
  ADMIN_CHAT_ID       (선택)  피드 고장 경고·실행 로그를 받을 개인 채팅
  LOOP_MINUTES        (선택)  0이면 1회 수집 후 종료. 4면 한 실행 안에서 4분간 1분 간격 재수집
  DRY_RUN=1           (선택)  텔레그램 대신 콘솔 출력

상시 실행:  python newswire.py --forever   (Windows는 pythonw, Termux는 python)
  - 같은 폴더의 secrets.env 에서 키를 읽음 (KEY=값 한 줄씩)
  - 로그는 newswire.log, 중복 실행은 자동 차단
"""
import concurrent.futures as cf
import datetime as dt
import email.utils
import gzip
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import config as C

KST = dt.timezone(dt.timedelta(hours=9))
BASE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE, "state", "state.json")
SECRETS_PATH = os.path.join(BASE, "secrets.env")
LOG_PATH = os.path.join(BASE, "newswire.log")
DRY = os.environ.get("DRY_RUN") == "1"


def load_secrets():
    """secrets.env (KEY=값) → 환경변수. 이미 환경변수에 있으면 그대로 둠. 매 바퀴 다시 읽어서
    파일만 고쳐도 재시작 없이 반영됨."""
    try:
        with open(SECRETS_PATH, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if v and (k not in os.environ or os.environ.get("_FROM_SECRETS_" + k)):
                    os.environ[k] = v
                    os.environ["_FROM_SECRETS_" + k] = "1"
    except FileNotFoundError:
        pass


def log(*a):
    print(dt.datetime.now(KST).strftime("[%H:%M:%S]"), *a, flush=True)


def now_kst():
    return dt.datetime.now(KST)


# ═════════════════════════ 상태 ═════════════════════════
def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("seen", {})            # key -> epoch
    s.setdefault("titles", [])          # [[정규화제목, epoch]] 최근 발송/처리 제목
    s.setdefault("digest", [])          # 묶음 대기 기사
    s.setdefault("last_digest", "")     # "YYYY-MM-DD-HH"
    s.setdefault("feeds", {})           # 피드별 etag / 실패 횟수
    s.setdefault("alert_day", "")
    s.setdefault("warm", False)         # 첫 실행 워밍업 완료 여부
    s.setdefault("sent_ts", [])         # 최근 즉시 발송 시각 (시간당 상한용)
    return s


def save_state(s):
    cutoff = time.time() - 3 * 86400
    s["seen"] = {k: v for k, v in s["seen"].items() if v > cutoff}
    s["titles"] = [t for t in s["titles"] if t[1] > time.time() - 86400][-800:]
    s["digest"] = s["digest"][-80:]
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


# ═════════════════════════ 수집 ═════════════════════════
def http_get(url, etag=None, lm=None, timeout=None):
    req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT,
                                               "Accept": "application/rss+xml, application/xml, text/xml, */*",
                                               "Accept-Encoding": "gzip"})   # 데이터 사용량 ~1/5
    if etag:
        req.add_header("If-None-Match", etag)
    if lm:
        req.add_header("If-Modified-Since", lm)
    try:
        with urllib.request.urlopen(req, timeout=timeout or C.HTTP_TIMEOUT) as r:
            body = r.read()
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            return r.status, body, r.headers.get("ETag"), r.headers.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, b"", etag, lm
        raise


TAG_RE = re.compile(r"<[^>]+>")


def clean(text, n=None):
    t = html.unescape(TAG_RE.sub(" ", text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n] if n else t


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        d = None
    if d is None:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    d = dt.datetime.strptime(s, fmt)
                    break
                except ValueError:
                    pass
    if d is None:
        return None
    if d.tzinfo is None:            # 국내 피드는 대부분 KST로 시간대 표기 없이 옴
        d = d.replace(tzinfo=KST)
    return d


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(raw, source):
    """RSS 2.0 / Atom / RDF 모두 처리. 각 기사 dict 리스트 반환."""
    raw = raw.lstrip(b"\xef\xbb\xbf \r\n\t")
    m = re.search(rb'encoding=["\']([A-Za-z0-9_\-]+)', raw[:200])
    enc = m.group(1).decode().lower() if m else "utf-8"
    if enc in ("euc-kr", "ks_c_5601-1987", "cp949"):   # 일부 국내 피드
        raw = raw.decode("cp949", "replace").encode("utf-8")
        raw = re.sub(rb'encoding=["\'][^"\']+["\']', b'encoding="utf-8"', raw, count=1)
    root = ET.fromstring(raw)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        f = {"title": "", "link": "", "date": None, "desc": "", "src": source}
        for ch in el:
            t = _local(ch.tag)
            if t == "title":
                f["title"] = clean(ch.text)
            elif t == "link":
                f["link"] = (ch.get("href") or ch.text or "").strip() or f["link"]
            elif t in ("pubdate", "published", "updated", "date") and not f["date"]:
                f["date"] = parse_date(ch.text)
            elif t in ("description", "summary", "content") and not f["desc"]:
                f["desc"] = clean(ch.text, 300)
            elif t == "source" and ch.text:       # 구글뉴스: 원 매체명
                f["src"] = clean(ch.text)
        if f["title"] and f["link"]:
            if source.startswith("G:") and f["src"] != source:
                # 구글뉴스 제목 끝의 " - 매체명" 제거
                f["title"] = re.sub(r"\s+-\s+[^-]{1,30}$", "", f["title"])
            out.append(f)
    return out


def gnews_url(q):
    q = f"{q} when:{C.GNEWS_WINDOW}"
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})


def all_sources():
    srcs = [(f["name"], f["url"]) for f in C.FEEDS]
    srcs += [(f"G:{q}", gnews_url(q)) for q in C.GNEWS_QUERIES]
    return srcs


def fetch_all(state):
    items, ok, fail = [], 0, []
    srcs = all_sources()

    def job(name_url):
        name, url = name_url
        st = state["feeds"].get(url, {})
        code, body, etag, lm = http_get(url, st.get("etag"), st.get("lm"))
        return name, url, code, body, etag, lm

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(job, s): s for s in srcs}
        for fu in cf.as_completed(futs):
            name, url = futs[fu]
            st = state["feeds"].setdefault(url, {"fail": 0})
            try:
                name, url, code, body, etag, lm = fu.result()
                st.update(etag=etag, lm=lm, last_ok=int(time.time()))
                if code != 304:
                    got = parse_feed(body, name)
                    items += got
                st["fail"] = 0
                ok += 1
            except Exception as e:                       # noqa: BLE001
                st["fail"] = st.get("fail", 0) + 1
                st["err"] = f"{type(e).__name__}: {str(e)[:120]}"
                fail.append(name)
    log(f"수집: 소스 {ok}/{len(srcs)} 성공, 기사 {len(items)}건" + (f", 실패 {fail}" if fail else ""))
    return items


# ═════════════════════════ 정규화·중복 ═════════════════════════
DROP_QS = re.compile(r"^(utm_|fbclid|gclid|ref|from|cmpid|sns|rss|ref_)", re.I)


def canon_url(u):
    p = urllib.parse.urlsplit(u.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not DROP_QS.match(k)]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"),
                                    urllib.parse.urlencode(q), ""))


def norm_title(t):
    t = re.sub(r"[\[\(【<〈][^\]\)】>〉]{0,12}[\]\)】>〉]", "", t)   # [단독] (종합) 등 말머리
    return re.sub(r"[^0-9A-Za-z가-힣]", "", t).lower()


def bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def similar(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / max(1, len(A | B))


def key_of(it):
    return hashlib.sha1(canon_url(it["link"]).encode()).hexdigest()[:16]


def tkey_of(it):
    return "t" + hashlib.sha1(norm_title(it["title"]).encode()).hexdigest()[:15]


# ═════════════════════════ 1차: 키워드 ═════════════════════════
def _kw_re(k):
    if re.fullmatch(r"[A-Za-z&]+", k):
        return re.compile(rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])", re.I)
    return re.compile(re.escape(k), re.I)


KW = {th: (cfg["w"], [_kw_re(k) for k in cfg["kw"]]) for th, cfg in C.THEMES.items()}


def kw_score(it):
    total, best, best_th = 0.0, 0.0, None
    for th, (w, regs) in KW.items():
        s = sum(2 for r in regs if r.search(it["title"])) + sum(1 for r in regs if r.search(it["desc"]))
        s = min(s, 6) * w
        total += s
        if s > best:
            best, best_th = s, th
    return round(total, 1), best_th


def excluded(it):
    return any(x in it["title"] for x in C.EXCLUDE)


EXCL_RE = re.compile(r"[\[\(【<〈]\s*단독\s*[\]\)】>〉]|^단독\s|^단독[:：]")


def is_exclusive(it):
    return bool(EXCL_RE.search(it["title"]))


def sector_hit(it):
    """제목에 관심 업종(AIDC·전력 / 반도체·기판 / AI / 정책) 키워드가 하나라도 있는지"""
    return any(r.search(it["title"]) for th in ("AIDC·전력", "반도체·기판", "AI", "정책")
               for r in KW[th][1])


# ═════════════════════════ 2차: Claude ═════════════════════════
PROMPT = """너는 한국 주식 리서치 채널의 데스크다. 아래 기사(제목+RSS요약)를 투자자 관점에서 심사해라.
관심 영역: AI·AI데이터센터·전력기기/에너지, 반도체·기판·소부장, 이와 관련된 정부 정책·규제, 시장을 움직일 속보(대형 수주·공시·실적).

각 기사마다 JSON 객체 하나:
- id: 입력의 id 그대로
- score: 1~5 정수
  5 = 지금 바로 알려야 할 속보급 — 주가를 당일 움직일 사건 (대형 정책 확정, 수천억 이상 수주·공급계약, 실적 서프라이즈/쇼크, 수출통제·관세 등 판을 바꾸는 뉴스). 하루 2~3건 수준.
  4 = 관심 영역에서 새로 확정된 구체적 사실 (숫자·계약 상대·일정·정부 결정이 기사에 명시됨). 하루 10건 안쪽.
  3 = 관련은 있지만 묶어서 봐도 되는 수준 (전망, 증권사 의견, 인터뷰, 업계 동향, 행사·MOU)
  2 이하 = 홍보성·칼럼·재탕·지역 행사·관심 영역 밖
  엄격하게 매겨라. 애매하면 낮은 점수. 대부분의 기사는 3 이하가 정상이다.
  단, 제목에 [단독]이 붙은 기사가 관심 영역(위 4가지)과 관련 있으면 최소 4점.
- theme: "AIDC·전력" | "반도체·기판" | "AI" | "정책" | "시장" 중 하나
- summary: 기사가 말하는 핵심 사실을 80자 이내 한국어 한두 문장으로. 제목을 그대로 베끼지 말고 숫자·주체·결정 위주. 원문 문장을 복사하지 말 것.
- stocks: 직접 언급되거나 직접 수혜/피해가 명확한 상장사 최대 3개. 한국 종목은 "#종목명", 미국 종목은 "$티커". 확실하지 않으면 빈 배열.

JSON 배열만 출력. 설명·코드펜스 금지.

기사:
{items}"""


def llm_review(cands):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not cands:
        return None
    payload = "\n".join(
        json.dumps({"id": i, "매체": c["src"], "제목": c["title"], "요약": c["desc"][:200]}, ensure_ascii=False)
        for i, c in enumerate(cands))
    body = json.dumps({
        "model": C.LLM_MODEL,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": PROMPT.format(items=payload)}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=C.LLM_TIMEOUT) as r:
                res = json.load(r)
            text = "".join(b.get("text", "") for b in res.get("content", []))
            return parse_llm(text, len(cands))
        except urllib.error.HTTPError as e:
            log(f"LLM HTTP {e.code}: {e.read()[:200]!r}")
            if e.code in (429, 500, 502, 503, 529):
                time.sleep(3 * (attempt + 1))
                continue
            return None
        except Exception as e:                           # noqa: BLE001
            log(f"LLM 오류: {e}")
            time.sleep(2)
    return None


def parse_llm(text, n):
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < a:
        return None
    try:
        arr = json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None
    out = {}
    for o in arr:
        try:
            i = int(o["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < n:
            stocks = [s for s in (o.get("stocks") or []) if isinstance(s, str) and re.match(r"^[#$]\S+$", s)][:3]
            out[i] = {"score": max(1, min(5, int(o.get("score", 1)))),
                      "theme": str(o.get("theme") or "")[:10],
                      "summary": clean(str(o.get("summary") or ""), 120),
                      "stocks": stocks}
    return out


# ═════════════════════════ 텔레그램 ═════════════════════════
def tg_send(text, chat=None, silent=False):
    chat = chat or os.environ.get("TELEGRAM_CHAT_ID")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if DRY or not token or not chat:
        print("─" * 40 + ("  (무음)" if silent else "") + "\n" + re.sub(r"<[^>]+>", "", text) + "\n", flush=True)
        return True
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                       "disable_notification": bool(silent),
                       "link_preview_options": {"is_disabled": True}}).encode()
    for _ in range(4):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                json.load(r)
            time.sleep(1.1)        # 채널 발송 한도(분당 ~20건) 여유
            return True
        except urllib.error.HTTPError as e:
            info = {}
            try:
                info = json.loads(e.read())
            except Exception:      # noqa: BLE001
                pass
            wait = (info.get("parameters") or {}).get("retry_after")
            if e.code == 429 and wait:
                log(f"텔레그램 429 → {wait}s 대기")
                time.sleep(int(wait) + 1)
                continue
            log(f"텔레그램 실패 {e.code}: {info.get('description')}")
            return False
        except Exception as e:     # noqa: BLE001
            log(f"텔레그램 오류: {e}")
            time.sleep(2)
    return False


def esc(s):
    return html.escape(s or "", quote=False)


def teaser(it, n=120):
    """요약 대용: RSS 요약문 첫 문장(최대 n자). 제목과 거의 같으면 생략."""
    d = re.sub(r"^\s*\[[^\]]{0,20}\]\s*", "", it.get("desc") or "")
    d = re.sub(r"^\s*[\(\[][^\)\]]{0,30}[\)\]]\s*", "", d)                   # "(서울=연합뉴스)" "[이데일리]"
    d = re.sub(r"^[가-힣A-Za-z·\s]{2,20}?(기자|특파원|객원기자)\s*[=:]?\s*", "", d)  # "홍길동 기자 ="
    d = re.sub(r"^\S{0,12}=\s*", "", d).strip()
    if not d or similar(norm_title(d[:60]), norm_title(it["title"])) > 0.6:
        return ""
    m = re.search(r"^(.{10,}?[다요음됨함]\.)\s", d + " ")
    s = m.group(1) if m else d
    return s if len(s) <= n else s[:n].rstrip() + "…"


def stock_tags(it):
    """LLM 종목 + 사전 매칭 종목을 합쳐 최대 4개."""
    text = f"{it['title']} {it.get('desc') or ''}"
    tags = list(it.get("stocks") or [])
    found = sorted((text.find(name), tag) for name, tag in C.STOCKS.items() if name in text)
    for _, tag in found:                       # 기사에 먼저 나온 종목부터 (제목 → 요약 순)
        if tag not in tags:
            tags.append(tag)
    return tags[:4]


def fmt_item(it):
    head = "🚨 " if it["score"] >= 5 else ""
    lines = [f'<b>{head}<a href="{html.escape(it["link"])}">{esc(it["title"])}</a></b>']
    body = it.get("summary") or teaser(it)
    if body:
        lines.append(esc(body))
    tags = stock_tags(it)
    if tags:
        lines.append(" ".join(esc(s) for s in tags))
    return "\n\n".join(lines)


def fmt_digest(buf, stamp):
    order = ["정책", "AIDC·전력", "반도체·기판", "AI", "시장"]
    buf = sorted(buf, key=lambda x: (order.index(x["theme"]) if x.get("theme") in order else 9,
                                     -x.get("score", 0)))
    lines = [f"<b>꾹쥐 뉴스 묶음 ({stamp})</b>", ""]
    for x in buf[:C.DIGEST_MAX_ITEMS]:
        th = f"[{x['theme']}] " if x.get("theme") else ""
        tags = stock_tags(x)
        stocks = (" " + " ".join(esc(s) for s in tags)) if tags else ""
        lines.append(f'▪ {th}<a href="{html.escape(x["link"])}">{esc(x["title"])}</a>{stocks}')
    if len(buf) > C.DIGEST_MAX_ITEMS:
        lines.append(f"\n외 {len(buf) - C.DIGEST_MAX_ITEMS}건")
    return "\n".join(lines)


# ═════════════════════════ 한 바퀴 ═════════════════════════
def one_pass(state):
    now = now_kst()
    raw = fetch_all(state)

    # ── 신규·신선도·제외어·중복 ──
    fresh, batch_titles = [], []
    max_age = dt.timedelta(hours=C.MAX_AGE_HOURS)
    recent = [t[0] for t in state["titles"]]
    for it in raw:
        k, tk = key_of(it), tkey_of(it)
        if k in state["seen"] or tk in state["seen"]:
            continue
        state["seen"][k] = state["seen"][tk] = int(time.time())
        if it["date"] and now - it["date"] > max_age:
            continue
        if excluded(it):
            continue
        nt = norm_title(it["title"])
        if len(nt) < 6 or any(similar(nt, r) >= C.SIMILAR_TITLE for r in recent + batch_titles):
            continue
        batch_titles.append(nt)
        it["kw"], it["kw_theme"] = kw_score(it)
        fresh.append(it)

    # 첫 실행: 지금 떠 있는 기사는 전부 '본 것'으로만 표시하고 발송 안 함 (폭탄 방지)
    if not state["warm"]:
        state["warm"] = True
        state["titles"] += [[t, int(time.time())] for t in batch_titles]
        log(f"첫 실행 워밍업: {len(fresh)}건을 기준선으로 저장, 발송 없음")
        return

    cands = sorted([x for x in fresh if x["kw"] >= C.PREFILTER_MIN], key=lambda x: -x["kw"])
    cands = cands[:C.LLM_MAX_BATCH]
    log(f"신규 {len(fresh)}건 → 키워드 통과 {len(cands)}건")
    state["titles"] += [[t, int(time.time())] for t in batch_titles]
    if not cands:
        return

    # ── 2차 심사 ──
    review = llm_review(cands)
    for i, c in enumerate(cands):
        r = (review or {}).get(i)
        if r:
            c.update(r)
            if c["theme"] not in ("AIDC·전력", "반도체·기판", "AI", "정책", "시장"):
                c["theme"] = {"시장속보": "시장"}.get(c["kw_theme"], c["kw_theme"])
        else:          # LLM 없거나 실패 → 키워드 점수로 대체 (보수적으로)
            # 업종 키워드만으로는 중요도를 못 가리므로, 4점 이상은 '사건' 단어(수주·계약·정책결정 등)가
            # 제목에 있어야만 줌. 나머지는 전부 3점(묶음)
            event = any(r.search(c["title"]) for th in ("시장속보", "정책") for r in KW[th][1])
            sector = sum(min(6, sum(2 for r in KW[th][1] if r.search(c["title"]))) * KW[th][0]
                         for th in ("AIDC·전력", "반도체·기판", "AI"))
            if event and c["kw"] >= 15 and sector >= 10:
                sc = 5
            elif event and c["kw"] >= 10:
                sc = 4
            else:
                sc = 3 if c["kw"] >= 4 else 2
            c.update(score=sc, theme={"시장속보": "시장"}.get(c["kw_theme"], c["kw_theme"]),
                     summary="", stocks=[])
        # 단독 기사: 관심 영역 키워드가 제목에 하나라도 있으면 최소 4점 (바로 발송)
        if is_exclusive(c) and sector_hit(c):
            c["score"] = max(c["score"], 4)

    quiet = now.hour in C.QUIET_HOURS_KST
    now_list, later = [], []
    for c in cands:
        if c["score"] >= 5 or (c["score"] >= C.SEND_NOW_MIN and not quiet):
            now_list.append(c)
        elif c["score"] >= C.DIGEST_MIN:
            later.append(c)

    # 발송 상한: 한 바퀴 MAX_SEND_PER_RUN, 최근 1시간 MAX_SEND_PER_HOUR
    hour_ago = time.time() - 3600
    state["sent_ts"] = [t for t in state.get("sent_ts", []) if t > hour_ago]
    room = max(0, min(C.MAX_SEND_PER_RUN, C.MAX_SEND_PER_HOUR - len(state["sent_ts"])))
    now_list.sort(key=lambda x: (-x["score"], not is_exclusive(x), -(x.get("kw") or 0)))
    sent = 0
    for c in now_list[:room]:
        if tg_send(fmt_item(c), silent=c["score"] < C.SILENT_BELOW):
            state["sent_ts"].append(int(time.time()))
            sent += 1
    later += now_list[room:]
    for c in later:
        state["digest"].append({k: c.get(k) for k in ("title", "link", "src", "theme", "score", "stocks", "desc")})
    log(f"즉시 {sent}건 · 묶음 대기 +{len(later)}건 (최근 1시간 발송 {len(state['sent_ts'])}건)")


def maybe_digest(state):
    now = now_kst()
    stamp = now.strftime("%Y-%m-%d-") + f"{now.hour:02d}"
    if now.hour not in C.DIGEST_HOURS_KST or state["last_digest"] == stamp:
        return
    state["last_digest"] = stamp
    if state["digest"]:
        tg_send(fmt_digest(state["digest"], now.strftime("%m/%d %H:00")), silent=True)
        log(f"묶음 발송 {len(state['digest'])}건")
        state["digest"] = []


def health(state):
    admin = os.environ.get("ADMIN_CHAT_ID")
    today = now_kst().strftime("%Y-%m-%d")
    names = {u: n for n, u in all_sources()}
    bad = [(names.get(u, u), st.get("err", "")) for u, st in state["feeds"].items()
           if u in names and st.get("fail", 0) >= C.FEED_FAIL_ALERT]
    if bad and admin and state["alert_day"] != today:
        state["alert_day"] = today
        msg = "<b>뉴스와이어 피드 점검</b>\n" + "\n".join(f"✕ {esc(n)} — {esc(e)}" for n, e in bad)
        msg += "\n\nconfig.py에서 주소를 고치거나 지우면 됨."
        tg_send(msg, chat=admin)


def _open_log():
    """--forever: 출력을 newswire.log 로 (2MB 넘으면 .old 로 넘김). pythonw 는 콘솔이 없어서 필수."""
    try:
        if os.path.getsize(LOG_PATH) > 2_000_000:
            os.replace(LOG_PATH, LOG_PATH + ".old")
    except OSError:
        pass
    f = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f


def forever():
    """PC 상시 실행. 1분마다 수집 → 발송. 어떤 오류가 나도 죽지 않고 다음 바퀴로."""
    import socket
    import traceback
    _open_log()
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", 47615))            # 이미 실행 중이면 포트가 잡혀 있음 → 종료
    except OSError:
        log("이미 실행 중 — 이 창은 종료")
        return
    log("=== 뉴스와이어 시작 (PC 상시 모드) ===")
    state = load_state()
    last_health = 0
    while True:
        t0 = time.time()
        try:
            load_secrets()
            if not os.environ.get("TELEGRAM_BOT_TOKEN"):
                log("secrets.env 에 TELEGRAM_BOT_TOKEN 이 비어 있음 — 1분 뒤 다시 확인")
            else:
                one_pass(state)
                maybe_digest(state)
                if time.time() - last_health > 3600:
                    health(state)
                    last_health = time.time()
            save_state(state)
        except Exception:                          # noqa: BLE001
            log("오류 (계속 진행):\n" + traceback.format_exc())
        time.sleep(max(5, C.POLL_SECONDS - (time.time() - t0)))


def main():
    load_secrets()
    if "--forever" in sys.argv:
        forever()
        return

    if "--check" in sys.argv:              # 피드 생존 점검만
        st = {"feeds": {}}
        for name, url in all_sources():
            try:
                code, body, *_ = http_get(url)
                n = len(parse_feed(body, name))
                print(f"OK   {n:>4}건  {name:<14} {url}")
            except Exception as e:         # noqa: BLE001
                print(f"FAIL       {name:<14} {url}  ← {type(e).__name__}: {str(e)[:80]}")
        return

    if "--test" in sys.argv:               # 형식 테스트: 지금 기사 중 가장 중요한 1건만 무음으로 발송
        raw = fetch_all({"feeds": {}})
        cutoff = now_kst() - dt.timedelta(hours=3)
        pool = [it for it in raw if not excluded(it) and (not it["date"] or it["date"] > cutoff)]
        for it in pool:
            it["kw"], it["kw_theme"] = kw_score(it)
        pool.sort(key=lambda x: -x["kw"])
        if not pool:
            log("테스트할 기사 없음")
            return
        top = pool[:10]
        review = llm_review(top) or {}
        for i, c in enumerate(top):
            c.update(review.get(i) or {"score": 4, "summary": "", "stocks": []})
        best = max(top, key=lambda x: (bool(stock_tags(x)) and bool(x.get("summary") or teaser(x)),
                                       x["score"], x["kw"]))
        best["score"] = min(best["score"], 4)    # 테스트는 🚨 없이
        ok = tg_send(fmt_item(best), silent=True)
        log(f"테스트 발송 {'성공' if ok else '실패'}: {best['title']}")
        return

    state = load_state()
    loop = float(os.environ.get("LOOP_MINUTES", "0") or 0)
    end = time.time() + loop * 60
    try:
        while True:
            t0 = time.time()
            one_pass(state)
            maybe_digest(state)
            save_state(state)
            if time.time() + C.POLL_SECONDS > end:
                break
            time.sleep(max(5, C.POLL_SECONDS - (time.time() - t0)))
        health(state)
    finally:
        save_state(state)


if __name__ == "__main__":
    main()
