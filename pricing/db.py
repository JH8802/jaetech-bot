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

from .engine import (CATEGORIES, IngredientLine, MaterialLine, QuoteInput, QuoteResult,
                     calc_mode, calculate)
from .prices import KRW, PriceBook

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
CREATE TABLE IF NOT EXISTS currencies (          -- 통화 (미국/베트남/튀르키예 + 기타 직접 추가)
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT DEFAULT '',
    quote_unit REAL NOT NULL DEFAULT 1,            -- 환율 표기 단위 (VND는 100동당 얼마)
    builtin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fx_rates (             -- 환율 이력 (원 / 외화 quote_unit)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    currency TEXT NOT NULL REFERENCES currencies(code) ON DELETE CASCADE,
    rate REAL NOT NULL,
    rate_date TEXT NOT NULL,
    memo TEXT DEFAULT '',
    UNIQUE(currency, rate_date)
);
CREATE TABLE IF NOT EXISTS material_prices (      -- 부자재 단가 이력
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    unit_price REAL NOT NULL,                      -- 원화 단가 (외화 단가는 입력 당시 환산값)
    effective_date TEXT NOT NULL,
    memo TEXT DEFAULT '',
    currency TEXT DEFAULT 'KRW',
    foreign_price REAL,
    fx_mode TEXT DEFAULT 'auto',
    fx_fixed_rate REAL
);
CREATE TABLE IF NOT EXISTS channels (             -- 판매처 (마트별 물류비 / 온라인 업체별 수수료 등)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'offline',          -- offline / online
    logistics_rate REAL DEFAULT 0,
    logistics_fixed REAL DEFAULT 0,
    logistics_vat INTEGER DEFAULT 0,
    fee_rate REAL DEFAULT 0,
    promo_rate REAL DEFAULT 0,
    event_rate REAL DEFAULT 0,
    event_fixed REAL DEFAULT 0,
    parcel_cost REAL DEFAULT 0,
    online_vat INTEGER DEFAULT 0,
    sga_rate REAL,                                 -- NULL이면 기본 설정 사용
    margin_rate REAL,                              -- NULL이면 기본 설정 사용
    memo TEXT DEFAULT ''
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


# 기존 DB에 컬럼을 덧붙이는 마이그레이션 (이미 있으면 건너뜀)
MIGRATIONS = {
    "ingredients": {"roasting_cost_per_kg": "REAL DEFAULT 0", "sorting_cost_per_kg": "REAL DEFAULT 0"},
    "ingredient_prices": {"currency": "TEXT DEFAULT 'KRW'", "foreign_price": "REAL",
                          "fx_mode": "TEXT DEFAULT 'auto'", "fx_fixed_rate": "REAL"},
    "products": {"three_pl_cost": "REAL DEFAULT 0"},
    "product_materials": {"qty_basis": "TEXT DEFAULT 'fixed'"},
    "currencies": {"symbol": "TEXT DEFAULT ''"},
}

SEED_CURRENCIES = [                       # code, 이름, 국가, 표기단위, 기호
    ("KRW", "원", "대한민국", 1, "₩"),
    ("USD", "미국 달러", "미국", 1, "$"),
    ("VND", "베트남 동", "베트남", 100, "₫"),
    ("TRY", "튀르키예 리라", "튀르키예", 1, "₺"),
]


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        for code, name, country, unit, symbol in SEED_CURRENCIES:
            con.execute("""INSERT OR IGNORE INTO currencies(code,name,country,quote_unit,builtin,symbol)
                           VALUES(?,?,?,?,1,?)""", (code, name, country, unit, symbol))
            con.execute("UPDATE currencies SET symbol=? WHERE code=? AND (symbol IS NULL OR symbol='')",
                        (symbol, code))
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        # 예전 버전(단가 이력 없이 단가 1개만 있던 부자재)을 이력 1건으로 이관 (단가가 있는 것만)
        con.execute("""INSERT INTO material_prices(material_id,unit_price,effective_date,memo)
                       SELECT m.id, m.unit_price, ?, '초기 이관' FROM materials m
                       WHERE m.unit_price > 0
                         AND NOT EXISTS (SELECT 1 FROM material_prices x WHERE x.material_id=m.id)""",
                    (date.today().isoformat(),))


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


# ---------------- 통화 / 환율 ----------------
def list_currencies(include_krw: bool = True) -> list[dict]:
    with connect() as con:
        rows = [dict(r) for r in con.execute(
            """SELECT * FROM currencies ORDER BY
               CASE code WHEN 'KRW' THEN 0 WHEN 'USD' THEN 1 WHEN 'VND' THEN 2 WHEN 'TRY' THEN 3 ELSE 4 END, code""")]
    return rows if include_krw else [r for r in rows if r["code"] != KRW]


def currency_symbol(c: dict) -> str:
    return (c.get("symbol") or "").strip() or c["code"]


def currency_label(c: dict) -> str:
    """화면 표시용. 기본 통화: '미국 ($)', (기타) 통화: '(기타) 유럽연합 (€)'"""
    country = c["country"] or c["name"]
    tag = "" if c["builtin"] else "(기타) "
    return f"{tag}{country} ({currency_symbol(c)})"


def add_currency(code: str, name: str, country: str = "", quote_unit: float = 1.0, symbol: str = "") -> None:
    """(기타) 통화 추가. 예: EUR / 유로 / 유럽연합 / 1 / €"""
    code = code.strip().upper()
    if not code.isalnum() or not 2 <= len(code) <= 6:
        raise ValueError("통화 코드는 영문/숫자 2~6자로 입력하세요 (예: EUR, CNY, AUD)")
    if not name.strip():
        raise ValueError("통화 이름을 입력하세요")
    if quote_unit <= 0:
        raise ValueError("환율 표기 단위는 0보다 커야 합니다")
    with connect() as con:
        if con.execute("SELECT 1 FROM currencies WHERE code=?", (code,)).fetchone():
            raise ValueError(f"이미 등록된 통화입니다: {code}")
        con.execute("""INSERT INTO currencies(code,name,country,quote_unit,builtin,symbol)
                       VALUES(?,?,?,?,0,?)""",
                    (code, name.strip(), country.strip(), quote_unit, symbol.strip()))


def delete_currency(code: str) -> None:
    with connect() as con:
        row = con.execute("SELECT builtin FROM currencies WHERE code=?", (code,)).fetchone()
        if row is None:
            return
        if row["builtin"]:
            raise ValueError("기본 통화(원·미국·베트남·튀르키예)는 삭제할 수 없습니다")
        used = (con.execute("SELECT 1 FROM ingredient_prices WHERE currency=? LIMIT 1", (code,)).fetchone()
                or con.execute("SELECT 1 FROM material_prices WHERE currency=? LIMIT 1", (code,)).fetchone()
                or con.execute("SELECT 1 FROM fx_rates WHERE currency=? LIMIT 1", (code,)).fetchone())
        if used:
            raise ValueError("환율 또는 단가 이력에서 사용 중인 통화는 삭제할 수 없습니다")
        con.execute("DELETE FROM currencies WHERE code=?", (code,))


def add_fx_rate(currency: str, rate: float, rate_date: str, memo: str = "") -> None:
    """같은 통화·같은 날짜가 있으면 덮어쓴다. rate = 원 / 외화 quote_unit."""
    if rate <= 0:
        raise ValueError("환율은 0보다 커야 합니다")
    with connect() as con:
        if not con.execute("SELECT 1 FROM currencies WHERE code=?", (currency,)).fetchone():
            raise ValueError(f"등록되지 않은 통화입니다: {currency}")
        if currency == KRW:
            raise ValueError("원화(KRW)는 환율을 입력하지 않습니다")
        con.execute("""INSERT INTO fx_rates(currency,rate,rate_date,memo) VALUES(?,?,?,?)
                       ON CONFLICT(currency,rate_date) DO UPDATE SET rate=excluded.rate, memo=excluded.memo""",
                    (currency, rate, rate_date, memo))


def list_fx_rates(currency: str | None = None, d_from: str | None = None,
                  d_to: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM fx_rates WHERE 1=1", []
    if currency:
        sql += " AND currency=?"; args.append(currency)
    if d_from:
        sql += " AND rate_date>=?"; args.append(d_from)
    if d_to:
        sql += " AND rate_date<=?"; args.append(d_to)
    with connect() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY rate_date DESC, currency", args)]


def delete_fx_rate(fx_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM fx_rates WHERE id=?", (fx_id,))


def load_pricebook() -> PriceBook:
    """날짜 기준 단가·환율 조회기. 한 번 읽어 두고 여러 날짜를 빠르게 계산할 때 쓴다."""
    with connect() as con:
        cur = [dict(r) for r in con.execute("SELECT * FROM currencies")]
        fx = [dict(r) for r in con.execute("SELECT * FROM fx_rates")]
        ing = [dict(r) for r in con.execute("SELECT * FROM ingredient_prices")]
        mat = [dict(r) for r in con.execute("SELECT * FROM material_prices")]
    return PriceBook(cur, fx, ing, mat)


def _snapshot_krw(con, currency, foreign, effective_date, fx_mode, fx_fixed_rate):
    """외화 단가를 입력 시점의 원화로 환산 (환율 이력이 아직 없는 날짜의 대비용 스냅샷)."""
    unit = con.execute("SELECT quote_unit FROM currencies WHERE code=?", (currency,)).fetchone()
    if unit is None:
        raise ValueError(f"등록되지 않은 통화입니다: {currency}")
    if fx_mode == "fixed":
        if not fx_fixed_rate or fx_fixed_rate <= 0:
            raise ValueError("고정 환율을 입력하세요")
        return foreign * fx_fixed_rate / unit["quote_unit"]
    row = con.execute("""SELECT rate FROM fx_rates WHERE currency=? AND rate_date<=?
                         ORDER BY rate_date DESC LIMIT 1""", (currency, effective_date)).fetchone()
    if row is None:
        raise ValueError(f"{currency} 환율 이력이 {effective_date} 이전에 없습니다. "
                         f"'환율' 메뉴에서 먼저 환율을 등록하거나 '고정 환율'을 선택하세요")
    return foreign * row["rate"] / unit["quote_unit"]


def _price_args(con, price, effective_date, currency, foreign_price, fx_mode, fx_fixed_rate):
    """단가 행에 저장할 (원화 스냅샷, 통화, 외화단가, 환율방식, 고정환율) 결정."""
    if currency and currency != KRW and foreign_price is not None:
        if foreign_price < 0:
            raise ValueError("단가는 음수일 수 없습니다")
        krw = _snapshot_krw(con, currency, foreign_price, effective_date, fx_mode, fx_fixed_rate)
        return krw, currency, foreign_price, fx_mode, (fx_fixed_rate if fx_mode == "fixed" else None)
    if price is None or price < 0:
        raise ValueError("단가를 입력하세요 (음수 불가)")
    return price, KRW, None, "auto", None


# ---------------- 원료 ----------------
def _today() -> str:
    return date.today().isoformat()


def list_ingredients(day: str | None = None) -> list[dict]:
    """원료 + day(기본 오늘) 기준 단가. 외화 단가는 환율을 적용한 원화 값이 price_per_kg."""
    day = day or _today()
    pb = load_pricebook()
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM ingredients ORDER BY name")]
    for r in rows:
        res = pb.ingredient(r["id"], day)
        r.update(price_per_kg=None, price_date=None, currency=KRW, foreign_price=None, fx=None, fx_date=None,
                 fx_mode=None, fx_fixed_rate=None)
        if res:
            r.update(price_per_kg=res["krw"], price_date=res["price_date"], currency=res["currency"],
                     foreign_price=res["foreign"], fx=res["fx"], fx_date=res["fx_date"],
                     fx_mode=res["fx_mode"], fx_fixed_rate=res["fx_fixed_rate"])
    return rows


def upsert_ingredient(name, origin="", supplier="", loss_moisture=0.0,
                      loss_split=0.0, loss_sorting=0.0, roasting_cost_per_kg=0.0,
                      sorting_cost_per_kg=0.0) -> int:
    with connect() as con:
        con.execute("""INSERT INTO ingredients(name,origin,supplier,loss_moisture,loss_split,loss_sorting,
                                               roasting_cost_per_kg,sorting_cost_per_kg)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET origin=excluded.origin,
                         supplier=excluded.supplier, loss_moisture=excluded.loss_moisture,
                         loss_split=excluded.loss_split, loss_sorting=excluded.loss_sorting,
                         roasting_cost_per_kg=excluded.roasting_cost_per_kg,
                         sorting_cost_per_kg=excluded.sorting_cost_per_kg""",
                    (name, origin, supplier, loss_moisture, loss_split, loss_sorting,
                     roasting_cost_per_kg, sorting_cost_per_kg))
        return con.execute("SELECT id FROM ingredients WHERE name=?", (name,)).fetchone()["id"]


def delete_ingredient(ingredient_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM ingredients WHERE id=?", (ingredient_id,))


def add_price(ingredient_id: int, price_per_kg: float | None, effective_date: str, memo="",
              currency: str = KRW, foreign_price: float | None = None,
              fx_mode: str = "auto", fx_fixed_rate: float | None = None) -> float:
    """원료 단가 추가. 원화는 price_per_kg, 외화는 currency+foreign_price(+환율방식)로 입력.
    같은 날짜에 이미 있으면 새 행이 우선한다. 원화 환산 스냅샷 값을 돌려준다."""
    with connect() as con:
        krw, cur, foreign, mode, fixed = _price_args(
            con, price_per_kg, effective_date, currency, foreign_price, fx_mode, fx_fixed_rate)
        con.execute("""INSERT INTO ingredient_prices(ingredient_id,price_per_kg,effective_date,memo,
                                                     currency,foreign_price,fx_mode,fx_fixed_rate)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (ingredient_id, krw, effective_date, memo, cur, foreign, mode, fixed))
    return krw


def price_history(ingredient_id: int) -> list[dict]:
    with connect() as con:
        rows = con.execute("""SELECT * FROM ingredient_prices
                              WHERE ingredient_id=? ORDER BY effective_date DESC, id DESC""",
                           (ingredient_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_price(price_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM ingredient_prices WHERE id=?", (price_id,))


def list_ingredient_prices_all() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("""
            SELECT p.*, i.name AS name FROM ingredient_prices p JOIN ingredients i ON i.id=p.ingredient_id
            ORDER BY i.name, p.effective_date, p.id""")]


# ---------------- 부자재 ----------------
def list_materials(day: str | None = None) -> list[dict]:
    """부자재 + day(기본 오늘) 기준 단가. unit_price 는 환율 적용 후 원화 값."""
    day = day or _today()
    pb = load_pricebook()
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM materials ORDER BY category, name")]
    for r in rows:
        res = pb.material(r["id"], day)
        r.update(price_date=None, currency=KRW, foreign_price=None, fx=None, fx_date=None,
                 fx_mode=None, fx_fixed_rate=None)
        if res:
            r.update(unit_price=res["krw"], price_date=res["price_date"], currency=res["currency"],
                     foreign_price=res["foreign"], fx=res["fx"], fx_date=res["fx_date"],
                     fx_mode=res["fx_mode"], fx_fixed_rate=res["fx_fixed_rate"])
    return rows


def _insert_material_price(con, material_id, unit_price, effective_date, memo, currency,
                           foreign_price, fx_mode, fx_fixed_rate) -> float:
    krw, cur, foreign, mode, fixed = _price_args(
        con, unit_price, effective_date, currency, foreign_price, fx_mode, fx_fixed_rate)
    con.execute("""INSERT INTO material_prices(material_id,unit_price,effective_date,memo,
                                               currency,foreign_price,fx_mode,fx_fixed_rate)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (material_id, krw, effective_date, memo, cur, foreign, mode, fixed))
    latest = con.execute("""SELECT unit_price FROM material_prices WHERE material_id=?
                            ORDER BY effective_date DESC, id DESC LIMIT 1""", (material_id,)).fetchone()
    con.execute("UPDATE materials SET unit_price=? WHERE id=?", (latest["unit_price"], material_id))
    return krw


def upsert_material(name, category, unit_price=None, loss_rate=0.0, memo="",
                    effective_date: str | None = None) -> int:
    """부자재 등록/수정. unit_price(원화)를 주면 현재 단가와 다를 때만 단가 이력에 추가한다.
    외화 단가 등은 add_material_price 로 입력한다."""
    with connect() as con:
        con.execute("""INSERT INTO materials(name,category,unit_price,loss_rate,memo)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET category=excluded.category,
                         loss_rate=excluded.loss_rate, memo=excluded.memo""",
                    (name, category, unit_price or 0.0, loss_rate, memo))
        mid = con.execute("SELECT id FROM materials WHERE name=?", (name,)).fetchone()["id"]
        has = con.execute("SELECT 1 FROM material_prices WHERE material_id=? LIMIT 1", (mid,)).fetchone()
        if unit_price is not None:
            cur = con.execute("""SELECT unit_price, currency FROM material_prices WHERE material_id=?
                                 ORDER BY effective_date DESC, id DESC LIMIT 1""", (mid,)).fetchone()
            if not has or cur["currency"] != KRW or abs(cur["unit_price"] - unit_price) > 1e-9:
                _insert_material_price(con, mid, unit_price, effective_date or _today(), "",
                                       KRW, None, "auto", None)
    return mid


def add_material_price(material_id: int, unit_price: float | None, effective_date: str, memo="",
                       currency: str = KRW, foreign_price: float | None = None,
                       fx_mode: str = "auto", fx_fixed_rate: float | None = None) -> float:
    with connect() as con:
        return _insert_material_price(con, material_id, unit_price, effective_date, memo,
                                      currency, foreign_price, fx_mode, fx_fixed_rate)


def material_price_history(material_id: int) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("""SELECT * FROM material_prices WHERE material_id=?
                                                ORDER BY effective_date DESC, id DESC""", (material_id,))]


def delete_material_price(price_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM material_prices WHERE id=?", (price_id,))


def list_material_prices_all() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("""
            SELECT p.*, m.name AS name, m.category AS category FROM material_prices p
            JOIN materials m ON m.id=p.material_id ORDER BY m.name, p.effective_date, p.id""")]


def delete_material(material_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM materials WHERE id=?", (material_id,))


# ---------------- 판매처 (마트 / 온라인 업체) ----------------
CHANNEL_FIELDS = ("name", "kind", "logistics_rate", "logistics_fixed", "logistics_vat", "fee_rate",
                  "promo_rate", "event_rate", "event_fixed", "parcel_cost", "online_vat",
                  "sga_rate", "margin_rate", "memo")


def list_channels() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM channels ORDER BY kind, name")]


def get_channel(channel_id: int) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
    return dict(r) if r else None


def upsert_channel(data: dict, channel_id: int | None = None) -> int:
    vals = {k: data.get(k) for k in CHANNEL_FIELDS}
    if not (vals["name"] or "").strip():
        raise ValueError("판매처 이름을 입력하세요")
    if vals["kind"] not in ("offline", "online"):
        raise ValueError("판매처 유형은 offline/online 이어야 합니다")
    for k in ("logistics_rate", "fee_rate", "promo_rate", "event_rate", "sga_rate", "margin_rate"):
        v = vals[k]
        if v is not None and not 0 <= v < 1:
            raise ValueError(f"{k}: 비율은 0 이상 100% 미만이어야 합니다")
    for k in ("logistics_vat", "online_vat"):
        vals[k] = 1 if vals[k] else 0
    for k in ("logistics_rate", "logistics_fixed", "fee_rate", "promo_rate", "event_rate",
              "event_fixed", "parcel_cost"):
        vals[k] = vals[k] or 0.0
    vals["name"] = vals["name"].strip()
    with connect() as con:
        if channel_id is None:
            cur = con.execute(f"INSERT INTO channels({','.join(CHANNEL_FIELDS)}) "
                              f"VALUES({','.join('?' * len(CHANNEL_FIELDS))})",
                              [vals[k] for k in CHANNEL_FIELDS])
            return cur.lastrowid
        sets = ",".join(f"{k}=?" for k in CHANNEL_FIELDS)
        con.execute(f"UPDATE channels SET {sets} WHERE id=?", [vals[k] for k in CHANNEL_FIELDS] + [channel_id])
        return channel_id


def delete_channel(channel_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM channels WHERE id=?", (channel_id,))


# ---------------- 제품 ----------------
def list_products() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM products ORDER BY name")]


def save_product(name, bag_count, unit_weight_g, sorting_cost_per_kg, shipping_cost,
                 memo, ingredient_rows: list[dict], material_rows: list[dict],
                 product_id: int | None = None, three_pl_cost: float = 0.0) -> int:
    """ingredient_rows: {ingredient_id, ratio, loss_rate|None, price_override|None}
       material_rows:   {material_id, qty, divisor, loss_rate|None, per_bag(bool)}"""
    with connect() as con:
        if product_id is None:
            cur = con.execute("""INSERT INTO products(name,bag_count,unit_weight_g,
                                 sorting_cost_per_kg,shipping_cost,memo,three_pl_cost)
                                 VALUES(?,?,?,?,?,?,?)""",
                              (name, bag_count, unit_weight_g, sorting_cost_per_kg, shipping_cost, memo,
                               three_pl_cost))
            product_id = cur.lastrowid
        else:
            con.execute("""UPDATE products SET name=?,bag_count=?,unit_weight_g=?,
                           sorting_cost_per_kg=?,shipping_cost=?,memo=?,three_pl_cost=? WHERE id=?""",
                        (name, bag_count, unit_weight_g, sorting_cost_per_kg, shipping_cost, memo,
                         three_pl_cost, product_id))
            con.execute("DELETE FROM product_ingredients WHERE product_id=?", (product_id,))
            con.execute("DELETE FROM product_materials WHERE product_id=?", (product_id,))
        for r in ingredient_rows:
            con.execute("""INSERT INTO product_ingredients(product_id,ingredient_id,ratio,loss_rate,price_override)
                           VALUES(?,?,?,?,?)""",
                        (product_id, r["ingredient_id"], r["ratio"], r.get("loss_rate"), r.get("price_override")))
        for r in material_rows:
            con.execute("""INSERT INTO product_materials(product_id,material_id,qty,divisor,loss_rate,qty_basis)
                           VALUES(?,?,?,?,?,?)""",
                        (product_id, r["material_id"], r["qty"], r["divisor"], r.get("loss_rate"),
                         "bag" if r.get("per_bag") else "fixed"))
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
                   i.roasting_cost_per_kg, i.sorting_cost_per_kg AS ing_sorting_cost_per_kg
            FROM product_ingredients pi JOIN ingredients i ON i.id=pi.ingredient_id
            WHERE pi.product_id=? ORDER BY pi.id""", (product_id,))]
        p["materials"] = [dict(r) for r in con.execute("""
            SELECT pm.*, m.name, m.category, m.unit_price, m.loss_rate AS master_loss
            FROM product_materials pm JOIN materials m ON m.id=pm.material_id
            WHERE pm.product_id=? ORDER BY pm.id""", (product_id,))]
    return p


def copy_product(product_id: int, new_name: str, bag_count: float | None = None,
                 unit_weight_g: float | None = None) -> int:
    """제품을 복사해 새 제품 생성 (예: 30입 → 60입). 봉수 연동 부자재는 새 봉수로 자동 계산된다."""
    d = get_product_detail(product_id)
    ing = [{"ingredient_id": r["ingredient_id"], "ratio": r["ratio"], "loss_rate": r["loss_rate"],
            "price_override": r["price_override"]} for r in d["ingredients"]]
    mat = [{"material_id": r["material_id"], "qty": r["qty"], "divisor": r["divisor"],
            "loss_rate": r["loss_rate"], "per_bag": r["qty_basis"] == "bag"} for r in d["materials"]]
    return save_product(new_name, bag_count if bag_count is not None else d["bag_count"],
                        unit_weight_g if unit_weight_g is not None else d["unit_weight_g"],
                        d["sorting_cost_per_kg"], d["shipping_cost"], d["memo"] or "", ing, mat,
                        None, d.get("three_pl_cost") or 0.0)


# ---------------- 견적 입력 조립 ----------------
def assemble_quote(detail: dict, settings: dict, channel: dict | None, pb: PriceBook, day: str,
                   fixed_price: float | None = None) -> QuoteInput:
    """제품 상세 + 설정 + 판매처 + day 기준 단가/환율 → 계산용 입력 (DB를 다시 읽지 않는다)."""
    notes: list[str] = []
    ings = []
    for r in detail["ingredients"]:
        loss = r["loss_rate"] if r["loss_rate"] is not None else r["master_loss"]
        common = dict(origin=r["origin"] or "", supplier=r["supplier"] or "",
                      roasting_per_kg=r["roasting_cost_per_kg"] or 0.0,
                      sorting_per_kg=r["ing_sorting_cost_per_kg"] or 0.0)
        if r["price_override"] is not None:
            ings.append(IngredientLine(r["name"], r["ratio"], r["price_override"], loss,
                                       price_source="제품 직접입력", **common))
            continue
        res = pb.ingredient(r["ingredient_id"], day)
        if res is None:
            notes.append(f"원료 '{r['name']}' 단가가 등록되어 있지 않아 0원으로 계산했습니다")
            ings.append(IngredientLine(r["name"], r["ratio"], 0.0, loss, price_source="단가 없음", **common))
            continue
        if res["before_first"]:
            notes.append(f"원료 '{r['name']}': 기준일({day}) 이전 단가 기록이 없어 가장 오래된 단가를 적용했습니다")
        if res["fx_missing"]:
            notes.append(f"원료 '{r['name']}': {res['currency']} 환율 이력이 없어 입력 당시 환산값을 적용했습니다")
        ings.append(IngredientLine(
            r["name"], r["ratio"], res["krw"], loss, price_date=res["price_date"],
            price_source="마스터 단가", currency=res["currency"], foreign_price=res["foreign"],
            fx_rate=res["fx"], fx_date=res["fx_date"] or "", **common))
    mats = []
    for r in detail["materials"]:
        loss = r["loss_rate"] if r["loss_rate"] is not None else r["master_loss"]
        res = pb.material(r["material_id"], day)
        per_bag = r.get("qty_basis") == "bag"
        if res is None:
            if not r["unit_price"]:
                notes.append(f"부자재 '{r['name']}' 단가가 등록되어 있지 않아 0원으로 계산했습니다")
            mats.append(MaterialLine(r["name"], r["category"], r["unit_price"], r["qty"], r["divisor"],
                                     loss, per_bag))
            continue
        if res["before_first"]:
            notes.append(f"부자재 '{r['name']}': 기준일({day}) 이전 단가 기록이 없어 가장 오래된 단가를 적용했습니다")
        if res["fx_missing"]:
            notes.append(f"부자재 '{r['name']}': {res['currency']} 환율 이력이 없어 입력 당시 환산값을 적용했습니다")
        mats.append(MaterialLine(
            r["name"], r["category"], res["krw"], r["qty"], r["divisor"], loss, per_bag,
            price_date=res["price_date"], currency=res["currency"], foreign_price=res["foreign"],
            fx_rate=res["fx"], fx_date=res["fx_date"] or ""))

    sga = settings["sga_rate"] if settings["use_sga"] else 0.0
    margin = settings["margin_rate"] if settings["use_margin"] else 0.0
    extra = {}
    if channel is None:
        log_rate = settings["logistics_rate"] if settings["use_logistics"] else 0.0
        log_vat = settings["logistics_vat"]
    else:
        if channel["sga_rate"] is not None:
            sga = channel["sga_rate"]
        if channel["margin_rate"] is not None:
            margin = channel["margin_rate"]
        log_rate, log_vat = channel["logistics_rate"] or 0.0, bool(channel["logistics_vat"])
        extra = dict(channel_name=channel["name"], channel_kind=channel["kind"],
                     logistics_fixed=channel["logistics_fixed"] or 0.0, fee_rate=channel["fee_rate"] or 0.0,
                     promo_rate=channel["promo_rate"] or 0.0, event_rate=channel["event_rate"] or 0.0,
                     event_fixed=channel["event_fixed"] or 0.0, parcel_cost=channel["parcel_cost"] or 0.0,
                     online_vat=bool(channel["online_vat"]))
    return QuoteInput(
        product_name=detail["name"], bag_count=detail["bag_count"], unit_weight_g=detail["unit_weight_g"],
        ingredients=ings, materials=mats,
        sorting_cost_per_kg=detail["sorting_cost_per_kg"] or 0.0, shipping_cost=detail["shipping_cost"] or 0.0,
        three_pl_cost=detail.get("three_pl_cost") or 0.0,
        sga_rate=sga, margin_rate=margin, logistics_rate=log_rate, logistics_vat=log_vat,
        rounding=settings["rounding"], fixed_price=fixed_price, as_of_date=day, input_notes=notes, **extra)


def build_quote_input(product_id: int, settings: dict | None = None,
                      fixed_price: float | None = None, channel_id: int | None = None,
                      as_of: str | None = None, pb: PriceBook | None = None) -> QuoteInput:
    """제품 + as_of(기본 오늘) 기준 단가·환율 + 설정 + 판매처를 합쳐 계산용 입력을 만든다."""
    s = settings or get_settings()
    channel = get_channel(channel_id) if channel_id else None
    return assemble_quote(get_product_detail(product_id), s, channel, pb or load_pricebook(),
                          as_of or _today(), fixed_price)


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


def calculate_quote(product_id: int, fixed_price: float | None = None,
                    channel_id: int | None = None, as_of: str | None = None):
    q = build_quote_input(product_id, fixed_price=fixed_price, channel_id=channel_id, as_of=as_of)
    return q, calculate(q)


# ---------------- 엑셀 일괄 등록 ----------------
_ING_FIELDS = ("origin", "supplier", "loss_moisture", "loss_split", "loss_sorting",
               "roasting_cost_per_kg", "sorting_cost_per_kg")
_ING_LABEL = {"origin": "원산지", "supplier": "공급처", "loss_moisture": "수분loss",
              "loss_split": "소분loss", "loss_sorting": "선별loss",
              "roasting_cost_per_kg": "로스팅비", "sorting_cost_per_kg": "선별비"}


def _n(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def _fmt_field(f: str, v) -> str:
    if f.startswith("loss"):
        return f"{(v or 0) * 100:.2f}%"
    if f.endswith("per_kg"):
        return _n(v or 0)
    return str(v) if v else "(없음)"


def _same(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return (a or "") == (b or "")
    return abs((a or 0.0) - (b or 0.0)) < 1e-9


_PRICE_TABLES = {  # 단가 이력 테이블 설정: (테이블, 품목 컬럼, 원화 컬럼)
    "ingredient": ("ingredient_prices", "ingredient_id", "price_per_kg"),
    "material": ("material_prices", "material_id", "unit_price"),
}


def _apply_price(con, kind: str, item_id: int, row: dict, price_key: str, today: str):
    """엑셀 행의 단가(원화 또는 외화)를 단가 이력에 반영. 반영했으면 설명 문자열, 아니면 None."""
    table, id_col, krw_col = _PRICE_TABLES[kind]
    cur = (row.get("currency") or KRW)
    foreign = row.get("foreign_price") if cur != KRW else None
    krw_in = row.get(price_key)
    if foreign is None and krw_in is None:
        return None
    d = row.get("date") or today
    fixed = row.get("fx_fixed") if foreign is not None else None
    mode = "fixed" if fixed else "auto"

    def same_def(r) -> bool:                      # 이력 행이 이번 입력과 같은 정의인가
        if foreign is not None:
            return (r["currency"] == cur and _same(r["foreign_price"], foreign) and (r["fx_mode"] or "auto") == mode
                    and (not fixed or _same(r["fx_fixed_rate"], fixed)))
        return (r["currency"] or KRW) == KRW and r["foreign_price"] is None and _same(r[krw_col], krw_in)

    # 그 날짜(d) 시점에 유효한 단가가 이미 같은 정의라면 변경 없음 (재업로드·중복 줄에도 안전)
    last = con.execute(f"""SELECT * FROM {table} WHERE {id_col}=? AND effective_date<=?
                           ORDER BY effective_date DESC, id DESC LIMIT 1""", (item_id, d)).fetchone()
    if last is not None and same_def(last):
        return None
    krw, cur2, foreign2, mode2, fixed2 = _price_args(con, krw_in, d, cur, foreign, mode, fixed)
    con.execute(f"""INSERT INTO {table}({id_col},{krw_col},effective_date,memo,currency,foreign_price,
                                        fx_mode,fx_fixed_rate) VALUES(?,?,?,?,?,?,?,?)""",
                (item_id, krw, d, row.get("memo") or "", cur2, foreign2, mode2, fixed2))
    if kind == "material":
        latest = con.execute("""SELECT unit_price FROM material_prices WHERE material_id=?
                                ORDER BY effective_date DESC, id DESC LIMIT 1""", (item_id,)).fetchone()
        con.execute("UPDATE materials SET unit_price=? WHERE id=?", (latest["unit_price"], item_id))

    def show(r_cur, r_foreign, r_krw) -> str:
        return f"{_n(r_foreign)} {r_cur}" if r_foreign is not None else _n(r_krw)
    old = "" if last is None else show(last["currency"], last["foreign_price"], last[krw_col]) + "→"
    new = show(cur2, foreign2, krw)
    fx_note = " [고정환율]" if mode2 == "fixed" else ""
    return f"단가 {old}{new}{fx_note} ({d})"


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
                """INSERT INTO ingredients(name,origin,supplier,loss_moisture,loss_split,loss_sorting,
                                           roasting_cost_per_kg,sorting_cost_per_kg)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (name, *[vals[f] for f in _ING_FIELDS])).lastrowid
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
        price_note = _apply_price(con, "ingredient", cid, row, "price", today)
        if price_note:
            notes.append(price_note)
            if status == "변경없음":
                status = "수정"
        out.update(status=status, detail=" / ".join(notes) or "변경 없음")
    except Exception as e:
        out.update(status="오류", detail=str(e))
    return out


def _apply_material(con, row: dict, today: str) -> dict:
    name = row["name"]
    out = {"kind": "부자재", "name": name, "src": row.get("src", "")}
    try:
        cur = con.execute("SELECT * FROM materials WHERE name=?", (name,)).fetchone()
        notes = []
        if cur is None:
            if not row.get("category"):
                raise ValueError("신규 부자재는 '분류'(롤포장지/포장지/인케이스/카톤박스/소분비/기타)가 필요합니다")
            mid = con.execute("""INSERT INTO materials(name,category,unit_price,loss_rate,memo)
                                 VALUES(?,?,0,?,?)""",
                              (name, row["category"], row.get("loss_rate") or 0.0, row.get("memo") or "")).lastrowid
            status = "신규"
            notes.append("부자재 신규")
            has_price = row.get("unit_price") is not None or row.get("foreign_price") is not None
            if not has_price:
                notes[-1] += " (단가 미입력 — 단가를 따로 추가하세요)"
        else:
            mid, status = cur["id"], "변경없음"
            for f, label in (("category", "분류"), ("loss_rate", "loss"), ("memo", "메모")):
                v = row.get(f)
                if v is None or _same(v, cur[f]):
                    continue
                con.execute(f"UPDATE materials SET {f}=? WHERE id=?", (v, mid))
                if f == "loss_rate":
                    notes.append(f"loss {cur[f] * 100:.2f}%→{v * 100:.2f}%")
                elif f == "category":
                    notes.append(f"분류 {CATEGORIES.get(cur[f], cur[f])}→{CATEGORIES.get(v, v)}")
                else:
                    notes.append(label + " 변경")
                status = "수정"
        price_note = _apply_price(con, "material", mid, row, "unit_price", today)
        if price_note:
            notes.append(price_note)
            if status == "변경없음":
                status = "수정"
        out.update(status=status, detail=" / ".join(notes) or "변경 없음")
    except Exception as e:
        out.update(status="오류", detail=str(e))
    return out


def _apply_fx(con, row: dict) -> dict:
    cur, d, rate = row["currency"], row["date"], row["rate"]
    out = {"kind": "환율", "name": f"{cur} {d}", "src": row.get("src", "")}
    try:
        if con.execute("SELECT 1 FROM currencies WHERE code=?", (cur,)).fetchone() is None:
            raise ValueError(f"등록되지 않은 통화입니다: {cur} — '환율' 메뉴에서 (기타) 통화로 먼저 추가하세요")
        if cur == KRW:
            raise ValueError("원화(KRW)는 환율을 입력하지 않습니다")
        old = con.execute("SELECT rate, memo FROM fx_rates WHERE currency=? AND rate_date=?", (cur, d)).fetchone()
        if old is None:
            con.execute("INSERT INTO fx_rates(currency,rate,rate_date,memo) VALUES(?,?,?,?)",
                        (cur, rate, d, row.get("memo") or ""))
            out.update(status="신규", detail=f"환율 {rate:,.4f}")
        elif abs(old["rate"] - rate) < 1e-12:
            out.update(status="변경없음", detail="변경 없음")
        else:
            con.execute("UPDATE fx_rates SET rate=?, memo=COALESCE(?, memo) WHERE currency=? AND rate_date=?",
                        (rate, row.get("memo"), cur, d))
            out.update(status="수정", detail=f"환율 {old['rate']:,.4f}→{rate:,.4f}")
    except Exception as e:
        out.update(status="오류", detail=str(e))
    return out


def bulk_apply(ingredients: list[dict], materials: list[dict], fx_rates: list[dict] | None = None,
               dry_run: bool = False, today: str | None = None) -> list[dict]:
    """환율 → 원료 → 부자재 순으로 이름(·통화·날짜) 기준 신규 등록/수정 (엑셀 일괄 등록용).
    비어 있는 칸(None)은 기존 값을 그대로 둔다. 하나라도 오류가 있으면 전부 취소(rollback)."""
    today = today or date.today().isoformat()
    results = []
    with connect() as con:
        for r in fx_rates or []:
            results.append(_apply_fx(con, r))
        for r in ingredients:
            results.append(_apply_ingredient(con, r, today))
        for r in materials:
            results.append(_apply_material(con, r, today))
        if dry_run or any(r["status"] == "오류" for r in results):
            con.rollback()
    return results


# ---------------- 전체 데이터 (엑셀 백업용) ----------------
def collect_all_data(include_quotes: bool = True) -> dict:
    """모든 마스터·이력 데이터를 표 형태(dict of list)로 모은다. (견적 이력은 무거우니 필요할 때만)"""
    with connect() as con:
        ingredients = [dict(r) for r in con.execute("SELECT * FROM ingredients ORDER BY name")]
        materials = [dict(r) for r in con.execute("SELECT * FROM materials ORDER BY category, name")]
        currencies = [dict(r) for r in con.execute("SELECT * FROM currencies ORDER BY builtin DESC, code")]
        products = [dict(r) for r in con.execute("SELECT * FROM products ORDER BY name")]
        bom_ing = [dict(r) for r in con.execute("""
            SELECT p.name AS product, i.name AS item, pi.ratio, pi.loss_rate, pi.price_override
            FROM product_ingredients pi JOIN products p ON p.id=pi.product_id
            JOIN ingredients i ON i.id=pi.ingredient_id ORDER BY p.name, pi.id""")]
        bom_mat = [dict(r) for r in con.execute("""
            SELECT p.name AS product, m.name AS item, m.category, pm.qty, pm.divisor, pm.qty_basis, pm.loss_rate
            FROM product_materials pm JOIN products p ON p.id=pm.product_id
            JOIN materials m ON m.id=pm.material_id ORDER BY p.name, pm.id""")]
    return {
        "ingredients": list_ingredients(), "materials": list_materials(),
        "ingredient_prices": list_ingredient_prices_all(), "material_prices": list_material_prices_all(),
        "fx_rates": sorted(list_fx_rates(), key=lambda r: (r["currency"], r["rate_date"])),
        "currencies": currencies, "channels": list_channels(), "products": products,
        "bom_ingredients": bom_ing, "bom_materials": bom_mat,
        "quotes": [(q, r, m) for q, r, m in search_quotes()] if include_quotes else [],
    }
