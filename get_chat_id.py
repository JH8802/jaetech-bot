"""
본인의 텔레그램 chat_id를 확인하는 헬퍼 스크립트.
(쓰레드 초안 DM을 받으려면 TELEGRAM_ADMIN_CHAT_ID 설정이 필요한데, 그 값을 찾기 위한 용도)

사용법:
1. 텔레그램 앱에서 본인 봇(@BotFather로 만든 그 봇)에게 아무 메시지나 1개 보내기 (예: "hi")
2. 터미널에서 python get_chat_id.py 실행
3. 출력된 chat_id 숫자를 .env 파일의 TELEGRAM_ADMIN_CHAT_ID= 뒤에 입력
"""
import asyncio
import os
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def main():
    bot = Bot(token=BOT_TOKEN)
    updates = await bot.get_updates()

    if not updates:
        print("❌ 최근 메시지가 없습니다.")
        print("텔레그램에서 본인 봇에게 먼저 메시지(예: hi)를 보낸 뒤 다시 실행하세요.")
        return

    seen = {}
    for update in updates:
        if update.message:
            chat = update.message.chat
            name = chat.username or chat.first_name or "알 수 없음"
            seen[chat.id] = name

    print("📋 최근 이 봇에게 메시지를 보낸 사람 목록:\n")
    for chat_id, name in seen.items():
        print(f"  chat_id: {chat_id}   (보낸 사람: {name})")

    print("\n본인의 chat_id를 .env 파일의 TELEGRAM_ADMIN_CHAT_ID= 뒤에 입력하세요.")


asyncio.run(main())
