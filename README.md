# 꾹쥐 뉴스와이어

국내 언론 RSS 22개 + 구글뉴스 검색 8개 → 키워드 1차 → Claude 2차 심사 → 텔레그램 채널 자동 발송.
GitHub Actions에서 5분마다 돌고, 한 번 돌 때 4분간 1분 간격으로 재수집 → 체감 지연 1~3분.

```
RSS 수집 → 중복 제거(URL·제목 유사도) → 키워드 점수 → Claude 심사(1~5점·한줄요약·종목)
   5점        : 즉시 발송 [속보]  (새벽에도)
   4점        : 즉시 발송        (00~06시는 07시 묶음으로)
   3점        : 07 / 12 / 18시 묶음
   2점 이하   : 버림
```

## 설치 (휴대폰 브라우저로 가능, 10분)

**1. 텔레그램 봇**
- @BotFather → `/newbot` → 토큰 복사
- 봇을 채널 관리자로 추가 (메시지 게시 권한)
- 처음엔 비공개 테스트 채널로 돌려보고, 괜찮으면 `@kkukgee`로 바꾸기

**2. GitHub 레포**
- 새 레포 생성 → **Public** (공개 레포는 Actions 무료·무제한. 비공개면 월 2,000분 한도라 5분 주기는 초과)
- 비밀키는 Secrets에 들어가서 공개돼도 안 보임
- 파일 4개 업로드 (`Add file → Create new file`에 경로째 입력하면 폴더 자동 생성)
  - `newswire.py`
  - `config.py`
  - `.github/workflows/newswire.yml`
  - `.github/workflows/keepalive.yml`

**3. Secrets** — `Settings → Secrets and variables → Actions → New repository secret`

| 이름 | 값 | 필수 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather 토큰 | ✅ |
| `TELEGRAM_CHAT_ID` | `@채널아이디` (비공개 채널은 `-100…` 숫자) | ✅ |
| `ANTHROPIC_API_KEY` | console.anthropic.com 키 | 권장 |
| `ADMIN_CHAT_ID` | 본인 개인 채팅 ID — 피드 고장 경고 받는 곳 | 선택 |

API 키가 없으면 키워드 점수만으로 돌아감 (요약·종목 태그 빠짐, 노이즈 늘어남).

**4. 첫 실행**
- `Actions → newswire → Run workflow` → **check 체크** → 실행 → 로그에서 피드별 OK/FAIL 확인
- FAIL 난 피드는 `config.py`에서 지우거나 주소 수정 (디일렉·전기신문·매경 경제섹션은 미검증 주소)
- 그다음 check 끄고 한 번 실행 → **첫 실행은 기준선만 저장하고 발송 안 함** (기존 기사 폭탄 방지)
- 5분 뒤부터 자동 발송 시작

## 자주 고칠 곳 (`config.py`)

- `THEMES` — 키워드 추가/삭제. 테마별 `w`가 가중치
- `EXCLUDE` — 제목에 있으면 바로 버리는 단어
- `GNEWS_QUERIES` — RSS 없는 매체(`site:도메인`)나 정책 키워드 추가
- `SEND_NOW_MIN`, `DIGEST_HOURS_KST`, `QUIET_HOURS_KST` — 발송 기준과 시각
- 수집 주기: 레포 `Settings → Variables`에 `LOOP_MINUTES` (기본 4, 0이면 5분에 1번만)

## 알아둘 것

- GitHub 예약 실행은 몰리는 시간대에 몇 분씩 밀릴 수 있음. 초 단위 속보가 필요하면 VPS로 옮기는 게 맞음 (코드는 그대로 `LOOP_MINUTES=60` + cron 1시간)
- 공개 레포는 60일 활동 없으면 예약이 멈춤 → `keepalive.yml`이 매달 1일 빈 커밋으로 막음
- 발송 내용은 제목 + 자체 한줄요약 + 원문 링크만. 기사 본문은 긁지 않음 (언론사 RSS 이용 조건 — 이투데이는 비상업 목적 명시)
- 정책브리핑(korea.kr) RSS는 2026-07-01 서비스 종료 → 정책은 구글뉴스 검색으로 보강
- 로컬 테스트: `DRY_RUN=1 python3 newswire.py` (텔레그램 대신 콘솔 출력)
