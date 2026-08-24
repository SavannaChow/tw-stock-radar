# -*- coding: utf-8 -*-
"""自選股卡片用的保守風險快篩。

這裡只整理既有行情、籌碼與基本面資料，不產生買賣建議。缺資料一律標成
unknown，不能因為抓不到資料就當成安全。
"""
from __future__ import annotations

import math
from typing import Any


LEVEL_RANK = {"ok": 0, "unknown": 1, "watch": 2, "high": 3}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 2) -> float | None:
    number = _finite(value)
    return round(number, digits) if number is not None else None


def history_metrics(df, live: bool = False) -> dict:
    """由 OHLCV 日線計算卡片需要的歷史風險量尺；任何缺值皆優雅降級。"""
    out = {
        "avg_turnover_20": None,
        "avg_volume_20_lots": None,
        "atr_pct": None,
        "max_drawdown_60": None,
        "max_drawdown_120": None,
        "ma60_gap_pct": None,
        "ma60_slope_10d_pct": None,
        "ma20_distance_atr": None,
        "from_52w_high_pct": None,
    }
    if df is None or len(df) < 22:
        return out

    try:
        import pandas as pd
        import scan

        data = scan._lower(df.tail(300).reset_index(drop=True))
        if live and len(data) > 22:
            data = data.iloc[:-1]
        close = pd.to_numeric(data["close"], errors="coerce").dropna()
        volume = pd.to_numeric(data["volume"], errors="coerce")
        if len(close) < 22:
            return out

        price = float(close.iloc[-1])
        aligned = data.loc[close.index]
        daily_value = pd.to_numeric(aligned["close"], errors="coerce") * pd.to_numeric(
            aligned["volume"], errors="coerce"
        )
        avg_turnover = daily_value.tail(20).mean()
        avg_volume = volume.tail(20).mean()
        out["avg_turnover_20"] = _round(avg_turnover, 0)
        out["avg_volume_20_lots"] = _round(avg_volume / 1000.0, 0)

        atr = scan._atr_last(data, scan.CHAND_LEN)
        out["atr_pct"] = _round(atr / price * 100.0, 2) if atr and price else None

        def max_drawdown(days: int) -> float | None:
            series = close.tail(days)
            if len(series) < min(20, days):
                return None
            running_high = series.cummax()
            return _round(((series / running_high) - 1.0).min() * 100.0, 2)

        out["max_drawdown_60"] = max_drawdown(60)
        out["max_drawdown_120"] = max_drawdown(120)

        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        if len(ma60.dropna()):
            current_ma60 = float(ma60.iloc[-1])
            if current_ma60:
                out["ma60_gap_pct"] = _round((price / current_ma60 - 1.0) * 100.0, 2)
            if len(ma60.dropna()) >= 11:
                previous_ma60 = float(ma60.iloc[-11])
                if previous_ma60:
                    out["ma60_slope_10d_pct"] = _round(
                        (current_ma60 / previous_ma60 - 1.0) * 100.0, 2
                    )
        if atr and len(ma20.dropna()):
            out["ma20_distance_atr"] = _round((price - float(ma20.iloc[-1])) / atr, 2)

        high_52w = float(close.tail(240).max())
        if high_52w:
            out["from_52w_high_pct"] = _round((price / high_52w - 1.0) * 100.0, 2)
    except Exception:
        return out
    return out


def quote_metrics(row: dict) -> dict:
    """由即時五檔計算最佳買賣價差；盤後無五檔時回 None。"""
    bid = row.get("bid") or []
    ask = row.get("ask") or []
    best_bid = _finite(bid[0].get("price")) if bid and isinstance(bid[0], dict) else None
    best_ask = _finite(ask[0].get("price")) if ask and isinstance(ask[0], dict) else None
    spread = None
    if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid:
        mid = (best_bid + best_ask) / 2.0
        spread = _round((best_ask - best_bid) / mid * 100.0, 2) if mid else None
    return {"bid_ask_spread_pct": spread, "best_bid": best_bid, "best_ask": best_ask}


def _money(value: float | None) -> str:
    if value is None:
        return "均額 —"
    if value >= 100_000_000:
        return f"均額 {value / 100_000_000:.1f}億"
    if value >= 10_000:
        return f"均額 {value / 10_000:.0f}萬"
    return f"均額 {value:.0f}元"


def _pct(value: float | None, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return "—"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.{digits}f}%"


def _lots(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f}張"


def _category(key: str, label: str, level: str, summary: str, reasons: list[str]) -> dict:
    return {"key": key, "label": label, "level": level, "summary": summary, "reasons": reasons}


def assess(row: dict) -> dict:
    """把單檔資料整理成五面向卡片燈號。門檻僅作保守快篩，不是買賣訊號。"""
    avg_turnover = _finite(row.get("avg_turnover_20"))
    spread = _finite(row.get("bid_ask_spread_pct"))
    atr_pct = _finite(row.get("atr_pct"))
    drawdown = _finite(row.get("max_drawdown_60"))
    drawdown_120 = _finite(row.get("max_drawdown_120"))
    ma60_gap = _finite(row.get("ma60_gap_pct"))
    ma60_slope = _finite(row.get("ma60_slope_10d_pct"))
    chase_atr = _finite(row.get("ma20_distance_atr"))
    from_high = _finite(row.get("from_52w_high_pct"))
    chip_net = _finite(row.get("chip_net_n"))
    avg_volume = _finite(row.get("avg_volume_20_lots"))
    margin_chg = _finite(row.get("margin_chg"))
    eps = _finite(row.get("eps_ttm"))
    rev_yoy = _finite(row.get("rev_yoy"))
    op_margin = _finite(row.get("op_margin"))
    is_etf = str(row.get("code") or "").startswith("00")

    categories: list[dict] = []

    liq_reasons: list[str] = []
    liq_level = "unknown" if avg_turnover is None and spread is None else "ok"
    if avg_turnover is not None:
        if avg_turnover < 30_000_000:
            liq_level = "high"; liq_reasons.append("20日平均成交金額偏低")
        elif avg_turnover < 100_000_000:
            liq_level = max((liq_level, "watch"), key=LEVEL_RANK.get)
            liq_reasons.append("成交金額不高，進出需留意")
    if spread is not None:
        if spread > 0.5:
            liq_level = "high"; liq_reasons.append("即時買賣價差偏大")
        elif spread > 0.2:
            liq_level = max((liq_level, "watch"), key=LEVEL_RANK.get)
            liq_reasons.append("即時買賣價差需留意")
    spread_text = f"價差 {_pct(spread, 2)}" if spread is not None else "價差盤後無資料"
    categories.append(_category("liquidity", "流動性", liq_level,
                                f"{_money(avg_turnover)} · {spread_text}", liq_reasons))

    vol_reasons: list[str] = []
    vol_level = "unknown" if atr_pct is None and drawdown is None else "ok"
    if atr_pct is not None:
        if atr_pct > 5:
            vol_level = "high"; vol_reasons.append("ATR波動幅度偏高")
        elif atr_pct > 3:
            vol_level = max((vol_level, "watch"), key=LEVEL_RANK.get)
            vol_reasons.append("ATR波動幅度需留意")
    if drawdown is not None:
        if drawdown <= -20:
            vol_level = "high"; vol_reasons.append("近60日曾有較深回撤")
        elif drawdown <= -12:
            vol_level = max((vol_level, "watch"), key=LEVEL_RANK.get)
            vol_reasons.append("近60日回撤需留意")
    categories.append(_category("volatility", "波動", vol_level,
                                f"ATR {_pct(atr_pct)} · 60／120日回撤 "
                                f"{_pct(drawdown)}／{_pct(drawdown_120)}", vol_reasons))

    trend_reasons: list[str] = []
    trend_level = "unknown" if ma60_gap is None and chase_atr is None else "ok"
    if chase_atr is not None:
        if chase_atr >= 3:
            trend_level = "high"; trend_reasons.append("股價遠離月線，追高風險較高")
        elif chase_atr >= 2:
            trend_level = max((trend_level, "watch"), key=LEVEL_RANK.get)
            trend_reasons.append("股價離月線偏遠，宜等待")
    if ma60_gap is not None and ma60_slope is not None and ma60_gap < 0 and ma60_slope < 0:
        trend_level = "high"; trend_reasons.append("位於下彎季線之下")
    elif ma60_gap is not None and ma60_gap < 0:
        trend_level = max((trend_level, "watch"), key=LEVEL_RANK.get)
        trend_reasons.append("股價仍在季線之下")
    categories.append(_category("trend", "趨勢／追高", trend_level,
                                f"季線 {_pct(ma60_gap, signed=True)} · 距年高 {_pct(from_high)} · 月線 "
                                f"{f'{chase_atr:.1f} ATR' if chase_atr is not None else '—'}",
                                trend_reasons))

    chip_reasons: list[str] = []
    chip_level = "unknown" if chip_net is None and margin_chg is None else "ok"
    chip_ratio = chip_net / avg_volume if chip_net is not None and avg_volume else None
    if chip_ratio is not None:
        if chip_ratio <= -2 and (margin_chg or 0) > 0:
            chip_level = "high"; chip_reasons.append("法人偏賣且融資增加")
        elif chip_ratio <= -2:
            chip_level = "high"; chip_reasons.append("近10日法人賣超偏重")
        elif chip_ratio <= -0.5:
            chip_level = "watch"; chip_reasons.append("近10日法人籌碼偏弱")
    categories.append(_category("chips", "籌碼", chip_level,
                                f"外資＋投信10日 {_lots(chip_net)} · 融資日增減 {_lots(margin_chg)}", chip_reasons))

    fund_reasons: list[str] = []
    if is_etf:
        fund_level = "na"
        fund_summary = "ETF不適用個股EPS／營收快篩"
    else:
        fund_level = "unknown" if eps is None and rev_yoy is None and op_margin is None else "ok"
        if eps is not None and eps <= 0:
            fund_level = "high"; fund_reasons.append("近四季EPS非正值")
        if op_margin is not None and op_margin < 0:
            fund_level = "high"; fund_reasons.append("營業利益率為負")
        if rev_yoy is not None:
            if rev_yoy <= -20:
                fund_level = "high"; fund_reasons.append("月營收年減幅度偏大")
            elif rev_yoy < 0:
                fund_level = max((fund_level, "watch"), key=LEVEL_RANK.get)
                fund_reasons.append("月營收仍在年減")
        fund_summary = f"EPS {eps:.2f}" if eps is not None else "EPS —"
        fund_summary += f" · 營收YoY {_pct(rev_yoy, signed=True)}"
    categories.append(_category("fundamentals", "基本面", fund_level, fund_summary, fund_reasons))

    scored = [c for c in categories if c["level"] != "na"]
    high_count = sum(c["level"] == "high" for c in scored)
    watch_count = sum(c["level"] == "watch" for c in scored)
    unknown_count = sum(c["level"] == "unknown" for c in scored)
    if high_count:
        level, label = "high", "風險偏高"
    elif watch_count:
        level, label = "watch", "有項目需留意"
    elif unknown_count >= 3:
        level, label = "unknown", "資料不足"
    else:
        level, label = "ok", "暫無明顯警訊"

    reasons = [reason for c in categories for reason in c["reasons"]]
    if not reasons and unknown_count:
        reasons.append(f"{unknown_count}項資料不足，不能視為低風險")
    return {
        "level": level,
        "label": label,
        "high_count": high_count,
        "watch_count": watch_count,
        "unknown_count": unknown_count,
        "reasons": reasons[:3],
        "categories": categories,
        "disclaimer": "風險快篩，不是買賣建議",
    }
