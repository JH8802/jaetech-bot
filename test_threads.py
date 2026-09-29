import asyncio
from telethon import TelegramClient
from telegram import Bot
from summarizer import select_important, summarize_for_threads, reset_api_counter
from config import CHANNELS
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

# 테스트용으로 채널 10개만 사용
TEST_CHANNELS = CHANNELS[:10]


async def test_threads():
    print("🧵 쓰레드 초안 테스트 시작...")
    reset_api_counter()

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
    print(f"📨 수집 완료: {len(messages)}개")

    selected = select_important(messages)
    print(f"⭐ 선별: {len(selected)}개")

    if not selected:
        print("📭 쓰레드용으로 쓸 만한 소식이 없습니다. (테스트는 채널 10개만 사용해서 그럴 수 있음)")
        return

    pick = selected[0]
    draft = summarize_for_threads(pick["channel"], pick["text"])

    if not draft:
        print("❌ 쓰레드 초안 생성 실패 (SKIP 또는 API 오류)")
        return

    print("\n" + "=" * 40)
    print(draft)
    print("=" * 40 + "\n")

    if ADMIN_CHAT_ID:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🧵 [테스트] 쓰레드 초안\n\n{draft}"
        )
        print("✅ 본인 텔레그램으로 테스트 DM 전송 완료! 확인해보세요.")
    else:
        print("ℹ️ TELEGRAM_ADMIN_CHAT_ID가 없어서 DM 전송은 건너뛰었습니다. (위 결과만 확인)")

asyncio.run(test_threads())
