import asyncio
from telethon import TelegramClient
from config import CHANNELS
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")


async def collect():
    client = TelegramClient("session", API_ID, API_HASH)
    await client.start()

    messages = []
    for channel in CHANNELS:
        try:
            async for message in client.iter_messages(channel, limit=3):
                if message.text:
                    messages.append({
                        "channel": channel,
                        "text": message.text,
                        "date": message.date
                    })
            print(f"✅ {channel} 수집 완료")
        except Exception as e:
            print(f"❌ {channel} 수집 실패: {e}")

    await client.disconnect()
    print(f"\n총 {len(messages)}개 메시지 수집 완료!")
    return messages

asyncio.run(collect())
