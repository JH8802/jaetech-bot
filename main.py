import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient
from telegram import Bot
from summarizer import is_important, summarize
from config import CHANNELS
from dotenv import load_dotenv
import os
import json
from datetime import datetime, timezone

load_dotenv()

# 환경변수 로드 (누락 시 명확한 에러 메시지)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
API_ID_STR = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")

if not all([BOT_TOKEN, CHANNEL_ID, API_ID_STR, API_HASH]):
    missing = [name for name, val in {
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_CHANNEL_ID": CHANNEL_ID,
        "TELEGRAM_API_ID": API_ID_STR,
        "TELEGRAM_API_HASH": API_HASH,
    }.items() if not val]
    raise ValueError(f"❌ .env 파일에 다음 값이 없습니다: {', '.join(missing)}")

try:
    API_ID = int(API_ID_STR)
except ValueError:
    raise ValueError(f"❌ TELEGRAM_API_ID는 숫자여야 합니다. 현재 값: {API_ID_STR}")

# 마지막 수집 시간 저장 파일
LAST_CHECK_FILE = "last_check.json"


def get_last_check():
    try:
        with open(LAST_CHECK_FILE, "r") as f:
            data = json.load(f)
            return datetime.fromisoformat(data["last_check"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def save_last_check():
    with open(LAST_CHECK_FILE, "w") as f:
        json.dump({"last_check": datetime.now(timezone.utc).isoformat()}, f)


async def job():
    print(f"🔄 콘텐츠 수집 & 발행 시작... ({datetime.now().strftime('%H:%M')})")
    bot = Bot(token=BOT_TOKEN)
    last_check = get_last_check()

    try:
        client = TelegramClient("session", API_ID, API_HASH)
        await client.start()

        messages = []
        for channel in CHANNELS:
            try:
                async for message in client.iter_messages(channel, limit=10):
                    if not message.text:
                        continue
                    # 마지막 수집 이후 새 메시지만
                    if last_check and message.date <= last_check:
                        break
                    messages.append({
                        "channel": channel,
                        "text": message.text
                    })
            except Exception as e:
                print(f"❌ {channel} 수집 실패: {e}")

        await client.disconnect()
        save_last_check()

        print(f"📨 새 메시지 {len(messages)}개 수집됨")

        published = 0
        for msg in messages:
            if is_important(msg["channel"], msg["text"]):
                summary = summarize(msg["channel"], msg["text"])
                if summary:
                    await bot.send_message(chat_id=CHANNEL_ID, text=summary)
                    print(f"✅ 발행: {msg['channel']}")
                    published += 1
                    await asyncio.sleep(2)

        if published == 0:
            print("📭 발행할 중요 메시지 없음")
        else:
            print(f"🎉 총 {published}개 발행 완료!")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")


async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    times = [
        (6, 30), (7, 30), (8, 0), (8, 30), (8, 45),
        (9, 3), (9, 30), (10, 0), (11, 0), (11, 30),
        (12, 0), (13, 0), (14, 0), (14, 30), (15, 0),
        (15, 35), (16, 0), (17, 0), (18, 0), (20, 0),
        (21, 0), (22, 0)
    ]

    for hour, minute in times:
        scheduler.add_job(job, "cron", hour=hour, minute=minute)

    scheduler.start()
    print("🚀 재테크 인사이트 봇 가동 시작!")
    print(f"📅 하루 {len(times)}회 자동 발행 예약 완료")

    await asyncio.Event().wait()

asyncio.run(main())
