"""환율·날짜 기준 단가·판매처·부자재 단가이력·DB 마이그레이션 테스트 (가짜 데이터)."""
import sqlite3
import pytest
from pricing import db
from pricing.prices import PriceBook


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()


# ---------------- PriceBook (순수 로직) ----------------
def pb_sample():
    cur = [{"code": "USD", "quote_unit": 1}, {"code": "VND", "quote_unit": 100}]
    fx = [{"id": 1, "currency": "USD", "rate": 1300.0, "rate_date": "2026-01-01"},
          {"id": 2, "currency": "USD", "rate": 1400.0, "rate_date": "2026-03-01"},
          {"id": 3, "currency": "VND", "rate": 5.5, "rate_date": "2026-01-01"}]
    ing = [{"id": 1, "ingredient_id": 1, "price_per_kg": 13000.0, "effective_date": "2026-01-01",
            "currency": "USD", "foreign_price": 10.0, "fx_mode": "auto"},
           {"id": 2, "ingredient_id": 1, "price_per_kg": 14000.0, "effective_date": "2026-05-01",
            "currency": "USD", "foreign_price": 10.0, "fx_mode": "fixed", "fx_fixed_rate": 1500.0},
           {"id": 3, "ingredient_id": 2, "price_per_kg": 9000.0, "effective_date": "2026-02-01",
            "currency": "KRW", "foreign_price": None}]
    mat = [{"id": 1, "material_id": 7, "unit_price": 33.0, "effective_date": "2026-01-01",
            "currency": "VND", "foreign_price": 600.0, "fx_mode": "auto"}]
    return PriceBook(cur, fx, ing, mat)


def test_fx_asof_and_unit_normalization():
    pb = pb_sample()
    assert pb.fx_asof("USD", "2026-02-15") == (1300.0, "2026-01-01")
    assert pb.fx_asof("USD", "2026-03-01") == (1400.0, "2026-03-01")
    assert pb.fx_asof("USD", "2025-12-31") is None
    assert pb.fx_asof("VND", "2026-06-01")[0] == pytest.approx(0.055)      # 100동당 5.5원 → 1동당 0.055원
    assert pb.fx_asof("KRW", "2026-06-01") == (1.0, None)


def test_foreign_auto_follows_fx_daily_and_fixed_does_not():
    pb = pb_sample()
    assert pb.ingredient(1, "2026-02-01")["krw"] == pytest.approx(13000)   # 10달러 × 1300
    assert pb.ingredient(1, "2026-04-01")["krw"] == pytest.approx(14000)   # 환율 1400 반영 (단가는 그대로)
    r = pb.ingredient(1, "2026-06-01")                                      # 고정 환율 행으로 교체
    assert r["krw"] == pytest.approx(15000) and r["fx_mode"] == "fixed" and r["fx"] == 1500.0
    assert pb.ingredient(2, "2026-06-01")["krw"] == 9000
    assert pb.material(7, "2026-06-01")["krw"] == pytest.approx(600 * 0.055)


def test_before_first_and_missing_fx_flags():
    pb = pb_sample()
    r = pb.ingredient(1, "2025-06-01")
    assert r["before_first"] and r["price_date"] == "2026-01-01"
    pb2 = PriceBook([{"code": "USD", "quote_unit": 1}], [],
                    [{"id": 1, "ingredient_id": 1, "price_per_kg": 12345.0, "effective_date": "2026-01-01",
                      "currency": "USD", "foreign_price": 9.0, "fx_mode": "auto"}], [])
    r = pb2.ingredient(1, "2026-02-01")
    assert r["fx_missing"] and r["krw"] == 12345.0          # 환율 이력이 없으면 입력 당시 환산값


def test_same_day_later_row_wins():
    pb = PriceBook([], [], [{"id": 1, "ingredient_id": 1, "price_per_kg": 100.0, "effective_date": "2026-01-01"},
                            {"id": 2, "ingredient_id": 1, "price_per_kg": 120.0, "effective_date": "2026-01-01"}], [])
    assert pb.ingredient(1, "2026-01-01")["krw"] == 120.0


# ---------------- DB ----------------
def seed_fx():
    db.add_fx_rate("USD", 1300, "2026-01-01")
    db.add_fx_rate("USD", 1400, "2026-06-01")
    db.add_fx_rate("VND", 5.5, "2026-01-01")


def test_seed_currencies_and_other_currency(tmpdb):
    codes = {c["code"] for c in db.list_currencies()}
    assert {"KRW", "USD", "VND", "TRY"} <= codes
    db.add_currency("eur", "유로", "유럽연합", 1)                       # (기타) 통화 추가
    assert "EUR" in {c["code"] for c in db.list_currencies()}
    db.add_fx_rate("EUR", 1500, "2026-01-01")
    with pytest.raises(ValueError):
        db.add_currency("EUR", "중복")
    with pytest.raises(ValueError):
        db.add_currency("1", "x")
    with pytest.raises(ValueError):
        db.delete_currency("USD")                                      # 기본 통화는 삭제 불가
    with pytest.raises(ValueError):
        db.delete_currency("EUR")                                      # 환율 이력 있으면 삭제 불가


def test_fx_rate_upsert_same_day_and_validation(tmpdb):
    db.add_fx_rate("USD", 1300, "2026-01-01")
    db.add_fx_rate("USD", 1310, "2026-01-01", "정정")
    rows = db.list_fx_rates("USD")
    assert len(rows) == 1 and rows[0]["rate"] == 1310
    with pytest.raises(ValueError):
        db.add_fx_rate("USD", 0, "2026-01-02")
    with pytest.raises(ValueError):
        db.add_fx_rate("XXX", 10, "2026-01-02")
    with pytest.raises(ValueError):
        db.add_fx_rate("KRW", 1, "2026-01-02")


def test_foreign_price_requires_fx_or_fixed(tmpdb):
    a = db.upsert_ingredient("수입A")
    with pytest.raises(ValueError):
        db.add_price(a, None, "2026-02-01", currency="USD", foreign_price=10)   # 환율 이력 없음
    krw = db.add_price(a, None, "2026-02-01", currency="USD", foreign_price=10,
                       fx_mode="fixed", fx_fixed_rate=1450)
    assert krw == pytest.approx(14500)
    with pytest.raises(ValueError):
        db.add_price(a, None, "2026-02-01", currency="USD", foreign_price=10, fx_mode="fixed")


def seed_product():
    seed_fx()
    a = db.upsert_ingredient("수입아몬드", "미국", "가상", .025, .03, .0054,
                             roasting_cost_per_kg=300, sorting_cost_per_kg=200)
    db.add_price(a, None, "2026-01-01", currency="USD", foreign_price=10)
    h = db.upsert_ingredient("국내호두")
    db.add_price(h, 9000, "2026-01-01")
    m1 = db.upsert_material("수입필름", "roll", None, .03)
    db.add_material_price(m1, None, "2026-01-01", currency="VND", foreign_price=600)
    m2 = db.upsert_material("카톤", "box", 1000, .03)
    pid = db.save_product("제품A", 30, 20, 0, 100, "",
                          [{"ingredient_id": a, "ratio": .5}, {"ingredient_id": h, "ratio": .5}],
                          [{"material_id": m1, "qty": 1, "divisor": 1, "per_bag": True},
                           {"material_id": m2, "qty": 1, "divisor": 10}], three_pl_cost=200)
    return pid, a, m1


def test_quote_as_of_uses_historical_fx(tmpdb):
    pid, a, m1 = seed_product()
    q1, r1 = db.calculate_quote(pid, as_of="2026-03-01")      # 환율 1300
    q2, r2 = db.calculate_quote(pid, as_of="2026-07-01")      # 환율 1400
    ia1 = q1.ingredients[0]; ia2 = q2.ingredients[0]
    assert ia1.price_per_kg == pytest.approx(13000) and ia2.price_per_kg == pytest.approx(14000)
    assert ia1.currency == "USD" and ia1.foreign_price == 10 and ia1.fx_rate == 1300 and ia1.fx_date == "2026-01-01"
    assert r2.direct_cost > r1.direct_cost and r2.price > r1.price
    assert q2.as_of_date == "2026-07-01" and q2.three_pl_cost == 200
    assert q1.ingredients[0].roasting_per_kg == 300 and r1.roasting_cost > 0
    # 부자재: VND 600동 × (100동당 5.5원) = 33원, 봉수(30) 연동
    film = next(x for x in r1.material_rows if x["name"] == "수입필름")
    assert film["qty"] == 30 and film["base"] == pytest.approx(600 * 0.055 * 30)


def test_future_dated_price_not_applied_until_its_date(tmpdb):
    pid, a, _ = seed_product()
    db.add_price(a, None, "2999-01-01", currency="USD", foreign_price=99)
    assert db.calculate_quote(pid)[0].ingredients[0].foreign_price == 10        # 아직 적용 전
    assert db.calculate_quote(pid, as_of="2999-02-01")[0].ingredients[0].foreign_price == 99


def test_quote_notes_for_before_first(tmpdb):
    pid, *_ = seed_product()
    q, r = db.calculate_quote(pid, as_of="2020-01-01")
    assert any("이전 단가 기록이 없어" in w for w in r.warnings)


def test_missing_price_gives_zero_and_note(tmpdb):
    seed_fx()
    a = db.upsert_ingredient("단가없음")
    pid = db.save_product("p", 1, 20, 0, 0, "", [{"ingredient_id": a, "ratio": 1.0}], [])
    q, r = db.calculate_quote(pid)
    assert q.ingredients[0].price_per_kg == 0 and any("단가가 등록되어 있지 않아" in w for w in r.warnings)


def test_price_override_beats_master(tmpdb):
    pid, a, _ = seed_product()
    h = next(i for i in db.list_ingredients() if i["name"] == "국내호두")["id"]
    d = db.get_product_detail(pid)
    db.save_product("제품A", 30, 20, 0, 100, "",
                    [{"ingredient_id": a, "ratio": .5}, {"ingredient_id": h, "ratio": .5, "price_override": 7000}],
                    [], pid, 200)
    q, _ = db.calculate_quote(pid)
    walnut = q.ingredients[1]
    assert walnut.price_per_kg == 7000 and walnut.price_source == "제품 직접입력"


# ---------------- 판매처 ----------------
def test_channel_quote_offline_and_online(tmpdb):
    pid, *_ = seed_product()
    mart = db.upsert_channel({"name": "가상마트", "kind": "offline", "logistics_rate": .03,
                              "logistics_fixed": 100, "margin_rate": .05})
    mall = db.upsert_channel({"name": "가상몰", "kind": "online", "fee_rate": .12, "promo_rate": .02,
                              "event_rate": .01, "event_fixed": 20, "parcel_cost": 3000,
                              "sga_rate": .02, "margin_rate": .04, "online_vat": True})
    base_q, base_r = db.calculate_quote(pid)
    q1, r1 = db.calculate_quote(pid, channel_id=mart)
    assert q1.channel_name == "가상마트" and q1.channel_kind == "offline"
    assert r1.logistics == pytest.approx(r1.price * .03 + 100) and r1.margin == pytest.approx(r1.price * .05)
    q2, r2 = db.calculate_quote(pid, channel_id=mall)
    assert r2.fee == pytest.approx(r2.price * .12 * 1.1) and r2.parcel == 3000
    assert q2.sga_rate == .02 and q2.margin_rate == .04                    # 판매처 설정이 기본값을 덮어씀
    assert r2.price > r1.price > base_r.price
    assert r2.total_cost == pytest.approx(r2.price, abs=1.0)


def test_channel_validation_and_snapshot(tmpdb):
    with pytest.raises(ValueError):
        db.upsert_channel({"name": "", "kind": "offline"})
    with pytest.raises(ValueError):
        db.upsert_channel({"name": "x", "kind": "weird"})
    with pytest.raises(ValueError):
        db.upsert_channel({"name": "x", "kind": "online", "fee_rate": 1.2})
    pid, *_ = seed_product()
    cid = db.upsert_channel({"name": "몰", "kind": "online", "fee_rate": .1})
    q, r = db.calculate_quote(pid, channel_id=cid)
    qid = db.save_quote(q, r, "t")
    db.upsert_channel({"name": "몰", "kind": "online", "fee_rate": .3}, cid)    # 이후 수수료 변경
    q2, r2, meta = db.load_quote(qid)
    assert q2.fee_rate == .1 and q2.channel_name == "몰" and r2.fee == r.fee      # 이력은 그 시점 값 유지


# ---------------- 부자재 단가 이력 ----------------
def test_material_price_history_and_resolution(tmpdb):
    seed_fx()
    m = db.upsert_material("박스", "box", 1000, .03, effective_date="2026-01-01")
    db.upsert_material("박스", "box", 1100, .03, effective_date="2026-04-01")
    db.upsert_material("박스", "box", 1100, .03, effective_date="2026-05-01")      # 같은 가격이면 이력 안 쌓임
    hist = db.material_price_history(m)
    assert [h["unit_price"] for h in hist] == [1100, 1000]
    pb = db.load_pricebook()
    assert pb.material(m, "2026-02-01")["krw"] == 1000 and pb.material(m, "2026-06-01")["krw"] == 1100
    assert next(x for x in db.list_materials() if x["id"] == m)["unit_price"] == 1100


# ---------------- 제품 복사 (30입 → 60입) ----------------
def test_copy_product_rescales_per_bag_items(tmpdb):
    pid, *_ = seed_product()
    new = db.copy_product(pid, "제품A 60입", bag_count=60)
    q30, r30 = db.calculate_quote(pid)
    q60, r60 = db.calculate_quote(new)
    film30 = next(x for x in r30.material_rows if x["name"] == "수입필름")["base"]
    film60 = next(x for x in r60.material_rows if x["name"] == "수입필름")["base"]
    assert film60 == pytest.approx(2 * film30)
    carton30 = next(x for x in r30.material_rows if x["name"] == "카톤")["base"]
    carton60 = next(x for x in r60.material_rows if x["name"] == "카톤")["base"]
    assert carton60 == pytest.approx(carton30)          # 고정 수량은 그대로
    assert q60.three_pl_cost == 200


# ---------------- 마이그레이션 ----------------
def test_migrates_old_database(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, origin TEXT DEFAULT '',
        supplier TEXT DEFAULT '', loss_moisture REAL DEFAULT 0, loss_split REAL DEFAULT 0, loss_sorting REAL DEFAULT 0);
    CREATE TABLE ingredient_prices (id INTEGER PRIMARY KEY AUTOINCREMENT, ingredient_id INTEGER NOT NULL,
        price_per_kg REAL NOT NULL, effective_date TEXT NOT NULL, memo TEXT DEFAULT '');
    CREATE TABLE materials (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, category TEXT NOT NULL,
        unit_price REAL NOT NULL DEFAULT 0, loss_rate REAL NOT NULL DEFAULT 0, memo TEXT DEFAULT '');
    CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, bag_count REAL NOT NULL DEFAULT 1,
        unit_weight_g REAL NOT NULL DEFAULT 0, sorting_cost_per_kg REAL DEFAULT 0, shipping_cost REAL DEFAULT 0, memo TEXT DEFAULT '');
    CREATE TABLE product_ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
        ingredient_id INTEGER NOT NULL, ratio REAL NOT NULL, loss_rate REAL, price_override REAL);
    CREATE TABLE product_materials (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
        material_id INTEGER NOT NULL, qty REAL NOT NULL DEFAULT 1, divisor REAL NOT NULL DEFAULT 1, loss_rate REAL);
    INSERT INTO ingredients(name) VALUES('아몬드');
    INSERT INTO ingredient_prices(ingredient_id,price_per_kg,effective_date) VALUES(1,10000,'2026-01-01');
    INSERT INTO materials(name,category,unit_price,loss_rate) VALUES('카톤','box',1000,0.03);
    INSERT INTO products(name,bag_count,unit_weight_g,shipping_cost) VALUES('옛제품',10,20,100);
    INSERT INTO product_ingredients(product_id,ingredient_id,ratio) VALUES(1,1,1.0);
    INSERT INTO product_materials(product_id,material_id,qty,divisor) VALUES(1,1,1,10);
    """)
    con.commit(); con.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db(); db.init_db()                                   # 두 번 실행해도 안전
    q, r = db.calculate_quote(1)
    assert q.ingredients[0].price_per_kg == 10000 and q.ingredients[0].currency == "KRW"
    assert r.box_cost == pytest.approx(1000 / 10 * 1.03)         # 카톤 1000원 ÷ 입수 10, loss 3%
    assert len(db.material_price_history(1)) == 1                 # 부자재 단가 → 이력 1건으로 이관
    assert {"KRW", "USD", "VND", "TRY"} <= {c["code"] for c in db.list_currencies()}
    assert q.materials[0].per_bag is False                        # 기존 수량은 '고정' 유지 → 숫자 불변


# ---------------- 회귀: 가격 없이 만든 부자재가 0원 자리표시 행으로 실제 단가를 덮어쓰던 버그 ----------------
def test_material_created_without_price_does_not_shadow_backdated_price(tmpdb):
    seed_fx()
    m = db.upsert_material("롤필름", "roll", None, .03)             # 가격 없이 먼저 생성
    assert db.material_price_history(m) == []                       # 0원 자리표시 행이 없어야 한다
    db.add_material_price(m, None, "2026-01-01", currency="USD", foreign_price=0.05)   # 과거 날짜로 단가 입력
    pid = db.save_product("p", 10, 20, 0, 0, "", [],
                          [{"material_id": m, "qty": 1, "divisor": 1, "per_bag": True}])
    q, r = db.calculate_quote(pid)
    assert q.materials[0].unit_price == pytest.approx(0.05 * 1400)
    assert r.roll_cost > 0


def test_material_without_any_price_warns_and_is_zero(tmpdb):
    m = db.upsert_material("가격미정", "etc", None, 0)
    pid = db.save_product("p", 1, 20, 0, 0, "", [], [{"material_id": m, "qty": 1, "divisor": 1}])
    q, r = db.calculate_quote(pid)
    assert r.etc_cost == 0 and any("단가가 등록되어 있지 않아" in w for w in r.warnings)
