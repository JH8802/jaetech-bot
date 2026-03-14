import asyncio
from telegram import Bot
from dotenv import load_dotenv
import os

load_dotenv()

async def test():
    bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    await bot.send_message(
        chat_id=os.getenv("TELEGRAM_CHANNEL_ID"),
        text="✅ 봇 연결 성공! 재테크 인사이트 채널 가동 준비 완료."
    )
    print("메시지 전송 성공!")

asyncio.run(test())