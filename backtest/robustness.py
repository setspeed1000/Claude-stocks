"""Robustness checks for backtest.py. Run: python3 backtest/robustness.py"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest as bt  # noqa: E402

END = pd.Timestamp("2026-11-20")


def small_account_window(strategy, start, end, universe=None, **kw):
    uni = universe or bt.UNIVERSE
    raw = {s: bt.add_indicators(bt.load(s, adjusted=False)) for s in uni}
    bench = bt.load(bt.BENCH, adjusted=False)
    dates = sorted(set.intersection(*[set(d.index) for d in raw.values()], set(bench.index)))
    dates = [d for d in dates if start <= d <= end]
    raw = {s: d.reindex(dates) for s, d in raw.items()}
    bench = bench.reindex(dates)
    a = bt.run(strategy, raw, dates, bench=bench, **kw)
    b = bt.run_bench(bench, dates, fractional=kw.get("fractional", False))
    return a, b


def main():
    out = {}

    # 1. Rolling 3-year small-account windows vs real XEQT (XEQT exists from Aug 2019)
    starts = pd.date_range("2019-11-01", "2023-11-24", freq="6MS")
    rows = []
    for st in starts:
        en = st + pd.DateOffset(years=3)
        en = min(en, END)
        for s in bt.STRATEGIES:
            a, b = small_account_window(s, st, en, fractional=True)
            sa, sb = bt.curve_stats(a.curve), bt.curve_stats(b)
            rows.append(dict(start=str(st.date()), strategy=s, deposits=sa["deposits"], strat=sa["final"],
                             xeqt=sb["final"], beat=bool(sa["final"] > sb["final"]),
                             avg_r=bt.trade_stats(a.trades).get("avg_r"), max_dd=sa["max_drawdown"]))
    out["rolling_3y_vs_xeqt"] = rows

    # 2. Rolling 3-year edge windows over the long history (total-return prices, big account)
    er = []
    for st in pd.date_range("2008-01-01", "2023-11-01", freq="12MS"):
        en = min(st + pd.DateOffset(years=3), END)
        for s in bt.STRATEGIES:
            e = bt.edge_test(s, st, en)
            er.append(dict(start=str(st.date()), strategy=s, n=e["trades"].get("n"), avg_r=e["trades"].get("avg_r"),
                           strat_ret=round(e["account"]["final"] / 1e5 - 1, 3), hold_ret=e["equal_weight_hold"]))
    out["rolling_3y_edge"] = er

    # 3. Cost sensitivity on the last 3 years (fractional, cash idle)
    st3 = pd.Timestamp("2023-11-24")
    sens = []
    base = (bt.HALF_SPREAD, bt.STOP_SLIP)
    for mult in (0, 1, 2, 3):
        bt.HALF_SPREAD, bt.STOP_SLIP = base[0] * mult, base[1] * mult
        for s in bt.STRATEGIES:
            a, b = small_account_window(s, st3, END, fractional=True)
            sens.append(dict(cost_mult=mult, strategy=s, final=bt.curve_stats(a.curve)["final"],
                             xeqt=bt.curve_stats(b)["final"]))
    bt.HALF_SPREAD, bt.STOP_SLIP = base
    out["cost_sensitivity_3y"] = sens

    # 4. Drop one ticker at a time (last 3 years) to see if one stock carries the result
    loo = []
    for drop in bt.UNIVERSE:
        uni = [u for u in bt.UNIVERSE if u != drop]
        for s in bt.STRATEGIES:
            a, b = small_account_window(s, st3, END, universe=uni, fractional=True)
            loo.append(dict(dropped=drop, strategy=s, final=bt.curve_stats(a.curve)["final"],
                            xeqt=bt.curve_stats(b)["final"]))
    out["leave_one_out_3y"] = loo

    # 5. P/L by ticker, last 3 years
    by = {}
    for s in bt.STRATEGIES:
        a, _ = small_account_window(s, st3, END, fractional=True)
        t = pd.DataFrame(a.trades)
        by[s] = t.groupby("sym")["pnl"].sum().round(2).to_dict() if len(t) else {}
        by[s + "_top3_share"] = round(t["pnl"].nlargest(3).sum() / t["pnl"].sum(), 2) if len(t) else None
    out["pnl_by_ticker_3y"] = by

    (Path(__file__).resolve().parent / "robustness.json").write_text(json.dumps(out, indent=2, default=float))
    return out


if __name__ == "__main__":
    o = main()
    r = pd.DataFrame(o["rolling_3y_vs_xeqt"])
    print(r.to_string(index=False))
    print(r.groupby("strategy")["beat"].agg(["sum", "count"]))
    e = pd.DataFrame(o["rolling_3y_edge"])
    print(e.to_string(index=False))
    print(e.assign(pos=e.avg_r > 0, beat_hold=e.strat_ret > e.hold_ret).groupby("strategy")[["pos", "beat_hold"]].mean())
    print(pd.DataFrame(o["cost_sensitivity_3y"]).to_string(index=False))
    print(pd.DataFrame(o["leave_one_out_3y"]).pivot(index="dropped", columns="strategy", values="final"))
    print(json.dumps(o["pnl_by_ticker_3y"], indent=1))
