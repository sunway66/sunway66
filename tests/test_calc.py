"""纯计算测试，不依赖 AKShare 或网络。

运行：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_data import (  # noqa: E402
    FUNDS,
    build_market_payload,
    build_payload,
    is_split_event,
    main,
    market_bucket_key,
)


class SplitDetectionTests(unittest.TestCase):
    def test_two_for_one_split(self) -> None:
        self.assertTrue(is_split_event(2.0, 0.5))
        self.assertTrue(is_split_event(2.0, 0.525))  # 拆分 + 5% 市场上涨
        self.assertTrue(is_split_event(0.5, 2.0))  # 合并

    def test_large_creation_is_not_split(self) -> None:
        self.assertFalse(is_split_event(1.5, 1.03))
        self.assertFalse(is_split_event(1.8, 1.0))

    def test_normal_move_is_not_split(self) -> None:
        self.assertFalse(is_split_event(1.02, 1.01))


class BuildPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        self.shares = {fund.code: {} for fund in FUNDS}
        self.nav = {fund.code: {} for fund in FUNDS}
        for fund in FUNDS:
            self.shares[fund.code].update(
                {self.dates[0]: 100.0, self.dates[1]: 110.0, self.dates[2]: 111.0}
            )
            self.nav[fund.code].update(
                {self.dates[0]: 2.0, self.dates[1]: 2.1, self.dates[2]: 2.2}
            )

    def test_normal_net_subscription_and_market_value(self) -> None:
        payload = build_payload(
            FUNDS,
            self.dates,
            self.shares,
            self.nav,
            days=180,
            now=datetime(2026, 1, 7, 20, 0),
        )
        series = payload["series"]["510300"]
        self.assertEqual(series["net_subscription"][0], None)
        self.assertEqual(series["net_subscription"][1], 21.0)  # 10 亿份 × 2.1 元
        self.assertEqual(series["market_value"][1], 231.0)  # 110 亿份 × 2.1 元
        self.assertEqual(payload["meta"]["data_date"], "2026-01-07")
        self.assertFalse(payload["meta"]["is_stale"])

    def test_split_day_is_neutralized(self) -> None:
        for fund in FUNDS:
            self.shares[fund.code][self.dates[1]] = 200.0
            self.nav[fund.code][self.dates[1]] = 1.05
        payload = build_payload(
            FUNDS,
            self.dates,
            self.shares,
            self.nav,
            days=180,
            now=datetime(2026, 1, 7, 20, 0),
        )
        series = payload["series"]["510300"]
        self.assertEqual(series["net_subscription"][1], 0.0)
        self.assertEqual(series["flags"][1], "split")
        self.assertTrue(payload["events"])
        self.assertEqual(payload["events"][0]["type"], "split")

    def test_incomplete_latest_day_is_stale(self) -> None:
        self.nav["159919"].pop(self.dates[2])
        payload = build_payload(
            FUNDS,
            self.dates,
            self.shares,
            self.nav,
            days=180,
            now=datetime(2026, 1, 7, 18, 10),
        )
        self.assertEqual(payload["meta"]["data_date"], "2026-01-06")
        self.assertTrue(payload["meta"]["is_stale"])
        self.assertIn("159919", payload["meta"]["missing_latest"]["nav"])
        self.assertEqual(payload["dates"][-1], "2026-01-06")

    def test_no_previous_day_gives_null(self) -> None:
        payload = build_payload(
            FUNDS,
            [self.dates[0]],
            self.shares,
            self.nav,
            days=180,
            now=datetime(2026, 1, 5, 20, 0),
        )
        self.assertIsNone(payload["series"]["510300"]["net_subscription"][0])
        self.assertEqual(payload["series"]["510300"]["flags"][0], "no_prev")

    def test_shares_are_in_yi_units(self) -> None:
        payload = build_payload(
            FUNDS,
            self.dates,
            self.shares,
            self.nav,
            days=180,
            now=datetime(2026, 1, 7, 20, 0),
        )
        self.assertEqual(payload["series"]["510300"]["shares"][0], 100.0)
        self.assertEqual(payload["meta"]["units"]["shares"], "亿份")

    def test_previous_day_buffer_is_saved(self) -> None:
        payload = build_payload(
            FUNDS,
            self.dates,
            self.shares,
            self.nav,
            days=2,
            now=datetime(2026, 1, 7, 20, 0),
        )
        self.assertEqual(payload["dates"], ["2026-01-06", "2026-01-07"])
        self.assertEqual(payload["previous"]["date"], "2026-01-05")
        self.assertEqual(payload["previous"]["shares"]["510300"], 100.0)
        self.assertNotIn("2026-01-05", payload["dates"])


class MarketPayloadTests(unittest.TestCase):
    def test_bucket_boundaries(self) -> None:
        self.assertEqual(market_bucket_key(10.1), "gt10")
        self.assertEqual(market_bucket_key(10.0), "7to10")
        self.assertEqual(market_bucket_key(7.0), "7to10")
        self.assertEqual(market_bucket_key(3.0), "3to7")
        self.assertEqual(market_bucket_key(0.0), "0to3")
        self.assertEqual(market_bucket_key(-0.1), "0to_3")
        self.assertEqual(market_bucket_key(-3.0), "_3to_7")
        self.assertEqual(market_bucket_key(-7.0), "_7to_10")
        self.assertEqual(market_bucket_key(-10.0), "_7to_10")
        self.assertEqual(market_bucket_key(-10.1), "lt_10")

    def test_distribution_and_limit_counts(self) -> None:
        stocks = [
            ("600000", "浦发银行", 10.0, 1_000_000_000),
            ("300001", "特锐德", 20.0, 500_000_000),
            ("688001", "华兴源创", 20.0, 300_000_000),
            ("830001", "艾融软件", 30.0, 100_000_000),
            ("600002", "ST示例", 5.0, 200_000_000),
            ("600003", "示例科技", 9.5, 100_000_000),
            ("600004", "N新股", 200.0, 50_000_000),
            ("000001", "平安银行", -10.0, 800_000_000),
            ("002001", "新和成", -3.0, 100_000_000),
            ("600005", "示例股份", 0.0, 100_000_000),
        ]
        payload = build_market_payload(stocks, date(2026, 11, 4))
        self.assertEqual(payload["total"], 10)
        self.assertEqual(payload["up"], 7)  # 6 只上涨 + 0% 不计入上涨
        self.assertEqual(payload["flat"], 1)
        self.assertEqual(payload["down"], 2)
        self.assertEqual(payload["limit_up"], 5)  # 10/20/20/30/ST5；N 新股排除
        self.assertEqual(payload["limit_down"], 1)
        self.assertEqual(sum(item["count"] for item in payload["distribution"]), 10)
        self.assertAlmostEqual(payload["turnover"], 32.5, places=2)  # 3.25 亿元 * 10

    def test_market_is_embedded_in_payload(self) -> None:
        market = {
            "date": "2026-01-07",
            "total": 1,
            "up": 1,
            "down": 0,
            "flat": 0,
            "distribution": [],
        }
        payload = build_payload(
            FUNDS,
            [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
            {fund.code: {date(2026, 1, 5): 100.0, date(2026, 1, 6): 101.0, date(2026, 1, 7): 102.0} for fund in FUNDS},
            {fund.code: {date(2026, 1, 5): 2.0, date(2026, 1, 6): 2.0, date(2026, 1, 7): 2.0} for fund in FUNDS},
            days=3,
            market=market,
        )
        self.assertEqual(payload["market"]["date"], "2026-01-07")
        self.assertFalse(payload["market"]["is_stale"])

    def test_csi300_risk_premium_formula(self) -> None:
        csi300 = {
            date(2026, 1, 5): {"pe_ttm": 10.0, "bond_yield": 2.0, "index_close": 4000.0},
            date(2026, 1, 6): {"pe_ttm": 12.5, "bond_yield": 1.8, "index_close": 4050.0},
            date(2026, 1, 7): {"pe_ttm": 15.0, "bond_yield": 1.7, "index_close": 4100.0},
        }
        payload = build_payload(
            FUNDS,
            [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
            {fund.code: {date(2026, 1, 5): 100.0, date(2026, 1, 6): 101.0, date(2026, 1, 7): 102.0} for fund in FUNDS},
            {fund.code: {date(2026, 1, 5): 2.0, date(2026, 1, 6): 2.0, date(2026, 1, 7): 2.0} for fund in FUNDS},
            days=3,
            csi300=csi300,
        )
        self.assertEqual(payload["csi300"]["risk_premium"][0], 8.0)
        self.assertEqual(payload["csi300"]["risk_premium"][1], 6.2)
        self.assertEqual(payload["csi300"]["index_close"][-1], 4100.0)


class FetchConcurrencyTests(unittest.TestCase):
    def test_parallel_sse_fetch_keeps_all_dates(self) -> None:
        import pandas as pd
        from unittest.mock import patch

        from fetch_data import fetch_sse_shares

        class FakeAk:
            @staticmethod
            def fund_etf_scale_sse(date: str):
                return pd.DataFrame(
                    {
                        "基金代码": ["510300", "510310", "510330"],
                        "基金份额": [10_000_000_000, 20_000_000_000, 30_000_000_000],
                    }
                )

        days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        with patch("fetch_data._ak", return_value=FakeAk()):
            result = fetch_sse_shares(days)

        self.assertEqual(sorted(result), days)
        self.assertEqual(result[days[0]]["510300"], 100.0)


class MainFlowTests(unittest.TestCase):
    def test_main_flow_with_mocked_sources(self) -> None:
        dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        shares = {
            day: {fund.code: 100.0 + index for fund in FUNDS}
            for index, day in enumerate(dates)
        }
        navs = {
            fund.code: {day: 2.0 + index * 0.01 for index, day in enumerate(dates)}
            for fund in FUNDS
        }

        with (
            patch("fetch_data.get_trade_dates", return_value=dates),
            patch("fetch_data.fetch_sse_shares", return_value=shares),
            patch("fetch_data.fetch_szse_shares", return_value=shares),
            patch("fetch_data.fetch_navs", return_value=navs),
            patch(
                "fetch_data.fetch_market_snapshot",
                return_value={
                    "date": "2026-01-07",
                    "total": 3,
                    "up": 2,
                    "down": 1,
                    "flat": 0,
                    "distribution": [],
                },
            ),
            patch(
                "fetch_data.fetch_csi300_data",
                return_value={
                    date(2026, 1, 5): {"pe_ttm": 10.0, "bond_yield": 2.0, "index_close": 4000.0},
                    date(2026, 1, 6): {"pe_ttm": 11.0, "bond_yield": 2.0, "index_close": 4010.0},
                    date(2026, 1, 7): {"pe_ttm": 12.0, "bond_yield": 2.0, "index_close": 4020.0},
                },
            ),
            patch("fetch_data.write_payload", return_value=True) as writer,
        ):
            code = main(["--output", str(ROOT / "unused-test-output.json"), "--days", "2"])

        self.assertEqual(code, 0)
        writer.assert_called_once()
        payload = writer.call_args.args[1]
        self.assertEqual(len(payload["dates"]), 2)
        self.assertEqual(payload["series"]["510300"]["market_value"][-1], round(102.0 * 2.02, 2))
        self.assertEqual(payload["market"]["total"], 3)


if __name__ == "__main__":
    unittest.main()
