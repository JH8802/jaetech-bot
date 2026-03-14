# 🤖 재테크 인사이트 봇 (Jaetech Bot)

텔레그램 재테크 채널들의 메시지를 자동으로 수집하고, AI(Claude)가 중요한 투자 정보를 요약하여 텔레그램 채널에 발행하는 봇입니다.

## 주요 기능

- **자동 수집**: 50개+ 텔레그램 재테크 채널에서 새 메시지 수집
- **AI 중요도 판단**: Claude Haiku가 투자자에게 중요한 정보인지 자동 판별
- **AI 요약 발행**: 중요 메시지를 구조화된 형식으로 요약하여 채널에 발행
- **스케줄링**: 하루 22회 자동 실행 (장 시작 전 ~ 장 마감 후)
- **중복 방지**: 마지막 수집 시간 기록으로 중복 발행 차단

## 프로젝트 구조

```
jaetech-bot/
├── main.py            # 메인 실행 파일 (스케줄러 + 수집/발행)
├── summarizer.py      # AI 중요도 판단 + 요약 생성
├── collector.py       # 채널 메시지 수집 (단독 테스트용)
├── config.py          # 채널 목록 설정
├── test_bot.py        # 봇 연결 테스트
├── test_send.py       # 수집→요약→발행 테스트
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

### 5. 봇 실행
```bash
# 봇 연결 테스트
python test_bot.py

# 수집→요약 테스트 (소량)
python test_send.py

# 본 실행 (스케줄러 가동)
python main.py
```

## 발행 시간표

| 시간대 | 실행 시각 |
|-------|----------|
| 장 시작 전 | 06:30, 07:30, 08:00, 08:30, 08:45 |
| 장중 | 09:03, 09:30, 10:00, 11:00, 11:30, 12:00, 13:00, 14:00, 14:30, 15:00 |
| 장 마감 후 | 15:35, 16:00, 17:00, 18:00, 20:00, 21:00, 22:00 |

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

## 기술 스택

- **Python 3.10+**
- **Telethon** - 텔레그램 채널 메시지 수집
- **python-telegram-bot** - 봇 메시지 발행
- **Anthropic Claude Haiku** - AI 중요도 판단 및 요약
- **APScheduler** - 정시 자동 실행
