#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 4 只沪深 300ETF 的每日份额与单位净值，生成 data.json。

数据源（全部免费、公开）：
  1. 上交所 ETF 基金规模：ak.fund_etf_scale_sse(date)
  2. 深交所基金规模日频：ak.fund_scale_daily_szse(start_date, end_date, symbol="ETF")
  3. 东方财富场内基金历史净值：ak.fund_etf_fund_info_em(fund, start_date, end_date)

计算口径：
  净申购（亿元） = (当日份额 - 前一交易日份额) × 当日单位净值
  总市值（亿元） = 当日份额 × 当日单位净值
  份额统一换算为“亿份”，因此“亿份 × 元”直接得到“亿元”。

注意：净申购是一级市场申赎的估算，不等于场内资金净流入。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

SHANGHAI = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data.json"
SCHEMA_VERSION = 1
DEFAULT_DAYS = 180
MAX_HISTORY_DAYS = 260

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("etf-review")


@dataclass(frozen=True)
class Fund:
    code: str
    name: str
    short_name: str
    exchange: str
    manager: str
    color: str


FUNDS: tuple[Fund, ...] = (
    Fund(
        code="510300",
        name="华泰柏瑞沪深300ETF",
        short_name="华泰柏瑞",
        exchange="SSE",
        manager="华泰柏瑞基金",
        color="#e4572e",
    ),
    Fund(
        code="510310",
        name="易方达沪深300ETF",
        short_name="易方达",
        exchange="SSE",
        manager="易方达基金",
        color="#1f7a8c",
    ),
    Fund(
        code="510330",
        name="华夏沪深300ETF",
        short_name="华夏",
        exchange="SSE",
        manager="华夏基金",
        color="#d49a17",
    ),
    Fund(
        code="159919",
        name="嘉实沪深300ETF",
        short_name="嘉实",
        exchange="SZSE",
        manager="嘉实基金",
        color="#6a4c93",
    ),
)

FUND_BY_CODE = {fund.code: fund for fund in FUNDS}
SSE_CODES = {fund.code for fund in FUNDS if fund.exchange == "SSE"}
SZSE_CODES = {fund.code for fund in FUNDS if fund.exchange == "SZSE"}

# 涨跌分布区间，顺序与前端柱状图一致。
MARKET_BUCKETS: tuple[tuple[str, str, str], ...] = (
    ("gt10", ">10%", "up"),
    ("7to10", "7%~10%", "up"),
    ("3to7", "3%~7%", "up"),
    ("0to3", "0~3%", "up"),
    ("0to_3", "0~-3%", "down"),
    ("_3to_7", "-3%~-7%", "down"),
    ("_7to_10", "-7%~-10%", "down"),
    ("lt_10", "<-10%", "down"),
)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _ak() -> Any:
    """延迟导入 AKShare，方便在没有安装依赖时运行纯计算测试。"""
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确提示
        raise RuntimeError(
            "缺少 akshare，请先执行：pip install -r requirements.txt"
        ) from exc
    return ak


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _normalize_code(value: Any) -> str:
    """把 510300 / 510300.0 / '510300' 统一成 6 位代码。"""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.split(".", 1)[0]
    return text.zfill(6)


def market_bucket_key(pct: float) -> str:
    """把个股涨跌幅归入 8 个展示区间。

    边界规则：10% 归入 7%~10%，-10% 归入 -7%~-10%；
    0% 归入 0~3%，但统计上涨/平盘/下跌时单独计为平盘。
    """
    if pct > 10:
        return "gt10"
    if pct >= 7:
        return "7to10"
    if pct >= 3:
        return "3to7"
    if pct >= 0:
        return "0to3"
    if pct > -3:
        return "0to_3"
    if pct > -7:
        return "_3to_7"
    if pct >= -10:
        return "_7to_10"
    return "lt_10"


def _limit_threshold(code: str, name: str) -> float:
    """按板块和 ST 标记返回涨跌停幅度（百分比）。"""
    upper_name = name.upper()
    if "ST" in upper_name:
        return 5.0
    if code.startswith(("30", "68")):
        return 20.0
    if code.startswith(("4", "8", "92")):
        return 30.0
    return 10.0


def build_market_payload(
    stocks: Iterable[tuple[str, str, float, float | None]],
    market_date: date,
    now: datetime | None = None,
) -> dict[str, Any]:
    """由全市场个股行情生成涨跌分布、涨跌停和成交额数据。

    :param stocks: (代码, 名称, 涨跌幅%, 成交额元) 的可迭代对象
    :param market_date: 数据所属交易日
    """
    now = now or datetime.now(SHANGHAI)
    counts = {key: 0 for key, _, _ in MARKET_BUCKETS}
    total = 0
    up = 0
    down = 0
    flat = 0
    limit_up = 0
    limit_down = 0
    turnover_sh = 0.0
    turnover_sz = 0.0
    turnover_bj = 0.0

    for code, name, pct, amount in stocks:
        if not (math.isfinite(pct)):
            continue
        total += 1
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
        else:
            flat += 1

        counts[market_bucket_key(pct)] += 1

        # 新股上市初期不设涨跌幅限制，名称通常以 N / C 开头，排除在涨跌停统计外。
        if not name.upper().startswith(("N", "C")):
            limit_pct = _limit_threshold(code, name)
            if pct > 0 and abs(pct - limit_pct) <= 0.35:
                limit_up += 1
            elif pct < 0 and abs(pct + limit_pct) <= 0.35:
                limit_down += 1

        if amount is not None and math.isfinite(amount) and amount > 0:
            if code.startswith("6"):
                turnover_sh += amount
            elif code.startswith(("0", "3")):
                turnover_sz += amount
            elif code.startswith(("4", "8", "92")):
                turnover_bj += amount

    total_turnover = turnover_sh + turnover_sz + turnover_bj
    distribution = [
        {
            "key": key,
            "label": label,
            "side": side,
            "count": counts[key],
        }
        for key, label, side in MARKET_BUCKETS
    ]

    return {
        "date": market_date.isoformat(),
        "as_of": now.isoformat(timespec="seconds"),
        "is_stale": False,
        "total": total,
        "up": up,
        "down": down,
        "flat": flat,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "turnover": round(total_turnover / 100_000_000, 2),
        "turnover_sh": round(turnover_sh / 100_000_000, 2),
        "turnover_sz": round(turnover_sz / 100_000_000, 2),
        "turnover_bj": round(turnover_bj / 100_000_000, 2),
        "distribution": distribution,
        "source": "东方财富 A 股行情（AKShare stock_zh_a_spot_em）",
        "limit_note": "涨停/跌停按板块涨跌停幅度与收盘涨跌幅统计，已排除 N/C 开头新股",
    }


def _share_to_yi(value: Any) -> float | None:
    """把交易所份额转换为亿份。

    上交所接口已经将“万份”换算为“份”；深交所接口的字段是“基金规模(份)”。
    这里仍保留一个兜底：如果返回值异常小（小于 1000 万份），按“万份”
    再换算一次，防止上游字段单位变化。4 只沪深 300ETF 的份额都远大于该阈值。
    """
    shares = _as_float(value)
    if shares is None or shares <= 0:
        return None
    if shares < 10_000_000:
        shares *= 10_000
    return shares / 100_000_000


def _chunk_date_range(start: date, end: date, max_days: int = 170) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _fallback_trade_dates(end: date, count: int) -> list[date]:
    """备用交易日历：只剔除周末。仅在 AKShare 交易日历不可用时使用。"""
    start = end - timedelta(days=count * 2 + 45)
    return [item.date() for item in pd.bdate_range(start=start, end=end)]


def get_trade_dates(days: int = DEFAULT_DAYS, end_date: date | None = None) -> list[date]:
    """返回截至 end_date 的最近 days 个交易日（按升序）。"""
    end = end_date or datetime.now(SHANGHAI).date()
    wanted = min(max(days, 2), MAX_HISTORY_DAYS)

    try:
        ak = _ak()
        frame = ak.tool_trade_date_hist_sina()
        if frame is not None and not frame.empty:
            column = "trade_date" if "trade_date" in frame.columns else frame.columns[0]
            values = pd.to_datetime(frame[column], errors="coerce")
            calendar = sorted({item.date() for item in values if not pd.isna(item)})
            calendar = [item for item in calendar if item <= end]
            if calendar:
                # 交易日历偶尔会滞后。若明显落后，则用工作日补足最近一段。
                if calendar[-1] < end - timedelta(days=10):
                    logger.warning(
                        "交易日历最后一天为 %s，明显落后于 %s，使用工作日兜底补齐",
                        calendar[-1],
                        end,
                    )
                    extra = [item for item in _fallback_trade_dates(end, wanted) if item > calendar[-1]]
                    calendar = sorted(set(calendar + extra))
                return calendar[-wanted:]
    except Exception as exc:  # 网络问题不应阻断后续数据源
        logger.warning("获取交易日历失败，改用工作日兜底：%s", exc)

    return _fallback_trade_dates(end, wanted)[-wanted:]


# ---------------------------------------------------------------------------
# 数据抓取
# ---------------------------------------------------------------------------


def _retry(description: str, func: Any, attempts: int = 3, pause: float = 1.2) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - 上游异常类型不稳定
            last_error = exc
            if attempt < attempts:
                sleep_for = pause * attempt
                logger.warning("%s失败（第 %s/%s 次）：%s，%.1f 秒后重试", description, attempt, attempts, exc, sleep_for)
                time.sleep(sleep_for)
    logger.error("%s最终失败：%s", description, last_error)
    return None


def fetch_sse_shares(dates: Iterable[date]) -> dict[date, dict[str, float]]:
    """抓取上交所每日 ETF 份额，返回 {日期: {代码: 亿份}}。"""
    targets = sorted(set(dates))
    if not targets:
        return {}

    ak = _ak()
    result: dict[date, dict[str, float]] = {}
    for index, item_date in enumerate(targets, start=1):
        stamp = item_date.strftime("%Y%m%d")
        frame = _retry(
            f"上交所份额 {stamp}",
            lambda: ak.fund_etf_scale_sse(date=stamp),
            attempts=3,
            pause=1.0,
        )
        if frame is None or frame.empty:
            logger.warning("上交所 %s 无份额数据", stamp)
            continue

        day_values: dict[str, float] = {}
        for _, row in frame.iterrows():
            code = _normalize_code(row.get("基金代码"))
            if code not in SSE_CODES:
                continue
            shares = _share_to_yi(row.get("基金份额"))
            if shares is not None:
                day_values[code] = shares
        if day_values:
            result[item_date] = day_values

        if index % 20 == 0 or index == len(targets):
            logger.info("上交所份额进度 %s/%s", index, len(targets))
        time.sleep(0.12)

    return result


def fetch_szse_shares(start: date, end: date) -> dict[date, dict[str, float]]:
    """抓取深交所每日 ETF 份额，返回 {日期: {代码: 亿份}}。"""
    if start > end:
        return {}

    ak = _ak()
    result: dict[date, dict[str, float]] = {}
    for chunk_start, chunk_end in _chunk_date_range(start, end):
        label = f"深交所份额 {chunk_start}~{chunk_end}"
        frame = _retry(
            label,
            lambda s=chunk_start, e=chunk_end: ak.fund_scale_daily_szse(
                start_date=s.strftime("%Y%m%d"),
                end_date=e.strftime("%Y%m%d"),
                symbol="ETF",
            ),
            attempts=3,
            pause=1.5,
        )
        if frame is None or frame.empty:
            logger.warning("%s 无数据", label)
            continue

        for _, row in frame.iterrows():
            code = _normalize_code(row.get("基金代码"))
            if code not in SZSE_CODES:
                continue
            item_date = _as_date(row.get("日期"))
            shares = _share_to_yi(row.get("基金份额"))
            if item_date is None or shares is None:
                continue
            result.setdefault(item_date, {})[code] = shares

        time.sleep(0.15)

    return result


def fetch_navs(codes: Iterable[str], start: date, end: date) -> dict[str, dict[date, float]]:
    """抓取东方财富场内基金历史单位净值，返回 {代码: {日期: 净值}}。"""
    ak = _ak()
    result: dict[str, dict[date, float]] = {}
    for code in sorted(set(codes)):
        frame = _retry(
            f"东方财富净值 {code}",
            lambda c=code: ak.fund_etf_fund_info_em(
                fund=c,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            ),
            attempts=3,
            pause=1.5,
        )
        if frame is None or frame.empty:
            logger.warning("%s 无净值数据", code)
            continue

        values: dict[date, float] = {}
        for _, row in frame.iterrows():
            item_date = _as_date(row.get("净值日期"))
            nav = _as_float(row.get("单位净值"))
            if item_date is not None and nav is not None and nav > 0:
                values[item_date] = nav
        if values:
            result[code] = values
            logger.info("%s 净值 %s 条（%s ~ %s）", code, len(values), min(values), max(values))
        else:
            logger.warning("%s 净值数据为空", code)
        time.sleep(0.15)

    return result


def fetch_market_snapshot(market_date: date) -> dict[str, Any] | None:
    """抓取全市场 A 股行情，生成当日涨跌分布与成交额。"""
    ak = _ak()
    frame = _retry(
        "A 股全市场行情",
        lambda: ak.stock_zh_a_spot_em(),
        attempts=3,
        pause=2.0,
    )
    if frame is None or frame.empty:
        logger.warning("全市场行情为空，无法生成大盘盘面")
        return None

    required = {"代码", "名称", "涨跌幅", "成交额"}
    missing = required - set(frame.columns)
    if missing:
        logger.warning("全市场行情缺少字段：%s", "、".join(sorted(missing)))
        return None

    stocks: list[tuple[str, str, float, float | None]] = []
    for _, row in frame.iterrows():
        code = _normalize_code(row.get("代码"))
        name = str(row.get("名称", "")).strip()
        pct = _as_float(row.get("涨跌幅"))
        amount = _as_float(row.get("成交额"))
        if not code or pct is None:
            continue
        stocks.append((code, name, pct, amount))

    if not stocks:
        logger.warning("全市场行情没有有效的涨跌幅数据")
        return None

    payload = build_market_payload(stocks, market_date)
    logger.info(
        "大盘盘面：%s 只，涨/平/跌=%s/%s/%s，涨停/跌停=%s/%s，成交额=%.2f 亿元",
        payload["total"],
        payload["up"],
        payload["flat"],
        payload["down"],
        payload["limit_up"],
        payload["limit_down"],
        payload["turnover"],
    )
    return payload


# ---------------------------------------------------------------------------
# 已有数据与合并
# ---------------------------------------------------------------------------


def load_existing(path: Path) -> dict[str, Any] | None:
    """读取已有 data.json，转换为份额/净值映射。演示数据不参与合并。"""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取已有 data.json 失败，将重新抓取：%s", exc)
        return None

    if payload.get("demo"):
        logger.info("检测到演示 data.json，本次执行完整回补")
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        logger.info("data.json schema 版本不匹配，本次执行完整回补")
        return None

    dates = [_as_date(item) for item in payload.get("dates", [])]
    dates = [item for item in dates if item is not None]
    if not dates:
        return None

    # 上一交易日只用于计算窗口第一天的净申购，不进入前端曲线。
    previous = payload.get("previous") or {}
    previous_date = _as_date(previous.get("date"))

    shares_map: dict[str, dict[date, float]] = {}
    nav_map: dict[str, dict[date, float]] = {}
    series = payload.get("series", {})
    for fund in FUNDS:
        fund_series = series.get(fund.code, {})
        shares_values = fund_series.get("shares", [])
        nav_values = fund_series.get("nav", [])
        if len(shares_values) != len(dates) or len(nav_values) != len(dates):
            logger.warning("%s 历史数组长度不一致，忽略该基金历史", fund.code)
            continue
        shares_map[fund.code] = {
            day: float(value)
            for day, value in zip(dates, shares_values)
            if _as_float(value) is not None
        }
        nav_map[fund.code] = {
            day: float(value)
            for day, value in zip(dates, nav_values)
            if _as_float(value) is not None
        }

    if previous_date is not None:
        for code, value in (previous.get("shares") or {}).items():
            number = _as_float(value)
            if number is not None:
                shares_map.setdefault(str(code), {})[previous_date] = number
        for code, value in (previous.get("nav") or {}).items():
            number = _as_float(value)
            if number is not None:
                nav_map.setdefault(str(code), {})[previous_date] = number

    if not shares_map or not nav_map:
        return None

    return {
        "dates": sorted(set(dates + ([previous_date] if previous_date else []))),
        "shares": shares_map,
        "nav": nav_map,
        "market": payload.get("market"),
    }


def merge_maps(target: dict[str, dict[date, float]], incoming: dict[Any, dict[str, float]] | dict[str, dict[date, float]]) -> None:
    """把抓取结果合并进已有映射。

    兼容两种形态：
      - {日期: {代码: 值}}（份额）
      - {代码: {日期: 值}}（净值）
    """
    if not incoming:
        return
    first_value = next(iter(incoming.values()))
    if not isinstance(first_value, dict):
        return
    first_key = next(iter(first_value))
    if isinstance(first_key, date):
        # {代码: {日期: 值}}
        for code, values in incoming.items():
            target.setdefault(str(code), {}).update(values)
    else:
        # {日期: {代码: 值}}
        for day, values in incoming.items():
            for code, value in values.items():
                target.setdefault(str(code), {})[day] = value


# ---------------------------------------------------------------------------
# 计算
# ---------------------------------------------------------------------------


def is_split_event(share_ratio: float, nav_ratio: float) -> bool:
    """用“份额反向跳变、规模基本连续”识别拆分/合并。

    例：2:1 拆分时份额约 ×2，净值约 ×0.5，scale≈1。
    正常的巨额申赎不会同时满足这两个条件。
    """
    if not (math.isfinite(share_ratio) and math.isfinite(nav_ratio)):
        return False
    if share_ratio <= 0 or nav_ratio <= 0:
        return False
    if abs(math.log(share_ratio)) < math.log(1.35):
        return False
    scale = share_ratio * nav_ratio
    return 0.88 <= scale <= 1.15


def build_payload(
    funds: tuple[Fund, ...],
    trade_dates: list[date],
    shares_map: dict[str, dict[date, float]],
    nav_map: dict[str, dict[date, float]],
    days: int = DEFAULT_DAYS,
    now: datetime | None = None,
    demo: bool = False,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """由份额/净值映射生成前端 data.json。"""
    now = now or datetime.now(SHANGHAI)
    if not trade_dates:
        raise ValueError("trade_dates 不能为空")

    days = min(max(days, 2), len(trade_dates))
    latest_trade_date = trade_dates[-1]

    complete_dates: list[date] = []
    for day in trade_dates:
        if all(day in shares_map.get(fund.code, {}) and day in nav_map.get(fund.code, {}) for fund in funds):
            complete_dates.append(day)

    data_date = max(complete_dates) if complete_dates else None
    if data_date is None:
        any_dates: list[date] = []
        for fund in funds:
            any_dates.extend(shares_map.get(fund.code, {}).keys())
            any_dates.extend(nav_map.get(fund.code, {}).keys())
        data_date = max(any_dates) if any_dates else None

    if data_date is None:
        output_dates: list[date] = []
    else:
        output_dates = [day for day in trade_dates if day <= data_date][-days:]

    trade_index = {day: index for index, day in enumerate(trade_dates)}
    events: list[dict[str, Any]] = []
    series: dict[str, Any] = {}

    for fund in funds:
        fund_shares = shares_map.get(fund.code, {})
        fund_navs = nav_map.get(fund.code, {})
        shares_values: list[float | None] = []
        nav_values: list[float | None] = []
        net_values: list[float | None] = []
        market_values: list[float | None] = []
        flags: list[str | None] = []

        for day in output_dates:
            shares = fund_shares.get(day)
            nav = fund_navs.get(day)
            flag: str | None = None

            if shares is None or nav is None:
                if shares is None and nav is None:
                    flag = "missing"
                elif shares is None:
                    flag = "missing_shares"
                else:
                    flag = "missing_nav"
                shares_values.append(round(shares, 4) if shares is not None else None)
                nav_values.append(round(nav, 4) if nav is not None else None)
                net_values.append(None)
                market_values.append(None)
                flags.append(flag)
                continue

            market_value = shares * nav
            shares_values.append(round(shares, 4))
            nav_values.append(round(nav, 4))
            market_values.append(round(market_value, 2))

            index = trade_index.get(day)
            previous_day = trade_dates[index - 1] if index is not None and index > 0 else None
            previous_shares = fund_shares.get(previous_day) if previous_day else None
            previous_nav = fund_navs.get(previous_day) if previous_day else None

            if previous_day is None or previous_shares is None or previous_nav is None:
                net_values.append(None)
                flags.append(flag or "no_prev")
                continue

            share_ratio = shares / previous_shares if previous_shares else float("nan")
            nav_ratio = nav / previous_nav if previous_nav else float("nan")

            if is_split_event(share_ratio, nav_ratio):
                net_values.append(0.0)
                flags.append("split")
                events.append(
                    {
                        "date": day.isoformat(),
                        "code": fund.code,
                        "type": "split",
                        "share_ratio": round(share_ratio, 4),
                        "nav_ratio": round(nav_ratio, 4),
                        "note": "检测到份额拆分/合并，净申购按 0 处理",
                    }
                )
            else:
                net_subscription = (shares - previous_shares) * nav
                net_values.append(round(net_subscription, 2))
                flags.append(flag)

        series[fund.code] = {
            "shares": shares_values,
            "nav": nav_values,
            "net_subscription": net_values,
            "market_value": market_values,
            "flags": flags,
        }

    previous_payload: dict[str, Any] | None = None
    if output_dates:
        first_index = trade_index.get(output_dates[0])
        if first_index is not None and first_index > 0:
            previous_day = trade_dates[first_index - 1]
            previous_shares: dict[str, float] = {}
            previous_nav: dict[str, float] = {}
            for fund in funds:
                shares = shares_map.get(fund.code, {}).get(previous_day)
                nav = nav_map.get(fund.code, {}).get(previous_day)
                if shares is not None:
                    previous_shares[fund.code] = round(shares, 4)
                if nav is not None:
                    previous_nav[fund.code] = round(nav, 4)
            if previous_shares or previous_nav:
                previous_payload = {
                    "date": previous_day.isoformat(),
                    "shares": previous_shares,
                    "nav": previous_nav,
                }

    missing_latest: dict[str, list[str]] = {"shares": [], "nav": []}
    if data_date is not None:
        for fund in funds:
            if latest_trade_date not in shares_map.get(fund.code, {}):
                missing_latest["shares"].append(fund.code)
            if latest_trade_date not in nav_map.get(fund.code, {}):
                missing_latest["nav"].append(fund.code)

    is_stale = data_date is None or data_date < latest_trade_date
    if data_date is None:
        stale_reason = "暂无可用数据"
    elif is_stale:
        stale_reason = (
            f"最新交易日 {latest_trade_date.isoformat()} 的份额或净值尚未完整发布，"
            "页面展示最近一个完整交易日的数据"
        )
    else:
        stale_reason = None

    market_payload = dict(market) if market else None
    if market_payload:
        market_payload["is_stale"] = market_payload.get("date") != latest_trade_date.isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "demo": demo,
        "meta": {
            "title": "沪深300 ETF 复盘",
            "generated_at": now.isoformat(timespec="seconds"),
            "data_date": data_date.isoformat() if data_date else None,
            "latest_trade_date": latest_trade_date.isoformat(),
            "is_stale": is_stale,
            "stale_reason": stale_reason,
            "trading_days": len(output_dates),
            "window_start": output_dates[0].isoformat() if output_dates else None,
            "window_end": output_dates[-1].isoformat() if output_dates else None,
            "units": {
                "shares": "亿份",
                "nav": "元",
                "net_subscription": "亿元",
                "market_value": "亿元",
            },
            "source": "上交所/深交所每日基金份额；东方财富历史单位净值；东方财富 A 股全市场行情（经 AKShare 获取）",
            "formula": "净申购 = (当日份额 - 前一交易日份额) × 当日单位净值；总市值 = 当日份额 × 当日单位净值",
            "missing_latest": missing_latest,
            "disclaimer": "净申购是一级市场申赎估算，不等同场内资金净流入；数据仅供参考，不构成投资建议。",
        },
        "funds": [
            {
                "code": fund.code,
                "name": fund.name,
                "short_name": fund.short_name,
                "exchange": fund.exchange,
                "manager": fund.manager,
                "color": fund.color,
            }
            for fund in funds
        ],
        "dates": [day.isoformat() for day in output_dates],
        "series": series,
        "previous": previous_payload,
        "market": market_payload,
        "events": events,
    }


# ---------------------------------------------------------------------------
# 写文件与主流程
# ---------------------------------------------------------------------------


def _comparable_payload(payload: dict[str, Any]) -> str:
    clone = json.loads(json.dumps(payload, ensure_ascii=False))
    clone.get("meta", {}).pop("generated_at", None)
    return json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_payload(path: Path, payload: dict[str, Any]) -> bool:
    """仅在数据内容变化时写文件，避免每天产生无意义 commit。"""
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not existing.get("demo") and _comparable_payload(existing) == _comparable_payload(payload):
                logger.info("数据没有变化，跳过写入")
                return False
        except Exception:
            pass

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    logger.info("已写入 %s（%.1f KB）", path, len(text.encode("utf-8")) / 1024)
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取沪深300ETF份额与净值，生成 data.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出文件路径")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="输出交易日数量，默认 180")
    parser.add_argument("--full", action="store_true", help="忽略已有数据，完整回补")
    parser.add_argument("--end-date", type=str, default=None, help="截止日期 YYYY-MM-DD，默认今天")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    end_date = _as_date(args.end_date) if args.end_date else datetime.now(SHANGHAI).date()
    if end_date is None:
        logger.error("--end-date 格式错误，应为 YYYY-MM-DD")
        return 2

    days = min(max(args.days, 2), MAX_HISTORY_DAYS)
    trade_dates = get_trade_dates(days + 1, end_date)
    if not trade_dates:
        logger.error("无法获取交易日历")
        return 1

    existing = None if args.full else load_existing(args.output)
    existing_dates = set(existing["dates"]) if existing else set()

    if existing is None or args.full or len(existing_dates) < 10:
        fetch_dates = list(trade_dates)
    else:
        missing = {day for day in trade_dates if day not in existing_dates}
        recent = set(trade_dates[-8:])
        fetch_dates = sorted(missing | recent)

    # 保证有“前一交易日”份额与净值，才能计算窗口第一天的净申购。
    # 已有数据覆盖该日时无需重复抓取。
    shares_map: dict[str, dict[date, float]] = {}
    nav_map: dict[str, dict[date, float]] = {}
    if existing:
        for code, values in existing["shares"].items():
            shares_map[code] = dict(values)
        for code, values in existing["nav"].items():
            nav_map[code] = dict(values)
        logger.info("已载入已有数据 %s 天", len(existing_dates))

    first_day = trade_dates[0]
    needs_prior = any(
        first_day not in shares_map.get(fund.code, {}) or first_day not in nav_map.get(fund.code, {})
        for fund in FUNDS
    )
    if needs_prior:
        fetch_dates = sorted(set(fetch_dates) | {first_day})

    if not fetch_dates:
        fetch_dates = list(trade_dates)

    logger.info(
        "交易日窗口 %s ~ %s，共 %s 天；本次抓取 %s 天",
        trade_dates[0],
        trade_dates[-1],
        len(trade_dates),
        len(fetch_dates),
    )

    if fetch_dates:
        sse = fetch_sse_shares(fetch_dates)
        merge_maps(shares_map, sse)

        szse_start, szse_end = min(fetch_dates), max(fetch_dates)
        szse = fetch_szse_shares(szse_start, szse_end)
        merge_maps(shares_map, szse)

        nav_start = min(fetch_dates) - timedelta(days=7)
        navs = fetch_navs([fund.code for fund in FUNDS], nav_start, end_date)
        merge_maps(nav_map, navs)

    if not any(shares_map.values()) or not any(nav_map.values()):
        logger.error("没有抓到任何份额或净值数据")
        return 1

    market = fetch_market_snapshot(trade_dates[-1])
    if market is None and existing and existing.get("market"):
        market = dict(existing["market"])
        market["is_stale"] = True
        market["stale_reason"] = "当日全市场行情暂不可用，展示上一次成功获取的数据"
        logger.warning("保留已有大盘盘面数据：%s", market.get("date"))

    payload = build_payload(
        FUNDS,
        trade_dates,
        shares_map,
        nav_map,
        days=days,
        demo=False,
        market=market,
    )

    if not payload["dates"]:
        logger.error("没有可用于绘图的完整交易日数据")
        return 1

    write_payload(args.output, payload)

    meta = payload["meta"]
    logger.info(
        "完成：data_date=%s latest_trade_date=%s 天数=%s stale=%s 事件=%s",
        meta["data_date"],
        meta["latest_trade_date"],
        meta["trading_days"],
        meta["is_stale"],
        len(payload["events"]),
    )
    if meta["missing_latest"]["shares"] or meta["missing_latest"]["nav"]:
        logger.warning(
            "最新交易日缺失：份额=%s 净值=%s",
            meta["missing_latest"]["shares"],
            meta["missing_latest"]["nav"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
