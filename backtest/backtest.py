"""Weekly-bar backtest of rule-based TSX swing trades vs XEQT on the same deposits.

Run:  python3 backtest/backtest.py            (writes backtest/results.md and results.json)

Data: Alpha Vantage TIME_SERIES_WEEKLY_ADJUSTED csv files in backtest/data/.
Daily history is a premium endpoint, so every rule here works on weekly bars:
signals are computed on a Friday close and orders work through the next week.

Fill model (deliberately pessimistic):
- Limit buy fills only if the week's low trades below the limit by a tick; fills at
  min(open, limit). Unfilled orders are cancelled at week end.
- Stop is a stop-market order: fills at min(open, stop) less slippage.
- Target is a limit sell: fills at max(open, target).
- If a week touches both stop and target, the stop is assumed to hit first.
- Time exits and stops pay half the bid-ask spread plus slippage.
- Commission $0 (Wealthsimple TSX trades). Dividends are paid in cash if held
  through the week of the ex-date.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
UNIVERSE = ["AQN", "BTO", "WCP", "BTE", "TVE", "VET"]
BENCH = "XEQT"

TICK = 0.01
HALF_SPREAD = 0.0015      # 0.15% of price, each side, on market-type fills
STOP_SLIP = 0.005         # extra 0.5% on stop fills (gaps, thin books)
MAX_RISK = 0.10           # risk at most 10% of equity per trade
HALT_LEVEL = 0.50         # no new buys if equity < 50% of deposits
DEPOSIT = 20.0


# ---------------------------------------------------------------- data

def load(sym: str, adjusted: bool) -> pd.DataFrame:
    d = pd.read_csv(DATA / f"{sym}.csv", parse_dates=["timestamp"])
    d = d.rename(columns={"timestamp": "date", "adjusted close": "adj", "dividend amount": "div"})
    d = d.sort_values("date").set_index("date")
    if adjusted:  # total-return series: fold splits and dividends into prices
        f = d["adj"] / d["close"]
        for c in ("open", "high", "low", "close"):
            d[c] = d[c] * f
        d["div"] = 0.0
    return d[["open", "high", "low", "close", "div"]]


def add_indicators(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    pc = d["close"].shift()
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(10).mean()
    d["sma5"] = d["close"].rolling(5).mean()
    d["sma10"] = d["close"].rolling(10).mean()
    d["sma26"] = d["close"].rolling(26).mean()
    d["sma40"] = d["close"].rolling(40).mean()
    d["low3"] = d["low"].rolling(3).min()
    d["ret13"] = d["close"] / d["close"].shift(13) - 1
    d["ret26"] = d["close"] / d["close"].shift(26) - 1
    delta = d["close"].diff()
    up = delta.clip(lower=0).rolling(6).mean()
    dn = (-delta.clip(upper=0)).rolling(6).mean()
    d["rsi"] = 100 - 100 / (1 + up / dn.replace(0, 1e-9))
    return d


# ---------------------------------------------------------------- strategies
# Each returns None or a plan dict: limit, stop, target, weeks (exit after N weeks).

def pullback(row):
    """Buy a dip inside an uptrend: above the 26-week average, below the 5-week one."""
    if not (row.close > row.sma26 and row.close < row.sma5 and row.sma26 > 0):
        return None
    limit = round(row.close * 0.99, 2)
    stop = round(min(row.low3, limit - 1.0 * row.atr) - TICK, 2)
    if stop <= 0 or stop >= limit:
        return None
    return dict(limit=limit, stop=stop, target=round(limit + 2.0 * (limit - stop), 2), weeks=3,
                score=row.ret26)


def momentum(row):
    """Ride strength: 13-week leaders above a rising 40-week average."""
    if not (row.close > row.sma40 and row.ret13 > 0.05 and row.sma10 > row.sma40):
        return None
    limit = round(row.close * 1.00, 2)
    stop = round(limit - 2.0 * row.atr, 2)
    if stop <= 0:
        return None
    return dict(limit=limit, stop=stop, target=round(limit + 3.0 * (limit - stop), 2), weeks=8,
                score=row.ret13)


def oversold(row):
    """Mean reversion: sharp drop (RSI < 30) well below the 10-week average."""
    if not (row.rsi < 30 and row.close < row.sma10 - 1.0 * row.atr):
        return None
    limit = round(row.close * 0.99, 2)
    stop = round(limit - 1.5 * row.atr, 2)
    target = round(row.sma10, 2)
    if stop <= 0 or target <= limit * 1.02:
        return None
    return dict(limit=limit, stop=stop, target=target, weeks=4, score=-row.rsi)


STRATEGIES = {"pullback": pullback, "momentum": momentum, "oversold": oversold}


# ---------------------------------------------------------------- simulator

@dataclass
class Pos:
    sym: str
    shares: float
    entry: float
    stop: float
    target: float
    exit_week: int
    risk: float
    opened: pd.Timestamp


@dataclass
class Account:
    cash: float = 0.0
    deposits: float = 0.0
    positions: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    curve: list = field(default_factory=list)


def size_shares(cash, equity, entry, stop, fractional, cap_frac):
    per = entry - stop
    if per <= 0:
        return 0
    n = min(MAX_RISK * equity / per, cash / entry, cap_frac * equity / entry)
    return n if fractional else math.floor(n)


def run(strategy: str, frame: dict, dates, *, fractional=False, idle_xeqt=False,
        max_positions=2, cap_frac=1.0, start_cash=DEPOSIT, monthly=DEPOSIT, bench=None):
    """Simulate one account. frame: sym -> indicator DataFrame aligned to dates."""
    fn = STRATEGIES[strategy]
    a = Account()
    xeqt_sh = 0.0
    last_month = None
    pending = []  # plans to work this week
    for i, dt in enumerate(dates):
        # deposit on the first week of each month
        if (dt.year, dt.month) != last_month:
            amt = start_cash if last_month is None else monthly
            a.cash += amt
            a.deposits += amt
            last_month = (dt.year, dt.month)
        # dividends for anything held into this week
        for p in a.positions:
            dv = frame[p.sym].at[dt, "div"]
            if dv > 0:
                a.cash += dv * p.shares
        if idle_xeqt and bench is not None:
            a.cash += xeqt_sh * bench.at[dt, "div"]

        # manage open positions on this week's bar
        still = []
        for p in a.positions:
            b = frame[p.sym].loc[dt]
            px = None
            if b.low <= p.stop:
                px, why = min(b.open, p.stop) * (1 - STOP_SLIP - HALF_SPREAD), "stop"
            elif b.high >= p.target:
                px, why = max(b.open, p.target), "target"
            elif i >= p.exit_week:
                px, why = b.close * (1 - HALF_SPREAD), "time"
            if px is None:
                still.append(p)
                continue
            a.cash += p.shares * px
            pnl = p.shares * (px - p.entry)
            a.trades.append(dict(sym=p.sym, opened=str(p.opened.date()), closed=str(dt.date()), why=why,
                                 entry=round(p.entry, 4), exit=round(px, 4), shares=round(p.shares, 4),
                                 pnl=round(pnl, 4), r=round((px - p.entry) / (p.entry - p.stop), 3)))
        a.positions = still

        # free cash parked in XEQT is sold at this week's open if a new plan needs it
        def equity_at(price_key):
            v = a.cash + sum(p.shares * frame[p.sym].at[dt, price_key] for p in a.positions)
            if idle_xeqt and bench is not None:
                v += xeqt_sh * bench.at[dt, price_key]
            return v

        # work pending limit buys (placed after last Friday's close)
        halted = equity_at("open") < HALT_LEVEL * a.deposits
        for plan in sorted(pending, key=lambda x: -x["score"]):
            if halted or len(a.positions) >= max_positions:
                break
            if any(p.sym == plan["sym"] for p in a.positions):
                continue
            b = frame[plan["sym"]].loc[dt]
            if b.low > plan["limit"] - TICK:
                continue  # never traded through the limit
            fill = min(b.open, plan["limit"])
            if idle_xeqt and xeqt_sh > 0:  # raise cash from XEQT at the open
                a.cash += xeqt_sh * bench.at[dt, "open"] * (1 - HALF_SPREAD)
                xeqt_sh = 0.0
            eq = equity_at("open")
            n = size_shares(a.cash, eq, fill, plan["stop"], fractional, cap_frac)
            if n <= 0 or (not fractional and n < 1):
                continue
            a.cash -= n * fill
            a.positions.append(Pos(plan["sym"], n, fill, plan["stop"], plan["target"],
                                   i + plan["weeks"], n * (fill - plan["stop"]), dt))
        pending = []

        # park idle cash in XEQT at the close
        if idle_xeqt and bench is not None and a.cash > 0:
            px = bench.at[dt, "close"] * (1 + HALF_SPREAD)
            n = a.cash / px if fractional else math.floor(a.cash / px)
            xeqt_sh += n
            a.cash -= n * px

        # new signals from this week's close for next week
        for s, d in frame.items():
            row = d.loc[dt]
            if row.isna().any():
                continue
            plan = fn(row)
            if plan:
                plan["sym"] = s
                pending.append(plan)

        eq = a.cash + sum(p.shares * frame[p.sym].at[dt, "close"] for p in a.positions)
        if idle_xeqt and bench is not None:
            eq += xeqt_sh * bench.at[dt, "close"]
        a.curve.append((str(dt.date()), round(eq, 4), round(a.deposits, 2)))
    return a


def run_bench(bench: pd.DataFrame, dates, *, fractional, start_cash=DEPOSIT, monthly=DEPOSIT):
    cash = sh = dep = 0.0
    last = None
    curve = []
    for dt in dates:
        if (dt.year, dt.month) != last:
            amt = start_cash if last is None else monthly
            cash += amt
            dep += amt
            last = (dt.year, dt.month)
        cash += sh * bench.at[dt, "div"]
        px = bench.at[dt, "close"] * (1 + HALF_SPREAD)
        n = cash / px if fractional else math.floor(cash / px)
        sh += n
        cash -= n * px
        curve.append((str(dt.date()), round(cash + sh * bench.at[dt, "close"], 4), round(dep, 2)))
    return curve


# ---------------------------------------------------------------- stats

def trade_stats(trades):
    if not trades:
        return dict(n=0)
    r = pd.Series([t["r"] for t in trades])
    wins = r[r > 0]
    return dict(n=len(r), win_rate=round((r > 0).mean(), 3), avg_r=round(r.mean(), 3),
                median_r=round(r.median(), 3), avg_win_r=round(wins.mean(), 3) if len(wins) else 0,
                avg_loss_r=round(r[r <= 0].mean(), 3) if (r <= 0).any() else 0,
                exits={k: int(v) for k, v in pd.Series([t["why"] for t in trades]).value_counts().items()})


def curve_stats(curve):
    eq = pd.Series([c[1] for c in curve])
    dep = pd.Series([c[2] for c in curve])
    dd = (eq / eq.cummax() - 1).min()
    return dict(final=round(eq.iloc[-1], 2), deposits=round(dep.iloc[-1], 2),
                gain=round(eq.iloc[-1] - dep.iloc[-1], 2), max_drawdown=round(dd, 3))


def edge_test(strategy, start, end):
    """Large fractional account, 10% risk sizing off a fixed $100k, to read the raw edge."""
    frame = {s: add_indicators(load(s, adjusted=True)) for s in UNIVERSE}
    dates = sorted(set.intersection(*[set(d.index) for d in frame.values()]))
    dates = [d for d in dates if start <= d <= end]
    frame = {s: d.reindex(dates) for s, d in frame.items()}
    a = run(strategy, frame, dates, fractional=True, max_positions=3, cap_frac=0.34,
            start_cash=100000, monthly=0)
    st = trade_stats(a.trades)
    # buy-and-hold equal weight of the same names over the same window (total return)
    bh = pd.Series({s: d["close"].iloc[-1] / d["close"].iloc[0] - 1 for s, d in frame.items()})
    return dict(strategy=strategy, window=f"{dates[0].date()} to {dates[-1].date()}",
                trades=st, account=curve_stats(a.curve), equal_weight_hold=round(bh.mean(), 3))


def main():
    end = pd.Timestamp("2026-11-20")       # last complete week in the data
    start3 = pd.Timestamp("2023-11-24")
    out = {"edge_full": [], "edge_3y": [], "account_3y": [], "bench_3y": {}}

    for s in STRATEGIES:
        out["edge_full"].append(edge_test(s, pd.Timestamp("2006-01-01"), end))
        out["edge_3y"].append(edge_test(s, start3, end))

    # realistic small account, raw prices + cash dividends, last 3 years
    raw = {s: add_indicators(load(s, adjusted=False)) for s in UNIVERSE}
    bench = load(BENCH, adjusted=False)
    dates = sorted(set.intersection(*[set(d.index) for d in raw.values()], set(bench.index)))
    dates = [d for d in dates if start3 <= d <= end]
    raw = {s: d.reindex(dates) for s, d in raw.items()}
    bench = bench.reindex(dates)

    for frac in (False, True):
        out["bench_3y"]["fractional" if frac else "whole"] = curve_stats(run_bench(bench, dates, fractional=frac))
    for s in STRATEGIES:
        for frac in (False, True):
            for idle in (False, True):
                a = run(s, raw, dates, fractional=frac, idle_xeqt=idle, bench=bench)
                out["account_3y"].append(dict(strategy=s, fractional=frac, idle_in_xeqt=idle,
                                              **curve_stats(a.curve), trades=trade_stats(a.trades)))
    (HERE / "results.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
