"""날짜 기준(as-of) 단가·환율 해석. DB와 무관한 순수 로직 (db.load_pricebook 이 데이터를 채워 준다).

용어
  단가 행(price row) : 원료/부자재의 '적용일' 별 단가 기록
      KRW 행   : krw(원화 단가)만 있음
      외화 행  : currency + foreign_price(외화 단가) [+ fx_mode / fx_fixed_rate]
                 fx_mode='auto'  → 그 날짜의 환율 이력(as-of)으로 매일 원화 환산
                 fx_mode='fixed' → 행에 적어 둔 고정 환율(계약환율 등)로 환산
  환율               : '원 / 외화 quote_unit 단위' 로 저장 (예: VND는 100동당 5.5원).
                       이 모듈의 함수는 항상 '원 / 외화 1단위' 로 정규화해서 돌려준다.
"""
from __future__ import annotations

from bisect import bisect_right

KRW = "KRW"


class PriceBook:
    def __init__(self, currencies: list[dict], fx_rows: list[dict],
                 ingredient_rows: list[dict], material_rows: list[dict]):
        self.unit = {c["code"]: (c.get("quote_unit") or 1.0) for c in currencies}
        self.unit[KRW] = 1.0
        self.names = {c["code"]: c.get("name", c["code"]) for c in currencies}
        # 환율: 통화 -> (날짜 리스트, 환율 리스트[quote_unit 기준])
        self._fx: dict[str, tuple[list[str], list[float]]] = {}
        by_cur: dict[str, list[dict]] = {}
        for r in fx_rows:
            by_cur.setdefault(r["currency"], []).append(r)
        for cur, rows in by_cur.items():
            rows.sort(key=lambda r: (r["rate_date"], r.get("id", 0)))
            self._fx[cur] = ([r["rate_date"] for r in rows], [r["rate"] for r in rows])
        self._ing = self._group(ingredient_rows, "ingredient_id", "price_per_kg")
        self._mat = self._group(material_rows, "material_id", "unit_price")

    @staticmethod
    def _group(rows, id_key, krw_key):
        out: dict[int, list[dict]] = {}
        for r in rows:
            r = dict(r)
            r["krw"] = r[krw_key]
            out.setdefault(r[id_key], []).append(r)
        for lst in out.values():
            lst.sort(key=lambda r: (r["effective_date"], r.get("id", 0)))
        return out

    # ------------------------------------------------------------ 환율
    def fx_asof(self, currency: str, day: str):
        """(원/외화 1단위, 환율 기준일) 또는 None."""
        if currency == KRW:
            return 1.0, None
        dates_rates = self._fx.get(currency)
        if not dates_rates:
            return None
        dates, rates = dates_rates
        i = bisect_right(dates, day) - 1
        if i < 0:
            return None
        return rates[i] / self.unit.get(currency, 1.0), dates[i]

    def has_fx(self, currency: str) -> bool:
        return currency == KRW or currency in self._fx

    def fx_dates(self, currency: str) -> list[str]:
        return list(self._fx.get(currency, ([], []))[0])

    # ------------------------------------------------------------ 단가
    def resolve(self, row: dict, day: str) -> dict:
        """단가 행 하나를 day 시점의 원화 단가로 환산."""
        cur = row.get("currency") or KRW
        foreign = row.get("foreign_price")
        out = {"krw": row["krw"], "currency": cur, "foreign": None, "fx": None, "fx_date": None,
               "fx_mode": None, "fx_fixed_rate": None, "price_date": row["effective_date"],
               "fx_missing": False}
        if cur == KRW or foreign is None:
            return out
        out["foreign"] = foreign
        mode = row.get("fx_mode") or "auto"
        out["fx_mode"] = mode
        if mode == "fixed" and row.get("fx_fixed_rate"):
            fx = row["fx_fixed_rate"] / self.unit.get(cur, 1.0)
            out.update(krw=foreign * fx, fx=fx, fx_date="고정", fx_fixed_rate=row["fx_fixed_rate"])
            return out
        found = self.fx_asof(cur, day)
        if found is None:
            out["fx_missing"] = True          # 환율 이력이 없으면 입력 당시 원화 환산값을 쓴다
            return out
        fx, fx_date = found
        out.update(krw=foreign * fx, fx=fx, fx_date=fx_date)
        return out

    def _asof(self, rows: list[dict] | None, day: str):
        if not rows:
            return None, False
        dates = [r["effective_date"] for r in rows]
        i = bisect_right(dates, day) - 1
        if i >= 0:
            return rows[i], False
        return rows[0], True                  # 기준일 이전 기록이 없으면 가장 오래된 단가 + 경고

    def _item(self, table, item_id: int, day: str):
        row, before_first = self._asof(table.get(item_id), day)
        if row is None:
            return None
        res = self.resolve(row, day)
        res["before_first"] = before_first
        res["memo"] = row.get("memo", "")
        return res

    def ingredient(self, ingredient_id: int, day: str):
        return self._item(self._ing, ingredient_id, day)

    def material(self, material_id: int, day: str):
        return self._item(self._mat, material_id, day)

    def rows(self, kind: str, item_id: int) -> list[dict]:
        table = self._ing if kind == "ingredient" else self._mat
        return list(table.get(item_id, []))

    def item_ids(self, kind: str) -> list[int]:
        return list((self._ing if kind == "ingredient" else self._mat).keys())
