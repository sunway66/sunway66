"""生成用于界面预览的演示 data.json。

注意：这不是真实行情。GitHub Actions 首次运行会用真实数据覆盖它。
"""

from __future__ import annotations

import base64
import json
import random
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_data import FUNDS, build_payload  # noqa: E402

# 2026-11-04 收盘后的真实单位净值（用于让演示数据看起来接近现实）。
END_NAV = {
    "510300": 4.1785,
    "510310": 4.0609,
    "510330": 4.3583,
    "159919": 4.3628,
}

# 由 2026-09-30 净资产规模 / 11-04 净值估算的份额（亿份）。
END_SHARES = {
    "510300": 1068.79 / 4.1785,
    "510310": 517.89 / 4.0609,
    "510330": 393.08 / 4.3583,
    "159919": 317.63 / 4.3628,
}

END_DATE = date(2026, 11, 4)
TRADE_DATES = [item.date() for item in pd.bdate_range(end=END_DATE, periods=1251)]


def make_fund_series(code: str, seed: int) -> tuple[list[float], list[float]]:
    rng = random.Random(seed)
    count = len(TRADE_DATES)

    raw = [1.0]
    for _ in range(1, count):
        raw.append(raw[-1] * (1 + rng.gauss(0.00025, 0.0085)))
    factor = END_NAV[code] / raw[-1]
    nav = [round(value * factor, 4) for value in raw]

    sigma = 5.0 if code == "510300" else 2.6
    net = [0.0] * count
    for index in range(1, count):
        value = rng.gauss(0.15, sigma)
        if rng.random() < 0.07:
            value += rng.choice([-1, 1]) * rng.uniform(9, 22)
        net[index] = value

    shares = [0.0] * count
    shares[-1] = END_SHARES[code]
    for index in range(count - 1, 0, -1):
        shares[index - 1] = shares[index] - net[index] / nav[index]

    # 保证起点为正，并让份额曲线有温和的趋势。
    shift = max(0.0, 8.0 - min(shares))
    shares = [value + shift for value in shares]
    return [round(value, 4) for value in shares], nav


def make_market_snapshot() -> dict:
    counts = [38, 96, 486, 2500, 1700, 420, 100, 20]
    labels = [">10%", "7%~10%", "3%~7%", "0~3%", "0~-3%", "-3%~-7%", "-7%~-10%", "<-10%"]
    keys = ["gt10", "7to10", "3to7", "0to3", "0to_3", "_3to_7", "_7to_10", "lt_10"]
    sides = ["up", "up", "up", "up", "down", "down", "down", "down"]
    return {
        "date": END_DATE.isoformat(),
        "as_of": "2026-11-04T20:30:00+08:00",
        "is_stale": False,
        "total": sum(counts),
        "up": 3060,
        "down": 2240,
        "flat": 60,
        "limit_up": 72,
        "limit_down": 8,
        "turnover": 19876.54,
        "turnover_sh": 8500.20,
        "turnover_sz": 10500.30,
        "turnover_bj": 876.04,
        "distribution": [
            {"key": key, "label": label, "side": side, "count": count}
            for key, label, side, count in zip(keys, labels, sides, counts)
        ],
        "source": "演示数据 · 东方财富 A 股行情（AKShare stock_zh_a_spot_em）",
        "limit_note": "涨停/跌停按板块涨跌停幅度与收盘涨跌幅统计，已排除 N/C 开头新股",
    }


def make_csi300_series() -> dict[date, dict[str, float]]:
    rng = random.Random(20261104)
    result: dict[date, dict[str, float]] = {}
    pe = 14.2
    bond = 1.85
    close = 3900.0
    for index, item_date in enumerate(TRADE_DATES):
        pe = max(9.0, min(18.0, pe + rng.gauss(0, 0.04)))
        bond = max(1.2, min(3.2, bond + rng.gauss(0, 0.006)))
        close = max(2800.0, close * (1 + rng.gauss(0.0002, 0.008)))
        result[item_date] = {
            "pe_ttm": round(pe, 2),
            "bond_yield": round(bond, 4),
            "index_close": round(close, 2),
        }
    return result


def main() -> None:
    shares_map: dict[str, dict[date, float]] = {}
    nav_map: dict[str, dict[date, float]] = {}
    for index, fund in enumerate(FUNDS):
        shares, nav = make_fund_series(fund.code, seed=20261104 + index)
        shares_map[fund.code] = dict(zip(TRADE_DATES, shares))
        nav_map[fund.code] = dict(zip(TRADE_DATES, nav))

    payload = build_payload(
        FUNDS,
        TRADE_DATES,
        shares_map,
        nav_map,
        days=1250,
        now=datetime(2026, 11, 4, 20, 30, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")),
        demo=True,
        market=make_market_snapshot(),
        csi300=make_csi300_series(),
    )
    payload["meta"]["latest_trade_date"] = END_DATE.isoformat()
    payload["meta"]["is_stale"] = False
    payload["meta"]["stale_reason"] = None
    payload["meta"]["missing_latest"] = {"shares": [], "nav": []}
    payload["meta"]["source"] = "演示数据（非真实行情）· 正式数据由上交所/深交所份额与东方财富净值生成"
    payload["meta"]["disclaimer"] = "当前为界面预览用演示数据，不是真实行情，不构成任何投资建议。"
    payload["events"] = []

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if "--base64" in sys.argv:
        print(base64.b64encode(text.encode("utf-8")).decode("ascii"))
    else:
        print(text)


if __name__ == "__main__":
    main()
