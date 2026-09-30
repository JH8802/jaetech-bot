"""
쓰레드 초안을 '한 번만' 만들어서 DM으로 보내는 스크립트.
main.py처럼 계속 켜져있지 않아도 되고, 실행하면 1번 작업하고 바로 종료함.
→ GitHub Actions가 하루 3번 이 스크립트를 대신 실행해줌 (PC를 안 켜둬도 됨).
"""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from telethon import TelegramClient
from telegram import Bot

from summarizer import select_important, summarize_for_threads, reset_api_counter
from config import CHANNELS

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

# main.py의 last_threads_check.json과는 별개 (GitHub Actions에서는
# 커밋으로 상태를 남겨야 다음 실행 때도 이어서 확인 가능하기 때문에
# .gitignore에 안 걸리는 별도 파일을 씀)
STATE_FILE = "threads_state.json"


def get_last_check():
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return datetime.fromisoformat(data["last_check"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return datetime.now(timezone.utc) - timedelta(hours=8)


def save_last_check():
    with open(STATE_FILE, "w") as f:
        json.dump({"last_check": datetime.now(timezone.utc).isoformat()}, f)


async def main():
    print(f"🧵 쓰레드 초안 생성 시작... ({datetime.now().strftime('%Y-%m-%d %H:%M')})")

    if not ADMIN_CHAT_ID:
        print("⚠️ TELEGRAM_ADMIN_CHAT_ID가 설정되지 않았습니다. (GitHub Secrets 확인)")
        return

    reset_api_counter()
    bot = Bot(token=BOT_TOKEN)
    last_check = get_last_check()

    messages = []
    async with TelegramClient("session", API_ID, API_HASH) as client:
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
    print(f"⭐ 선별: {len(selected_messages)}개")

    if not selected_messages:
        print("📭 쓰레드용으로 쓸 만한 소식 없음 (이번 타임슬롯은 DM 없이 종료)")
        return

    pick = selected_messages[0]
    draft = summarize_for_threads(pick["channel"], pick["text"])

    if draft:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🧵 쓰레드 초안 ({datetime.now().strftime('%H:%M')})\n\n{draft}"
        )
        print(f"✅ 쓰레드 초안 전송 완료: {pick['channel']}")
    else:
        print("📭 요약 실패 또는 SKIP")


asyncio.run(main())
