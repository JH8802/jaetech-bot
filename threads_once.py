"""
쓰레드 초안을 '한 번만' 만들어서 DM으로 보내는 스크립트.
main.py처럼 계속 켜져있지 않아도 되고, 실행하면 1번 작업하고 바로 종료함.
→ cron-job.org가 하루 3번 GitHub Actions를 호출해서 이 스크립트를 실행함.
"""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto
from telegram import Bot

from summarizer import select_important, pick_for_threads, summarize_for_threads, reset_api_counter
from config import CHANNELS

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
STRING_SESSION = os.getenv("TELETHON_STRING_SESSION")

# main.py의 last_threads_check.json과는 별개 (GitHub Actions에서는
# 커밋으로 상태를 남겨야 다음 실행 때도 이어서 확인 가능하기 때문에
# .gitignore에 안 걸리는 별도 파일을 씀)
STATE_FILE = "threads_state.json"
RECENT_SECTORS_KEEP = 3  # 하루 3번 발행 → 최근 하루치 섹터는 피함
MAX_PICK_CANDIDATES = 15


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def get_last_check(state):
    try:
        return datetime.fromisoformat(state["last_check"])
    except (KeyError, TypeError, ValueError):
        return datetime.now(timezone.utc) - timedelta(hours=8)


async def main():
    print(f"🧵 쓰레드 초안 생성 시작... ({datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST)")

    if not ADMIN_CHAT_ID:
        print("⚠️ TELEGRAM_ADMIN_CHAT_ID가 설정되지 않았습니다. (GitHub Secrets 확인)")
        return

    reset_api_counter()
    bot = Bot(token=BOT_TOKEN)
    state = load_state()
    last_check = get_last_check(state)
    recent_sectors = state.get("recent_sectors", [])

    async with TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH) as client:
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
                        "text": message.text,
                        # 링크 미리보기 썸네일 말고, 실제로 첨부된 사진(차트·표)만
                        "has_image": isinstance(message.media, MessageMediaPhoto),
                        "message": message,
                    })
            except Exception as e:
                print(f"❌ {channel} 수집 실패: {e}")

        state["last_check"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        print(f"📨 새 메시지 {len(messages)}개 수집됨")

        selected_messages = select_important(messages)
        print(f"⭐ 선별: {len(selected_messages)}개")

        if not selected_messages:
            print("📭 쓰레드용으로 쓸 만한 소식 없음 (이번 타임슬롯은 DM 없이 종료)")
            return

        candidates = selected_messages[:MAX_PICK_CANDIDATES]
        index, sector = pick_for_threads(candidates, recent_sectors)
        pick = candidates[index]
        print(f"🎯 소재 선택: [{sector}] {pick['channel']} (최근 섹터: {recent_sectors or '없음'})")

        draft = summarize_for_threads(pick["channel"], pick["text"], sector=sector)
        if not draft:
            print("📭 요약 실패 또는 SKIP")
            return

        # 원문에 붙은 실제 차트/표 이미지를 그대로 가져옴 (AI 이미지 대신 쓰도록)
        image_bytes = None
        if pick["has_image"]:
            try:
                image_bytes = await client.download_media(pick["message"], file=bytes)
            except Exception as e:
                print(f"⚠️ 원문 이미지 다운로드 실패: {e}")

    if not image_bytes:
        draft += "\n\n📷 첨부할 원문 이미지가 없어요. 관련 차트(MTS 캡처, 리포트 표 등)를 직접 붙여주세요. AI 이미지보다 실제 데이터 이미지가 반응이 좋았어요."

    await bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🧵 쓰레드 초안 ({datetime.now(KST).strftime('%H:%M')})\n\n{draft}"
    )

    if image_bytes:
        try:
            await bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=image_bytes,
                caption=f"📎 원문 첨부 이미지 (출처: t.me/{pick['channel']}) — 쓰레드에 쓸 땐 출처를 같이 적어주세요."
            )
        except Exception as e:
            print(f"⚠️ 원문 이미지 전송 실패: {e}")

    state["recent_sectors"] = (recent_sectors + [sector])[-RECENT_SECTORS_KEEP:]
    save_state(state)
    print(f"✅ 쓰레드 초안 전송 완료: [{sector}] {pick['channel']}")


asyncio.run(main())
