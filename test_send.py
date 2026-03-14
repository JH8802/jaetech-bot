import asyncio
from telethon import TelegramClient
from telegram import Bot
from summarizer import is_important, summarize
from config import CHANNELS
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

# 테스트용으로 채널 10개만 사용
TEST_CHANNELS = CHANNELS[:10]


async def test_send():
    print("🔄 테스트 발행 시작...")
    bot = Bot(token=BOT_TOKEN)
    client = TelegramClient("session", API_ID, API_HASH)
    await client.start()

    messages = []
    for channel in TEST_CHANNELS:
        try:
            async for message in client.iter_messages(channel, limit=3):
                if message.text:
                    messages.append({
                        "channel": channel,
                        "text": message.text
                    })
            print(f"✅ {channel} 수집 완료")
        except Exception as e:
            print(f"❌ {channel} 실패: {e}")

    await client.disconnect()

    published = 0
    for msg in messages:
        print(f"🔍 중요도 판단 중: {msg['channel']}")
        if is_important(msg["channel"], msg["text"]):
            summary = summarize(msg["channel"], msg["text"])
            if summary:
                await bot.send_message(chat_id=CHANNEL_ID, text=summary)
                print(f"✅ 발행 완료: {msg['channel']}")
                published += 1
                await asyncio.sleep(2)
        else:
            print(f"⏭ 스킵: {msg['channel']}")

    print(f"\n🎉 총 {published}개 발행 완료!")

asyncio.run(test_send())
