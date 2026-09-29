import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient
from telegram import Bot
from summarizer import select_important, summarize, summarize_for_threads, reset_api_counter
from config import CHANNELS
from dotenv import load_dotenv
import os
import json
from datetime import datetime, timezone, timedelta

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
API_ID_STR = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")  # 쓰레드 초안을 받을 개인 chat_id (선택)

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

LAST_CHECK_FILE = "last_check.json"


def get_last_check():
    try:
        with open(LAST_CHECK_FILE, "r") as f:
            data = json.load(f)
            return datetime.fromisoformat(data["last_check"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print("📌 last_check 없음 → 최근 10시간 메시지만 수집합니다.")
        return datetime.now(timezone.utc) - timedelta(hours=10)


def save_last_check():
    with open(LAST_CHECK_FILE, "w") as f:
        json.dump({"last_check": datetime.now(timezone.utc).isoformat()}, f)


LAST_THREADS_CHECK_FILE = "last_threads_check.json"


def get_last_threads_check():
    try:
        with open(LAST_THREADS_CHECK_FILE, "r") as f:
            data = json.load(f)
            return datetime.fromisoformat(data["last_check"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return datetime.now(timezone.utc) - timedelta(hours=6)


def save_last_threads_check():
    with open(LAST_THREADS_CHECK_FILE, "w") as f:
        json.dump({"last_check": datetime.now(timezone.utc).isoformat()}, f)


async def job():
    print(f"🔄 콘텐츠 수집 & 발행 시작... ({datetime.now().strftime('%H:%M')})")

    reset_api_counter()

    bot = Bot(token=BOT_TOKEN)
    last_check = get_last_check()

    try:
        # ✅ 수정 1: async with 사용 → 에러가 나도 자동으로 disconnect됨
        async with TelegramClient("session", API_ID, API_HASH) as client:
            messages = []
            for channel in CHANNELS:
                try:
                    async for message in client.iter_messages(channel, limit=30):
                        if not message.text:
                            continue
                        if last_check and message.date <= last_check:
                            break
                        messages.append({
                            "channel": channel,
                            "text": message.text
                        })
                except Exception as e:
                    print(f"❌ {channel} 수집 실패: {e}")

        save_last_check()

        print(f"📨 새 메시지 {len(messages)}개 수집됨")

        selected_messages = select_important(messages)
        print(f"⭐ 최종 선별: {len(selected_messages)}개")

        published = 0
        for msg in selected_messages:
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


async def threads_job():
    """텔레그램 발행과 별개로, 쓰레드 SNS용 초안을 만들어 관리자에게 DM으로 보낸다.
    실제 쓰레드 게시(마스코트 첨부 포함)는 본인이 직접 한다."""
    print(f"🧵 쓰레드 초안 생성 시작... ({datetime.now().strftime('%H:%M')})")

    if not ADMIN_CHAT_ID:
        print("⚠️ TELEGRAM_ADMIN_CHAT_ID가 설정되지 않아 쓰레드 초안 발송을 건너뜁니다.")
        return

    reset_api_counter()
    bot = Bot(token=BOT_TOKEN)
    last_check = get_last_threads_check()

    try:
        async with TelegramClient("session", API_ID, API_HASH) as client:
            messages = []
            for channel in CHANNELS:
                try:
                    async for message in client.iter_messages(channel, limit=30):
                        if not message.text:
                            continue
                        if last_check and message.date <= last_check:
                            break
                        messages.append({
                            "channel": channel,
                            "text": message.text
                        })
                except Exception as e:
                    print(f"❌ {channel} 수집 실패: {e}")

        save_last_threads_check()

        selected_messages = select_important(messages)

        if not selected_messages:
            print("📭 쓰레드용으로 쓸 만한 소식 없음")
            return

        # 여러 개 선별돼도 쓰레드용은 대표 1건만 사용 (증권사 채널이 있으면 우선)
        pick = selected_messages[0]
        draft = summarize_for_threads(pick["channel"], pick["text"])

        if draft:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🧵 쓰레드 초안 ({datetime.now().strftime('%H:%M')})\n\n{draft}"
            )
            print(f"✅ 쓰레드 초안 전송 완료: {pick['channel']}")
        else:
            print("📭 쓰레드 초안 요약 실패 또는 SKIP")

    except Exception as e:
        print(f"❌ 쓰레드 초안 생성 오류: {e}")


async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    times = [
        (6, 30), (8, 40),
        (9, 3), (11, 30), (14, 30), (15, 40),
        (18, 0), (21, 0)
    ]

    for hour, minute in times:
        # ✅ 수정 2: max_instances=1 → 실행이 겹치지 않음
        scheduler.add_job(job, "cron", hour=hour, minute=minute, max_instances=1)

    # 쓰레드 초안 발송 시간 (오전 8시 / 점심 12시 / 저녁 6시)
    # 18:00은 위 텔레그램 발행 시간과 겹쳐 같은 세션 파일 충돌이 날 수 있어 18:03으로 3분 늦춤
    threads_times = [(8, 0), (12, 0), (18, 3)]

    for hour, minute in threads_times:
        scheduler.add_job(threads_job, "cron", hour=hour, minute=minute, max_instances=1)

    scheduler.start()
    print("🚀 재테크 인사이트 봇 가동 시작!")
    print(f"📅 텔레그램 채널: 하루 {len(times)}회 자동 발행 예약 완료")
    print(f"🧵 쓰레드 초안 DM: 하루 {len(threads_times)}회 예약 완료 (08:00 / 12:00 / 18:03)")

    await job() 
    await asyncio.Event().wait()

asyncio.run(main())
