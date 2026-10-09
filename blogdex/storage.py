"""원고 저장소(SQLite). 개인용이라 파일 하나로 충분합니다.

저장 위치는 .env 의 BLOGDEX_DB (기본: blogdex/data/blogdex.db).
원고 텍스트는 기한 없이 보관합니다. (사진 보관기간은 사진 기능을 붙일 때 정합니다.)
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / "data" / "blogdex.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title_input TEXT NOT NULL,
    title_final TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    place_json TEXT NOT NULL DEFAULT '{}',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    options_json TEXT NOT NULL DEFAULT '{}',
    body TEXT NOT NULL,
    chars INTEGER NOT NULL DEFAULT 0,
    quality_json TEXT NOT NULL DEFAULT '{}',
    model TEXT NOT NULL DEFAULT '',
    parent_id INTEGER,
    created_at TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.getenv("BLOGDEX_DB", str(DEFAULT_DB)))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def save_article(*, kind, title_input, title_final, memo, place, keywords, options, body, chars, quality, model, parent_id=None) -> int:
    with closing(_connect()) as con, con:
        cur = con.execute(
            "INSERT INTO articles (kind,title_input,title_final,memo,place_json,keywords_json,options_json,body,chars,quality_json,model,parent_id,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, title_input, title_final, memo, json.dumps(place, ensure_ascii=False), json.dumps(keywords, ensure_ascii=False),
             json.dumps(options, ensure_ascii=False), body, chars, json.dumps(quality, ensure_ascii=False), model, parent_id,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        return cur.lastrowid


def _row(r: sqlite3.Row, full: bool) -> dict:
    d = {"id": r["id"], "kind": r["kind"], "title": r["title_final"], "chars": r["chars"], "created_at": r["created_at"]}
    if full:
        d.update({
            "title_input": r["title_input"], "memo": r["memo"], "body": r["body"], "model": r["model"], "parent_id": r["parent_id"],
            "place": json.loads(r["place_json"]), "keywords": json.loads(r["keywords_json"]),
            "options": json.loads(r["options_json"]), "quality": json.loads(r["quality_json"]),
        })
    return d


def list_articles() -> list[dict]:
    with closing(_connect()) as con:
        return [_row(r, False) for r in con.execute("SELECT * FROM articles ORDER BY id DESC")]


def get_article(article_id: int) -> dict | None:
    with closing(_connect()) as con:
        r = con.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        return _row(r, True) if r else None


def delete_articles(ids: list[int]) -> int:
    if not ids:
        return 0
    with closing(_connect()) as con, con:
        q = ",".join("?" * len(ids))
        return con.execute(f"DELETE FROM articles WHERE id IN ({q})", ids).rowcount
