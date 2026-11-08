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
"""
import concurrent.futures as cf
import datetime as dt
import email.utils
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
DRY = os.environ.get("DRY_RUN") == "1"


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
                                               "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    if etag:
        req.add_header("If-None-Match", etag)
    if lm:
        req.add_header("If-Modified-Since", lm)
    try:
        with urllib.request.urlopen(req, timeout=timeout or C.HTTP_TIMEOUT) as r:
            return r.status, r.read(), r.headers.get("ETag"), r.headers.get("Last-Modified")
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


# ═════════════════════════ 2차: Claude ═════════════════════════
PROMPT = """너는 한국 주식 리서치 채널의 데스크다. 아래 기사(제목+RSS요약)를 투자자 관점에서 심사해라.
관심 영역: AI·AI데이터센터·전력기기/에너지, 반도체·기판·소부장, 이와 관련된 정부 정책·규제, 시장을 움직일 속보(대형 수주·공시·실적).

각 기사마다 JSON 객체 하나:
- id: 입력의 id 그대로
- score: 1~5 정수
  5 = 지금 바로 알려야 할 속보급 (대형 정책 발표, 대형 수주/계약, 실적 서프라이즈, 수출통제·관세 같은 판을 바꾸는 뉴스)
  4 = 관심 영역의 의미 있는 새 사실 (구체적 숫자·계약·일정·결정이 있음)
  3 = 관련은 있지만 묶어서 봐도 되는 수준 (전망, 인터뷰, 업계 동향)
  2 이하 = 홍보성·행사·칼럼·재탕·관심 영역 밖
- theme: "AIDC·전력" | "반도체·기판" | "AI" | "정책" | "시장" 중 하나
- summary: 기사가 말하는 핵심 사실을 50자 이내 한국어 한 문장으로. 제목을 그대로 베끼지 말고 숫자·주체·결정 위주. 원문 문장을 복사하지 말 것.
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
                      "summary": clean(str(o.get("summary") or ""), 80),
                      "stocks": stocks}
    return out


# ═════════════════════════ 텔레그램 ═════════════════════════
def tg_send(text, chat=None):
    chat = chat or os.environ.get("TELEGRAM_CHAT_ID")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if DRY or not token or not chat:
        print("─" * 40 + "\n" + re.sub(r"<[^>]+>", "", text) + "\n", flush=True)
        return True
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
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


def fmt_item(it):
    head = "[속보] " if it["score"] >= 5 else ""
    tag = f"[{it['theme']}] " if it.get("theme") else ""
    lines = [f"<b>{head}{tag}{esc(it['title'])}</b>"]
    if it.get("summary"):
        lines.append(esc(it["summary"]))
    if it.get("stocks"):
        lines.append(" ".join(esc(s) for s in it["stocks"]))
    when = it["date"].astimezone(KST).strftime("%H:%M") if it.get("date") else ""
    lines.append(f'<a href="{html.escape(it["link"])}">{esc(it["src"])}</a> · {when}')
    return "\n".join(lines)


def fmt_digest(buf, stamp):
    order = ["정책", "AIDC·전력", "반도체·기판", "AI", "시장"]
    buf = sorted(buf, key=lambda x: (order.index(x["theme"]) if x.get("theme") in order else 9,
                                     -x.get("score", 0)))
    lines = [f"<b>꾹쥐 뉴스 묶음 ({stamp})</b>", ""]
    for x in buf[:C.DIGEST_MAX_ITEMS]:
        th = f"[{x['theme']}] " if x.get("theme") else ""
        stocks = (" " + " ".join(esc(s) for s in x.get("stocks", []))) if x.get("stocks") else ""
        lines.append(f'▪ {th}<a href="{html.escape(x["link"])}">{esc(x["title"])}</a> — {esc(x["src"])}{stocks}')
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
        else:          # LLM 없거나 실패 → 키워드 점수로 대체
            c.update(score=5 if c["kw"] >= 12 else 4 if c["kw"] >= 7 else 3 if c["kw"] >= 4 else 2,
                     theme={"시장속보": "시장"}.get(c["kw_theme"], c["kw_theme"]), summary="", stocks=[])

    quiet = now.hour in C.QUIET_HOURS_KST
    now_list, later = [], []
    for c in cands:
        if c["score"] >= 5 or (c["score"] >= C.SEND_NOW_MIN and not quiet):
            now_list.append(c)
        elif c["score"] >= C.DIGEST_MIN:
            later.append(c)

    now_list.sort(key=lambda x: (-x["score"], x["date"] or now))
    overflow = now_list[C.MAX_SEND_PER_RUN:]
    for c in now_list[:C.MAX_SEND_PER_RUN]:
        tg_send(fmt_item(c))
    later += overflow
    for c in later:
        state["digest"].append({k: c.get(k) for k in ("title", "link", "src", "theme", "score", "stocks")})
    log(f"즉시 {min(len(now_list), C.MAX_SEND_PER_RUN)}건 · 묶음 대기 +{len(later)}건")


def maybe_digest(state):
    now = now_kst()
    stamp = now.strftime("%Y-%m-%d-") + f"{now.hour:02d}"
    if now.hour not in C.DIGEST_HOURS_KST or state["last_digest"] == stamp:
        return
    state["last_digest"] = stamp
    if state["digest"]:
        tg_send(fmt_digest(state["digest"], now.strftime("%m/%d %H:00")))
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


def main():
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
