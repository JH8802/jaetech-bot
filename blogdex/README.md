# 블덱스라이터 BETA 재현본 (blogdex)

블로그 원고 자동 생성 웹앱입니다. 화면은 스크린샷을 보고 따라 만들었고, 원고/제목 생성은 Claude API로 구현했습니다.
원본 서비스의 코드·프롬프트는 알 수 없으므로 "비슷하게 동작하는 버전"입니다.

## 기능

- 글 종류 선택: 정보글 / 맛집글 / 전문직 / 홍보글 / 커스텀 / 기타
- 제목 자동 생성 (후보 5개, `R` 키 또는 ⟳ 버튼으로 다시 생성)
- 원고 생성 (네이버 블로그에 붙여넣기 좋은 순수 텍스트, 글자 수 표시, 복사 버튼)
- 맛집글: 매장 이름 → [자동 입력] → 네이버 검색 API(지역)로 주소 후보 검색 → 선택한 정보를 원고에 사실로 반영
- 아직 미구현(탭만 비활성): 자동발행, 내 원고, 플랜, 비즈니스, 로그인

## 실행 방법

```bash
# 1) 저장소 루트에서 패키지 설치
pip install -r blogdex/requirements.txt

# 2) 루트의 .env 에 키 입력 (.env.example 참고)
#    ANTHROPIC_API_KEY=...            (필수)
#    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET   (맛집글 주소 검색용, 선택)

# 3) 실행
python blogdex/app.py
# → 브라우저에서 http://127.0.0.1:5000 접속
```

API 키 없이 화면만 확인하려면: `BLOGDEX_MOCK=1 python blogdex/app.py`  (샘플 결과를 돌려주며 비용 0원)

## 설정 (.env)

| 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude API 키 | 필수 |
| `BLOGDEX_MODEL` | 사용 모델. 비용을 줄이려면 `claude-sonnet-5-5` | `claude-opus-5-5` |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 네이버 검색 API 키 (https://developers.naver.com → 애플리케이션 등록 → '검색') | 없음 |
| `PORT` | 서버 포트 | `5000` |

## 구조

```
blogdex/
├── app.py            # Flask 서버 (/api/titles, /api/article, /api/places)
├── prompts.py        # 글 종류별 프롬프트 ← 결과물을 원본에 맞추려면 여기를 다듬습니다
├── static/index.html # 화면 (HTML+CSS+JS 한 파일)
└── requirements.txt
```

## 주의

- 서버는 `127.0.0.1`(본인 PC)에서만 열립니다. 외부에 공개하려면 로그인과 사용량 제한을 먼저 붙여야 API 비용 폭탄을 막을 수 있습니다.
- 맛집글 주소 검색은 네이버 검색 API(지역) 응답 형식 기준으로 작성했고, 실제 키로 호출해 본 테스트는 아직 못 했습니다.
