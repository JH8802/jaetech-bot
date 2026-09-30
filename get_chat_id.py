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
    updates = await bot.get_updates(allowed_updates=[])  # 모든 종류의 업데이트를 다 받음

    print(f"🔍 전체 업데이트 수: {len(updates)}개\n")

    if not updates:
        print("❌ 최근 업데이트가 없습니다.")
        print("텔레그램에서 본인 봇에게 먼저 메시지(예: hi)를 보낸 뒤 다시 실행하세요.")
        return

    seen = {}
    for update in updates:
        # 메시지/채널 게시물/봇 차단-시작 등 어떤 형태로 오든 chat_id를 찾아봄
        fields = {
            "message": update.message,
            "edited_message": update.edited_message,
            "channel_post": update.channel_post,
            "edited_channel_post": update.edited_channel_post,
            "my_chat_member": update.my_chat_member,
        }
        present = [name for name, val in fields.items() if val is not None]
        print(f"  - update_id={update.update_id}, 종류={present}")

        candidate = update.message or update.edited_message or update.channel_post or update.my_chat_member

        if candidate is not None:
            chat = candidate.chat
            name = getattr(chat, "username", None) or getattr(chat, "first_name", None) or chat.title or "알 수 없음"
            seen[chat.id] = f"{name} ({chat.type})"

    print()
    if not seen:
        print("⚠️ 업데이트는 있는데 chat 정보를 못 찾았습니다. 위 '종류' 목록을 캡쳐해서 보여주세요.")
        return

    print("📋 후보 chat_id 목록:\n")
    for chat_id, name in seen.items():
        print(f"  chat_id: {chat_id}   (대상: {name})")

    print("\n본인 개인 대화(private)로 나온 chat_id를 .env 파일의 TELEGRAM_ADMIN_CHAT_ID= 뒤에 입력하세요.")


asyncio.run(main())
