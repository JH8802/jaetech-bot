# 🤖 재테크 인사이트 봇 (Jaetech Bot)

텔레그램 재테크 채널들의 메시지를 자동으로 수집하고, AI(Claude)가 중요한 투자 정보를 요약하여 텔레그램 채널에 발행하는 봇입니다.

## 주요 기능

- **자동 수집**: 50개+ 텔레그램 재테크 채널에서 새 메시지 수집
- **AI 중요도 판단**: Claude Haiku가 투자자에게 중요한 정보인지 자동 판별
- **AI 요약 발행**: 중요 메시지를 구조화된 형식으로 요약하여 채널에 발행
- **스케줄링**: 하루 22회 자동 실행 (장 시작 전 ~ 장 마감 후)
- **중복 방지**: 마지막 수집 시간 기록으로 중복 발행 차단
- **쓰레드(Threads) 초안 발송**: 하루 3회(08:00/12:00/18:03), 대표 소식 1건을 SNS 캐주얼 톤으로 바꿔 관리자에게 DM으로 전송 (실제 게시는 본인이 마스코트 이미지 첨부 후 직접)

## 프로젝트 구조

```
jaetech-bot/
├── main.py            # 메인 실행 파일 (스케줄러 + 수집/발행)
├── summarizer.py      # AI 중요도 판단 + 요약 생성
├── collector.py       # 채널 메시지 수집 (단독 테스트용)
├── config.py          # 채널 목록 설정
├── test_bot.py        # 봇 연결 테스트
├── test_send.py       # 수집→요약→발행 테스트
├── test_threads.py    # 쓰레드 초안 생성 테스트
├── get_chat_id.py     # 본인 텔레그램 chat_id 확인용 헬퍼
├── threads_once.py    # 쓰레드 초안 1회 생성+발송 (GitHub Actions용)
├── generate_string_session.py  # 세션을 짧은 문자열로 변환 (GitHub Secret용, 1회성)
├── .github/
│   └── workflows/
│       └── threads_draft.yml  # PC 없이 하루 3번 자동 실행 설정
├── requirements.txt   # Python 패키지 목록
├── .env.example       # 환경변수 템플릿
└── .gitignore
```

## 설치 방법

### 1. 저장소 클론
```bash
git clone https://github.com/사용자이름/jaetech-bot.git
cd jaetech-bot
```

### 2. 가상환경 생성 및 활성화
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. 패키지 설치
```bash
pip install -r requirements.txt
```

### 4. 환경변수 설정
```bash
# .env.example을 복사하여 .env 파일 생성
cp .env.example .env    # Mac/Linux
copy .env.example .env  # Windows
```

`.env` 파일을 열어 아래 값들을 입력하세요:

| 환경변수 | 설명 | 발급 방법 |
|---------|------|----------|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | @BotFather에서 `/newbot` |
| `TELEGRAM_CHANNEL_ID` | 발행할 채널 ID | 예: `@puel_insight` |
| `TELEGRAM_API_ID` | 텔레그램 API ID | [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | 텔레그램 API Hash | [my.telegram.org](https://my.telegram.org) |
| `ANTHROPIC_API_KEY` | Claude API 키 | [console.anthropic.com](https://console.anthropic.com) |
| `TELEGRAM_ADMIN_CHAT_ID` | 쓰레드 초안을 받을 본인 chat_id (선택) | 아래 5번 `get_chat_id.py` 실행해서 확인 |

### 5. 봇 실행
```bash
# 봇 연결 테스트
python test_bot.py

# 수집→요약 테스트 (소량)
python test_send.py

# (선택) 쓰레드 초안 기능을 쓰려면, 본인 봇에게 메시지 1개 먼저 보낸 뒤:
python get_chat_id.py
# → 출력된 chat_id를 .env의 TELEGRAM_ADMIN_CHAT_ID에 입력

# 쓰레드 초안 생성 테스트 (소량)
python test_threads.py

# 본 실행 (스케줄러 가동)
python main.py
```

## 발행 시간표

| 시간대 | 실행 시각 |
|-------|----------|
| 장 시작 전 | 06:30, 07:30, 08:00, 08:30, 08:45 |
| 장중 | 09:03, 09:30, 10:00, 11:00, 11:30, 12:00, 13:00, 14:00, 14:30, 15:00 |
| 장 마감 후 | 15:35, 16:00, 17:00, 18:00, 20:00, 21:00, 22:00 |

### 쓰레드 초안 DM 시간표

| 시간 | 비고 |
|------|------|
| 08:00 | 오전 |
| 12:00 | 점심 |
| 18:03 | 저녁 (텔레그램 채널 18:00 발행과 겹치지 않도록 3분 늦춤) |

`TELEGRAM_ADMIN_CHAT_ID`를 설정해두면, 해당 시간마다 대표 소식 1건을 쓰레드용 캐주얼 톤으로 바꿔서 DM으로 보내줍니다. 마지막 해시태그 옆에 `(호재)` / `(악재)` / `(중립)` 태그가 붙어 있으니, 이걸 보고 어울리는 마스코트 이미지를 골라 직접 쓰레드에 게시하면 됩니다.

### PC를 꺼둬도 쓰레드 초안 받기 (GitHub Actions)

`main.py`는 실행 중인 동안에만 동작하지만, 쓰레드 초안 기능만큼은 **GitHub Actions**를 이용해 PC 전원과 무관하게 하루 3번(08:00 / 12:00 / 18:03 KST) 자동 실행되도록 만들어뒀습니다 (`.github/workflows/threads_draft.yml`, 실행 스크립트는 `threads_once.py`). GitHub 서버가 대신 실행해주는 방식이라 PC를 꺼도, 회사에 있어도 그대로 동작합니다.

**설정 방법 (최초 1회만, PC 필요)**

1. GitHub 저장소 페이지 → Settings → Secrets and variables → Actions → "New repository secret"에서 아래 6개를 각각 등록:

| Secret 이름 | 값 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `.env`에 있는 값과 동일 |
| `TELEGRAM_API_ID` | `.env`에 있는 값과 동일 |
| `TELEGRAM_API_HASH` | `.env`에 있는 값과 동일 |
| `TELEGRAM_ADMIN_CHAT_ID` | `.env`에 있는 값과 동일 |
| `ANTHROPIC_API_KEY` | `.env`에 있는 값과 동일 |
| `TELETHON_STRING_SESSION` | 아래 스크립트로 만든 값 |

2. `TELETHON_STRING_SESSION` 값 만들기 — 프로젝트 폴더에서:
```bash
python generate_string_session.py
```
기존 `session.session`을 그대로 활용해서 재로그인 없이 짧은 문자열 하나로 변환해줍니다. 출력된 문자열을 그대로 `TELETHON_STRING_SESSION` 시크릿 값 칸에 붙여넣기.

(참고: 처음엔 `session.session` 파일 자체를 base64로 인코딩해서 통째로 시크릿에 넣으려 했으나, 45KB 파일이 6만자 넘는 base64 문자열이 되면서 GitHub Secrets에서 계속 `base64: invalid input` 오류가 발생했습니다. Telethon의 `StringSession`으로 인증 정보만 압축해서 옮기는 방식으로 바꿔 해결했습니다.)

3. 6개 다 등록했으면, GitHub 저장소의 **Actions 탭** → "쓰레드 초안 발송" 워크플로우 → **Run workflow** 버튼으로 지금 바로 테스트 가능 (PC 없이 폰 브라우저로도 가능).

설정은 한 번만 하면 되고, 그 이후로는 PC를 계속 꺼둬도 GitHub가 알아서 하루 3번 실행해줍니다.

**주의**: PC에서 `main.py`도 동시에 켜두면 같은 시간대에 쓰레드 초안이 중복으로 올 수 있습니다. GitHub Actions를 쓰기로 했다면 `main.py`는 텔레그램 채널 발행 용도로만 쓰고, 쓰레드 초안은 GitHub Actions 쪽에 맡기는 것을 권장합니다.

## 발행 메시지 형식

```
📌 [핵심 제목]

📝 내용:
- 구체적 수치 포함 요약 2~3줄

💡 투자 포인트:
- 투자자 관점 핵심 1~2가지

🔍 관련 종목 (참고용):
- 종목명 종목코드

🔗 출처: https://t.me/채널명
⚠️ 본 내용은 투자 참고용이며 투자 권유가 아닙니다.
```

## 주의사항

- `.env` 파일은 절대 GitHub에 올리지 마세요 (API 키 노출 위험)
- `session.session` 파일은 텔레그램 로그인 세션이므로 공유하지 마세요
- 본 봇의 발행 내용은 투자 참고용이며, 투자 판단은 본인 책임입니다
- `python main.py`는 실행 중인 동안에만 스케줄이 동작합니다. 하루 종일(텔레그램 발행 + 쓰레드 초안 DM 포함) 계속 돌아가게 하려면 컴퓨터를 계속 켜두거나, 상시 구동 서버(PC 자체, 클라우드 VM 등)에서 실행해야 합니다

## 기술 스택

- **Python 3.10+**
- **Telethon** - 텔레그램 채널 메시지 수집
- **python-telegram-bot** - 봇 메시지 발행
- **Anthropic Claude Haiku** - AI 중요도 판단 및 요약
- **APScheduler** - 정시 자동 실행
