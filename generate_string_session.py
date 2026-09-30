"""
기존 session.session 파일의 로그인 정보를 훨씬 짧은 '문자열'로 변환하는
1회용 스크립트. (재로그인 필요 없음, 기존 session.session을 그대로 활용)

GitHub Actions에 45KB짜리 세션 파일을 통째로 base64로 넘기려다 보니
GitHub Secrets 용량 문제로 계속 실패했음 -> 문자열 하나로 압축해서
훨씬 안전하게 넘기는 방식으로 변경.

사용법:
1. python generate_string_session.py 실행
2. 출력된 문자열을 GitHub Secret 'TELETHON_STRING_SESSION'에 등록
"""
import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")


async def main():
    async with TelegramClient("session", API_ID, API_HASH) as client:
        string_session = StringSession.save(client.session)

    print("\n" + "=" * 60)
    print(string_session)
    print("=" * 60)
    print(f"\n길이: {len(string_session)}자")
    print("위 문자열을 GitHub Secret 'TELETHON_STRING_SESSION'에 등록하세요.")


asyncio.run(main())
