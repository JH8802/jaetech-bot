"""SQLite 저장소. DB 파일은 pricing/data/pricing.db (git 제외).

환경변수 PRICING_DB 로 DB 파일 위치를 바꿀 수 있다.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .engine import (IngredientLine, MaterialLine, QuoteInput, QuoteResult,
                     calc_mode, calculate)

DB_PATH = Path(os.environ.get(
    "PRICING_DB", Path(__file__).resolve().parent / "data" / "pricing.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingredients (          -- 원료 마스터
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    origin TEXT DEFAULT '',
    supplier TEXT DEFAULT '',
    loss_moisture REAL DEFAULT 0,                  -- 수분 loss
    loss_split REAL DEFAULT 0,                     -- 소분 loss
    loss_sorting REAL DEFAULT 0                    -- 선별 loss
);
CREATE TABLE IF NOT EXISTS ingredient_prices (    -- 원료 단가 이력
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    price_per_kg REAL NOT NULL,
    effective_date TEXT NOT NULL,
    memo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS materials (            -- 부자재 마스터
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,                        -- pack / split / box
    unit_price REAL NOT NULL DEFAULT 0,
    loss_rate REAL NOT NULL DEFAULT 0,
    memo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS products (             -- 제품
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    bag_count REAL NOT NULL DEFAULT 1,
    unit_weight_g REAL NOT NULL DEFAULT 0,
    sorting_cost_per_kg REAL DEFAULT 0,
    shipping_cost REAL DEFAULT 0,
    memo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS product_ingredients (  -- 제품 배합표
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    ratio REAL NOT NULL,
    loss_rate REAL,                                -- NULL이면 원료 마스터의 loss 합계 사용
    price_override REAL                            -- NULL이면 최신 단가 사용
);
CREATE TABLE IF NOT EXISTS product_materials (    -- 제품 부자재
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    qty REAL NOT NULL DEFAULT 1,
    divisor REAL NOT NULL DEFAULT 1,
    loss_rate REAL                                 -- NULL이면 부자재 마스터 loss 사용
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes (               -- 견적 스냅샷 (그 시점 입력/결과 그대로 보존)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT DEFAULT '',
    memo TEXT DEFAULT '',
    price REAL NOT NULL,
    input_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (            -- 삭제·권한 변경 기록
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    user TEXT DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT DEFAULT ''
);
"""

# 판관비/물류비/마진은 '선택 사항' -> 기본값은 모두 꺼짐
DEFAULT_SETTINGS = {
    "use_sga": "1", "sga_rate": "0.05",
    "use_logistics": "0", "logistics_rate": "0.0275", "logistics_vat": "0",
    "use_margin": "0", "margin_rate": "0.05",
    "rounding": "round",
    "allow_quote_delete": "0",          # 견적 이력 삭제 잠금 (기본: 삭제 불가)
}


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")   # 여러 명이 동시에 조회해도 안전
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


# ---------------- 설정 ----------------
def get_settings() -> dict:
    with connect() as con:
        rows = con.execute("SELECT key,value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    return {
        "use_sga": s["use_sga"] == "1", "sga_rate": float(s["sga_rate"]),
        "use_logistics": s["use_logistics"] == "1",
        "logistics_rate": float(s["logistics_rate"]),
        "logistics_vat": s["logistics_vat"] == "1",
        "use_margin": s["use_margin"] == "1", "margin_rate": float(s["margin_rate"]),
        "rounding": s["rounding"],
        "allow_quote_delete": s["allow_quote_delete"] == "1",
    }


def save_settings(s: dict) -> None:
    with connect() as con:
        for k, v in s.items():
            v = ("1" if v else "0") if isinstance(v, bool) else str(v)
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))


# ---------------- 원료 ----------------
def list_ingredients() -> list[dict]:
    """원료 + 최신 단가."""
    with connect() as con:
        rows = con.execute("""
            SELECT i.*, (SELECT price_per_kg FROM ingredient_prices p
                          WHERE p.ingredient_id=i.id
                          ORDER BY effective_date DESC, id DESC LIMIT 1) AS price_per_kg,
                        (SELECT effective_date FROM ingredient_prices p
                          WHERE p.ingredient_id=i.id
                          ORDER BY effective_date DESC, id DESC LIMIT 1) AS price_date
            FROM ingredients i ORDER BY i.name""").fetchall()
    return [dict(r) for r in rows]


def upsert_ingredient(name, origin="", supplier="", loss_moisture=0.0,
                      loss_split=0.0, loss_sorting=0.0) -> int:
    with connect() as con:
        con.execute("""INSERT INTO ingredients(name,origin,supplier,loss_moisture,loss_split,loss_sorting)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET origin=excluded.origin,
                         supplier=excluded.supplier, loss_moisture=excluded.loss_moisture,
                         loss_split=excluded.loss_split, loss_sorting=excluded.loss_sorting""",
                    (name, origin, supplier, loss_moisture, loss_split, loss_sorting))
        return con.execute("SELECT id FROM ingredients WHERE name=?", (name,)).fetchone()["id"]


def delete_ingredient(ingredient_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM ingredients WHERE id=?", (ingredient_id,))


def add_price(ingredient_id: int, price_per_kg: float, effective_date: str, memo="") -> None:
    with connect() as con:
        con.execute("""INSERT INTO ingredient_prices(ingredient_id,price_per_kg,effective_date,memo)
                       VALUES(?,?,?,?)""", (ingredient_id, price_per_kg, effective_date, memo))


def price_history(ingredient_id: int) -> list[dict]:
    with connect() as con:
        rows = con.execute("""SELECT effective_date, price_per_kg, memo FROM ingredient_prices
                              WHERE ingredient_id=? ORDER BY effective_date DESC, id DESC""",
                           (ingredient_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------------- 부자재 ----------------
def list_materials() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM materials ORDER BY category, name")]


def upsert_material(name, category, unit_price, loss_rate=0.0, memo="") -> int:
    with connect() as con:
        con.execute("""INSERT INTO materials(name,category,unit_price,loss_rate,memo)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET category=excluded.category,
                         unit_price=excluded.unit_price, loss_rate=excluded.loss_rate,
                         memo=excluded.memo""",
                    (name, category, unit_price, loss_rate, memo))
        return con.execute("SELECT id FROM materials WHERE name=?", (name,)).fetchone()["id"]


def delete_material(material_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM materials WHERE id=?", (material_id,))


# ---------------- 제품 ----------------
def list_products() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM products ORDER BY name")]


def save_product(name, bag_count, unit_weight_g, sorting_cost_per_kg, shipping_cost,
                 memo, ingredient_rows: list[dict], material_rows: list[dict],
                 product_id: int | None = None) -> int:
    """ingredient_rows: {ingredient_id, ratio, loss_rate|None, price_override|None}
       material_rows:   {material_id, qty, divisor, loss_rate|None}"""
    with connect() as con:
        if product_id is None:
            cur = con.execute("""INSERT INTO products(name,bag_count,unit_weight_g,
                                 sorting_cost_per_kg,shipping_cost,memo) VALUES(?,?,?,?,?,?)""",
                              (name, bag_count, unit_weight_g, sorting_cost_per_kg, shipping_cost, memo))
            product_id = cur.lastrowid
        else:
            con.execute("""UPDATE products SET name=?,bag_count=?,unit_weight_g=?,
                           sorting_cost_per_kg=?,shipping_cost=?,memo=? WHERE id=?""",
                        (name, bag_count, unit_weight_g, sorting_cost_per_kg, shipping_cost, memo, product_id))
            con.execute("DELETE FROM product_ingredients WHERE product_id=?", (product_id,))
            con.execute("DELETE FROM product_materials WHERE product_id=?", (product_id,))
        for r in ingredient_rows:
            con.execute("""INSERT INTO product_ingredients(product_id,ingredient_id,ratio,loss_rate,price_override)
                           VALUES(?,?,?,?,?)""",
                        (product_id, r["ingredient_id"], r["ratio"], r.get("loss_rate"), r.get("price_override")))
        for r in material_rows:
            con.execute("""INSERT INTO product_materials(product_id,material_id,qty,divisor,loss_rate)
                           VALUES(?,?,?,?,?)""",
                        (product_id, r["material_id"], r["qty"], r["divisor"], r.get("loss_rate")))
    return product_id


def delete_product(product_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM products WHERE id=?", (product_id,))


def get_product_detail(product_id: int) -> dict:
    with connect() as con:
        p = dict(con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
        p["ingredients"] = [dict(r) for r in con.execute("""
            SELECT pi.*, i.name, i.origin, i.supplier,
                   i.loss_moisture+i.loss_split+i.loss_sorting AS master_loss,
                   (SELECT price_per_kg FROM ingredient_prices x WHERE x.ingredient_id=i.id
                    ORDER BY effective_date DESC, id DESC LIMIT 1) AS latest_price,
                   (SELECT effective_date FROM ingredient_prices x WHERE x.ingredient_id=i.id
                    ORDER BY effective_date DESC, id DESC LIMIT 1) AS latest_price_date
            FROM product_ingredients pi JOIN ingredients i ON i.id=pi.ingredient_id
            WHERE pi.product_id=? ORDER BY pi.id""", (product_id,))]
        p["materials"] = [dict(r) for r in con.execute("""
            SELECT pm.*, m.name, m.category, m.unit_price, m.loss_rate AS master_loss
            FROM product_materials pm JOIN materials m ON m.id=pm.material_id
            WHERE pm.product_id=? ORDER BY pm.id""", (product_id,))]
    return p


def build_quote_input(product_id: int, settings: dict | None = None,
                      fixed_price: float | None = None) -> QuoteInput:
    """제품 + 최신 단가 + 설정을 합쳐 계산용 입력을 만든다."""
    s = settings or get_settings()
    p = get_product_detail(product_id)
    ings = []
    for r in p["ingredients"]:
        override = r["price_override"] is not None
        price = r["price_override"] if override else (r["latest_price"] or 0.0)
        loss = r["loss_rate"] if r["loss_rate"] is not None else r["master_loss"]
        ings.append(IngredientLine(
            r["name"], r["ratio"], price, loss,
            origin=r["origin"] or "", supplier=r["supplier"] or "",
            price_date="" if override else (r["latest_price_date"] or ""),
            price_source="제품 직접입력" if override else "마스터 최신단가"))
    mats = []
    for r in p["materials"]:
        loss = r["loss_rate"] if r["loss_rate"] is not None else r["master_loss"]
        mats.append(MaterialLine(r["name"], r["category"], r["unit_price"], r["qty"], r["divisor"], loss))
    return QuoteInput(
        product_name=p["name"], bag_count=p["bag_count"], unit_weight_g=p["unit_weight_g"],
        ingredients=ings, materials=mats,
        sorting_cost_per_kg=p["sorting_cost_per_kg"], shipping_cost=p["shipping_cost"],
        sga_rate=s["sga_rate"] if s["use_sga"] else 0.0,
        margin_rate=s["margin_rate"] if s["use_margin"] else 0.0,
        logistics_rate=s["logistics_rate"] if s["use_logistics"] else 0.0,
        logistics_vat=s["logistics_vat"], rounding=s["rounding"], fixed_price=fixed_price)


# ---------------- 견적 이력 ----------------
def save_quote(q: QuoteInput, r: QuoteResult, created_by="", memo="") -> int:
    from dataclasses import asdict
    with connect() as con:
        cur = con.execute("""INSERT INTO quotes(product_name,created_at,created_by,memo,price,input_json,result_json)
                             VALUES(?,?,?,?,?,?,?)""",
                          (q.product_name, datetime.now().strftime("%Y-%m-%d %H:%M"), created_by, memo,
                           r.price, json.dumps(asdict(q), ensure_ascii=False),
                           json.dumps(r.to_dict(), ensure_ascii=False)))
        return cur.lastrowid


def _row_to_quote(row) -> tuple[QuoteInput, QuoteResult, dict]:
    d = json.loads(row["input_json"])
    q = QuoteInput(**{**d,
                      "ingredients": [IngredientLine(**x) for x in d["ingredients"]],
                      "materials": [MaterialLine(**x) for x in d["materials"]]})
    # 저장된 결과를 그대로 복원 (스냅샷). 예전 이력에 없는 새 필드는 기본값으로 채워진다.
    r = QuoteResult(**json.loads(row["result_json"]))
    meta = {k: row[k] for k in ("id", "created_at", "created_by", "product_name", "price", "memo")}
    meta["mode"] = calc_mode(q)
    return q, r, meta


def list_quotes(limit=200) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(
            """SELECT id,created_at,created_by,product_name,price,memo FROM quotes
               ORDER BY id DESC LIMIT ?""", (limit,))]


def search_quotes(date_from: str | None = None, date_to: str | None = None,
                  products: list[str] | None = None, users: list[str] | None = None,
                  modes: list[str] | None = None, limit: int | None = None
                  ) -> list[tuple[QuoteInput, QuoteResult, dict]]:
    """조건에 맞는 견적을 (입력, 결과, 메타) 로 반환 (최신순). 날짜는 'YYYY-MM-DD'."""
    sql, args = "SELECT * FROM quotes WHERE 1=1", []
    if date_from:
        sql += " AND created_at >= ?"
        args.append(date_from + " 00:00")
    if date_to:
        sql += " AND created_at <= ?"
        args.append(date_to + " 23:59")
    if products:
        sql += f" AND product_name IN ({','.join('?' * len(products))})"
        args += products
    if users:
        sql += f" AND created_by IN ({','.join('?' * len(users))})"
        args += users
    sql += " ORDER BY id DESC"
    with connect() as con:
        rows = con.execute(sql, args).fetchall()
    out = [_row_to_quote(r) for r in rows]
    if modes:
        out = [x for x in out if x[2]["mode"] in modes]
    return out[:limit] if limit else out


def quote_filter_options() -> dict:
    with connect() as con:
        prods = [r[0] for r in con.execute("SELECT DISTINCT product_name FROM quotes ORDER BY 1")]
        users = [r[0] for r in con.execute("SELECT DISTINCT created_by FROM quotes ORDER BY 1")]
    return {"products": prods, "users": [u for u in users if u]}


def load_quote(quote_id: int) -> tuple[QuoteInput, QuoteResult, dict]:
    with connect() as con:
        row = con.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
    return _row_to_quote(row)


def log_audit(action: str, detail: str = "", user: str = "") -> None:
    with connect() as con:
        con.execute("INSERT INTO audit_log(at,user,action,detail) VALUES(?,?,?,?)",
                    (datetime.now().strftime("%Y-%m-%d %H:%M"), user, action, detail))


def list_audit(limit=100) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT at,user,action,detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


def delete_quote(quote_id: int, user: str = "") -> None:
    """견적 이력 삭제. 설정에서 '삭제 허용'을 켜지 않으면 거부하고, 삭제하면 기록을 남긴다."""
    if not get_settings()["allow_quote_delete"]:
        raise PermissionError("견적 이력 삭제가 잠겨 있습니다 (설정에서 허용해야 합니다)")
    q, r, meta = load_quote(quote_id)
    with connect() as con:
        con.execute("DELETE FROM quotes WHERE id=?", (quote_id,))
    log_audit("견적 삭제", f"#{quote_id} {q.product_name} / 납품가 {r.price:,.0f}원 / "
                         f"작성 {meta['created_by']} {meta['created_at']}", user)


def calculate_quote(product_id: int, fixed_price: float | None = None):
    q = build_quote_input(product_id, fixed_price=fixed_price)
    return q, calculate(q)


# ---------------- 엑셀 일괄 등록 ----------------
_ING_FIELDS = ("origin", "supplier", "loss_moisture", "loss_split", "loss_sorting")
_ING_LABEL = {"origin": "원산지", "supplier": "공급처", "loss_moisture": "수분loss",
              "loss_split": "소분loss", "loss_sorting": "선별loss"}


def _n(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def _fmt_field(f: str, v) -> str:
    if f.startswith("loss"):
        return f"{(v or 0) * 100:.2f}%"
    return str(v) if v else "(없음)"


def _same(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return (a or "") == (b or "")
    return abs((a or 0.0) - (b or 0.0)) < 1e-9


def _apply_ingredient(con, row: dict, today: str) -> dict:
    name = row["name"]
    out = {"kind": "원료", "name": name, "src": row.get("src", "")}
    try:
        cur = con.execute("SELECT * FROM ingredients WHERE name=?", (name,)).fetchone()
        notes = []
        if cur is None:
            vals = {f: (row.get(f) if row.get(f) is not None else ("" if f in ("origin", "supplier") else 0.0))
                    for f in _ING_FIELDS}
            cid = con.execute(
                """INSERT INTO ingredients(name,origin,supplier,loss_moisture,loss_split,loss_sorting)
                   VALUES(?,?,?,?,?,?)""",
                (name, vals["origin"], vals["supplier"], vals["loss_moisture"],
                 vals["loss_split"], vals["loss_sorting"])).lastrowid
            status = "신규"
            notes.append("원료 신규")
        else:
            cid, status = cur["id"], "변경없음"
            for f in _ING_FIELDS:
                v = row.get(f)
                if v is None or _same(v, cur[f]):
                    continue
                con.execute(f"UPDATE ingredients SET {f}=? WHERE id=?", (v, cid))
                notes.append(f"{_ING_LABEL[f]} {_fmt_field(f, cur[f])}→{_fmt_field(f, v)}")
                status = "수정"

        price = row.get("price")
        if price is not None:
            given = row.get("date")
            d = given or today
            last = con.execute("""SELECT price_per_kg, effective_date FROM ingredient_prices
                                  WHERE ingredient_id=? ORDER BY effective_date DESC, id DESC LIMIT 1""",
                               (cid,)).fetchone()
            dup = con.execute("""SELECT 1 FROM ingredient_prices WHERE ingredient_id=?
                                 AND effective_date=? AND ABS(price_per_kg-?)<1e-9""",
                              (cid, d, price)).fetchone()
            unchanged = last is not None and _same(last["price_per_kg"], price) and d >= last["effective_date"]
            if not dup and not unchanged:
                con.execute("""INSERT INTO ingredient_prices(ingredient_id,price_per_kg,effective_date,memo)
                               VALUES(?,?,?,?)""", (cid, price, d, row.get("memo") or ""))
                old = "" if last is None else f"{_n(last['price_per_kg'])}→"
                notes.append(f"단가 {old}{_n(price)} ({d})")
                if status == "변경없음":
                    status = "수정"
        out.update(status=status, detail=" / ".join(notes) or "변경 없음")
    except Exception as e:
        out.update(status="오류", detail=str(e))
    return out


def _apply_material(con, row: dict) -> dict:
    name = row["name"]
    out = {"kind": "부자재", "name": name, "src": row.get("src", "")}
    try:
        cur = con.execute("SELECT * FROM materials WHERE name=?", (name,)).fetchone()
        notes = []
        if cur is None:
            if not row.get("category"):
                raise ValueError("신규 부자재는 '분류'(포장지/소분비/박스비)가 필요합니다")
            price = row.get("unit_price")
            con.execute("""INSERT INTO materials(name,category,unit_price,loss_rate,memo)
                           VALUES(?,?,?,?,?)""",
                        (name, row["category"], price or 0.0, row.get("loss_rate") or 0.0,
                         row.get("memo") or ""))
            status = "신규"
            notes.append("부자재 신규" + ("" if price is not None else " (단가 미입력 → 0)"))
        else:
            status = "변경없음"
            for f, label in (("category", "분류"), ("unit_price", "단가"),
                             ("loss_rate", "loss"), ("memo", "메모")):
                v = row.get(f)
                if v is None or _same(v, cur[f]):
                    continue
                con.execute(f"UPDATE materials SET {f}=? WHERE id=?", (v, cur["id"]))
                if f == "unit_price":
                    notes.append(f"단가 {_n(cur[f])}→{_n(v)}")
                elif f == "loss_rate":
                    notes.append(f"loss {cur[f] * 100:.2f}%→{v * 100:.2f}%")
                elif f == "category":
                    notes.append(f"분류 {cur[f]}→{v}")
                else:
                    notes.append(label + " 변경")
                status = "수정"
        out.update(status=status, detail=" / ".join(notes) or "변경 없음")
    except Exception as e:
        out.update(status="오류", detail=str(e))
    return out


def bulk_apply(ingredients: list[dict], materials: list[dict], dry_run: bool = False,
               today: str | None = None) -> list[dict]:
    """원료/부자재를 이름 기준으로 신규 등록 또는 수정한다 (엑셀 일괄 등록용).
    비어 있는 칸(None)은 기존 값을 그대로 둔다. 하나라도 오류가 있으면 전부 취소(rollback)."""
    today = today or date.today().isoformat()
    results = []
    with connect() as con:
        for r in ingredients:
            results.append(_apply_ingredient(con, r, today))
        for r in materials:
            results.append(_apply_material(con, r))
        if dry_run or any(r["status"] == "오류" for r in results):
            con.rollback()
    return results
