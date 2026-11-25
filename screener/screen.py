#!/usr/bin/env python3
"""Weekly TSX screener for a small ($20-$100) Wealthsimple account.

Finds TSX-listed stocks and ETFs that are cheap enough to buy whole shares,
liquid, tight-spread and trending steadily, then sizes each one for a $20 and a
$100 account under the project's 10%-risk-per-trade rule.

Output (in data/screener/):
  latest.csv / latest.json  full ranked list of everything that passed the filters
  latest.md                 short human summary (top picks + run stats)
  universe.csv              last good TSX symbol list (fallback if the TSX feed fails)
  history/YYYY-MM-DD.csv    one snapshot per run

Run:  python screener/screen.py            (live data, needs internet)
      python screener/screen.py --limit 50 (quick test on 50 symbols)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "screener"

# ---- Filters (tuned for a $20-$100 account; override with CLI flags) -------
CFG = {
    "min_price": 1.00,          # below this, tick size makes spreads huge
    "max_price": 15.00,         # whole shares must fit a small account
    "min_dollar_vol": 500_000,  # 20-day median daily value traded (CAD)
    "min_volume": 50_000,       # 20-day median daily shares traded
    "max_spread_pct": 0.60,     # estimated or quoted bid-ask spread, % of price
    "min_history": 130,         # trading days of data needed
    "risk_pct": 0.10,           # project rule: risk at most 10% of account per trade
    "stop_atr": 2.0,            # stop distance for sizing = 2 x ATR(14)
    "accounts": (20, 100),
    "quote_top_n": 60,          # fetch live bid/ask for this many top-ranked names
}

# Instrument suffixes that are not common shares, REIT units or ETFs.
EXCLUDE = re.compile(r"\.(PR|WT|DB|NT|RT|SB|NO|IR|PS)(\.|$)|\.U$")
# Leveraged and inverse ETFs decay over time; not for a steady-compounding account.
LEVERAGED = re.compile(r"BetaPro|(?<![\w.])-?[1-3](?:\.\d+)?x\b|Inverse|Leveraged", re.I)
ETF_HINT = re.compile(r"\b(?:ETF|INDEX|FUND|PORTFOLIO|ISHARES|VANGUARD)\b", re.I)


# ---- Universe --------------------------------------------------------------
def to_yahoo(sym: str) -> str:
    """TSX 'BBD.B' / 'REI.UN' -> Yahoo 'BBD-B.TO' / 'REI-UN.TO'."""
    return sym.replace(".", "-") + ".TO"


def fetch_universe(session) -> pd.DataFrame:
    """Every TSX instrument from the TSX company directory."""
    url = "https://www.tsx.com/json/company-directory/search/tsx/%5E*"
    r = session.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows = []
    for co in r.json().get("results", []):
        insts = co.get("instruments") or [{"symbol": co.get("symbol"), "name": co.get("name")}]
        for ins in insts:
            sym = (ins.get("symbol") or "").strip().upper()
            if sym:
                rows.append({"ticker": sym, "name": (ins.get("name") or co.get("name") or "").strip()})
    df = pd.DataFrame(rows).drop_duplicates("ticker")
    if len(df) < 500:
        raise RuntimeError(f"TSX directory returned only {len(df)} symbols")
    return df


def load_universe(limit: int | None) -> tuple[pd.DataFrame, str]:
    import requests

    cache = OUT / "universe.csv"
    try:
        uni, src = fetch_universe(requests.Session()), "tsx.com directory"
        OUT.mkdir(parents=True, exist_ok=True)
        uni.to_csv(cache, index=False)
    except Exception as e:  # fall back to the last good list
        if not cache.exists():
            raise SystemExit(f"Universe fetch failed and no cache: {e}")
        uni, src = pd.read_csv(cache), f"cached universe.csv (live fetch failed: {e})"
    uni = uni[~uni["ticker"].str.contains(EXCLUDE) & ~uni["name"].fillna("").str.contains(LEVERAGED)].copy()
    uni["yahoo"] = uni["ticker"].map(to_yahoo)
    if limit:
        uni = uni.head(limit)
    return uni.reset_index(drop=True), src


# ---- Prices ----------------------------------------------------------------
def download_history(yahoo_syms: list[str], batch: int = 100) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(yahoo_syms), batch):
        chunk = yahoo_syms[i : i + batch]
        for attempt in range(3):
            try:
                raw = yf.download(chunk, period="1y", interval="1d", auto_adjust=False,
                                  group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:
                print(f"batch {i}: {e}; retrying", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for s in chunk:
            try:
                d = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            d = d.dropna(subset=["Close"])
            if len(d):
                out[s] = d
        time.sleep(1)
    return out


# ---- Metrics ---------------------------------------------------------------
def corwin_schultz(h: pd.Series, l: pd.Series) -> float:
    """Corwin & Schultz (2012) bid-ask spread estimate from daily highs/lows, as % of price.

    Tends to overstate the spread for volatile names, which is the safe direction here.
    """
    h, l = h.astype(float).values, l.astype(float).values
    ok = (h > 0) & (l > 0) & (h >= l)
    if ok.sum() < 10:
        return float("nan")
    hl = np.log(h / l) ** 2
    beta = hl[:-1] + hl[1:]
    gamma = np.log(np.maximum(h[:-1], h[1:]) / np.minimum(l[:-1], l[1:])) ** 2
    k = 3 - 2 * math.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = np.where(np.isfinite(s), np.clip(s, 0, None), np.nan)
    return float(np.nanmean(s) * 100)


def metrics(d: pd.DataFrame) -> dict | None:
    d = d[["Open", "High", "Low", "Close", "Volume"]].astype(float).dropna()
    if len(d) < CFG["min_history"]:
        return None
    c, h, l, v = d["Close"], d["High"], d["Low"], d["Volume"]
    last = float(c.iloc[-1])
    tail20 = d.tail(20)
    med_vol = float(tail20["Volume"].median())
    med_dv = float((tail20["Close"] * tail20["Volume"]).median())
    zero_days = int((d.tail(60)["Volume"] <= 0).sum())
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    rets = np.log(c / prev).dropna()
    vol60 = float(rets.tail(60).std() * math.sqrt(252))
    sma50, sma100, sma200 = (float(c.tail(n).mean()) for n in (50, 100, 200))
    mom3 = last / float(c.iloc[-64]) - 1
    mom6 = last / float(c.iloc[-127]) - 1
    hi52 = float(h.tail(252).max())
    # Max drawdown over the last 6 months: a proxy for how bumpy the ride is.
    c6 = c.tail(126)
    mdd = float((c6 / c6.cummax() - 1).min())
    return {
        "close": round(last, 2),
        "last_date": d.index[-1].strftime("%Y-%m-%d"),
        "med_volume_20d": int(med_vol),
        "med_dollar_vol_20d": int(med_dv),
        "zero_vol_days_60d": zero_days,
        "spread_est_pct": round(corwin_schultz(tail20["High"], tail20["Low"]), 3),
        "atr14": round(atr, 3),
        "atr14_pct": round(atr / last * 100, 2),
        "vol_60d_ann_pct": round(vol60 * 100, 1),
        "mom_3m_pct": round(mom3 * 100, 1),
        "mom_6m_pct": round(mom6 * 100, 1),
        "max_dd_6m_pct": round(mdd * 100, 1),
        "sma50": round(sma50, 2),
        "sma100": round(sma100, 2),
        "sma200": round(sma200, 2) if len(c) >= 200 else None,
        "pct_from_52w_high": round((last / hi52 - 1) * 100, 1),
    }


def score_row(r: pd.Series) -> float:
    """Risk-adjusted momentum with a trend gate and a cost penalty.

    Favours steady uptrends (the project wants compounding, not lottery tickets):
    blended 3/6-month return divided by volatility, minus round-trip spread cost
    and a drawdown penalty. Names below their 50- or 100-day average score zero.
    """
    if not (r["close"] > r["sma50"] > r["sma100"]) or r["pinned"]:
        return 0.0
    vol = max(r["vol_60d_ann_pct"], 5.0)
    mom = 0.4 * r["mom_3m_pct"] + 0.6 * r["mom_6m_pct"]
    s = mom / vol
    s -= 0.5 * r["spread_pct"] / max(r["atr14_pct"], 0.5)  # round-trip cost vs typical daily move
    s += r["max_dd_6m_pct"] / 100                          # e.g. -20% drawdown -> -0.2
    return round(max(s, 0.0), 3)


def size(r: pd.Series, acct: float) -> int:
    """Whole shares allowed by cash and by the 10%-risk rule with a 2xATR stop."""
    stop_dist = CFG["stop_atr"] * r["atr14"]
    by_cash = math.floor(acct / r["close"]) if r["close"] > 0 else 0
    by_risk = math.floor(CFG["risk_pct"] * acct / stop_dist) if stop_dist > 0 else 0
    return int(max(min(by_cash, by_risk), 0))


# ---- Live quotes for the short list ------------------------------------------
def add_quotes(df: pd.DataFrame, n: int) -> pd.DataFrame:
    import yfinance as yf

    df["bid"] = np.nan
    df["ask"] = np.nan
    df["quote_type"] = ""
    for idx in df.head(n).index:
        sym = df.at[idx, "yahoo"]
        try:
            info = yf.Ticker(sym).get_info()
        except Exception as e:
            print(f"quote {sym}: {e}", file=sys.stderr)
            continue
        b, a = info.get("bid") or 0, info.get("ask") or 0
        if b > 0 and a > b:
            df.at[idx, "bid"], df.at[idx, "ask"] = b, a
        df.at[idx, "quote_type"] = info.get("quoteType", "") or ""
        time.sleep(0.4)
    mid = (df["bid"] + df["ask"]) / 2
    df["spread_quote_pct"] = ((df["ask"] - df["bid"]) / mid * 100).round(3)
    return df


# ---- Main ------------------------------------------------------------------
def run(limit: int | None, skip_quotes: bool) -> pd.DataFrame:
    uni, src = load_universe(limit)
    print(f"Universe: {len(uni)} symbols from {src}")
    hist = download_history(uni["yahoo"].tolist())
    print(f"History downloaded for {len(hist)} symbols")

    rows, stats = [], {"universe": len(uni), "with_history": len(hist)}
    for _, u in uni.iterrows():
        d = hist.get(u["yahoo"])
        m = metrics(d) if d is not None else None
        if m:
            rows.append({"ticker": u["ticker"], "yahoo": u["yahoo"], "name": u["name"], **m})
    df = pd.DataFrame(rows)
    stats["enough_history"] = len(df)
    if df.empty:
        raise SystemExit("No symbols with enough history; data source may be down.")

    # Hard filters.
    stale = pd.Timestamp(df["last_date"].max()) - pd.Timedelta(days=5)
    df = df[pd.to_datetime(df["last_date"]) >= stale]
    df = df[df["close"].between(CFG["min_price"], CFG["max_price"])]
    stats["in_price_range"] = len(df)
    df = df[(df["med_dollar_vol_20d"] >= CFG["min_dollar_vol"]) & (df["med_volume_20d"] >= CFG["min_volume"])
            & (df["zero_vol_days_60d"] == 0)]
    stats["liquid"] = len(df)
    df = df[df["spread_est_pct"].fillna(99) <= CFG["max_spread_pct"] * 1.5].copy()  # loose pre-filter

    # Daily range far below what past volatility implies: usually a takeover bid has pinned the price.
    df["pinned"] = df["atr14_pct"] < 0.45 * df["vol_60d_ann_pct"] / math.sqrt(252)
    df["spread_pct"] = df["spread_est_pct"]
    df["score"] = df.apply(score_row, axis=1)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    if not skip_quotes and len(df):
        df = add_quotes(df, CFG["quote_top_n"])
        # Prefer a real quoted spread where we have one.
        df["spread_pct"] = df["spread_quote_pct"].where(df["spread_quote_pct"].notna(), df["spread_est_pct"])
        df["score"] = df.apply(score_row, axis=1)
    else:
        df["bid"] = df["ask"] = df["spread_quote_pct"] = np.nan
        df["quote_type"] = ""

    df = df[df["spread_pct"] <= CFG["max_spread_pct"]].copy()
    stats["tight_spread"] = len(df)

    is_etf = (df["quote_type"].str.upper() == "ETF") | ((df["quote_type"] == "") & df["name"].str.contains(ETF_HINT))
    df["type"] = np.where(is_etf, "ETF", "Stock")
    df["trend_ok"] = (df["close"] > df["sma50"]) & (df["sma50"] > df["sma100"])
    df["stop_2atr"] = (df["close"] - CFG["stop_atr"] * df["atr14"]).round(2)
    for a in CFG["accounts"]:
        df[f"shares_at_{a}"] = df.apply(lambda r: size(r, a), axis=1)
    df["note"] = df.apply(note, axis=1)
    df = df.sort_values(["score", "med_dollar_vol_20d"], ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    stats["candidates_trend_ok"] = int(df["trend_ok"].sum())
    stats["source"] = src
    df.attrs["stats"] = stats
    return df


def note(r: pd.Series) -> str:
    bits = []
    if r["pinned"]:
        bits.append("price pinned after a jump, check for takeover")
    if not r["trend_ok"]:
        bits.append("no uptrend")
    if r["shares_at_20"] == 0:
        bits.append("too big for $20 at 10% risk" if r["close"] <= 20 else "price > $20")
    if r["pct_from_52w_high"] > -3:
        bits.append("near 52w high")
    if r["max_dd_6m_pct"] < -20:
        bits.append(f"{r['max_dd_6m_pct']:.0f}% drawdown in 6m")
    if pd.isna(r.get("spread_quote_pct")):
        bits.append("spread estimated")
    return "; ".join(bits)


COLS = ["rank", "ticker", "name", "type", "close", "score", "trend_ok", "mom_3m_pct", "mom_6m_pct",
        "vol_60d_ann_pct", "max_dd_6m_pct", "atr14", "atr14_pct", "stop_2atr", "shares_at_20", "shares_at_100",
        "spread_pct", "spread_quote_pct", "spread_est_pct", "bid", "ask", "med_volume_20d", "med_dollar_vol_20d",
        "sma50", "sma100", "sma200", "pct_from_52w_high", "last_date", "yahoo", "note"]


def write(df: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "history").mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    out = df[COLS]
    out.to_csv(OUT / "latest.csv", index=False)
    out.to_csv(OUT / "history" / f"{today}.csv", index=False)
    payload = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "config": {k: v for k, v in CFG.items()}, "stats": df.attrs.get("stats", {}),
               "rows": json.loads(out.to_json(orient="records"))}
    (OUT / "latest.json").write_text(json.dumps(payload, indent=1))
    (OUT / "latest.md").write_text(summary(out, payload))


def summary(out: pd.DataFrame, p: dict) -> str:
    s = p["stats"]
    top = out[out["score"] > 0].head(15)
    lines = [f"# TSX screener, {p['generated'][:10]}", "",
             f"Universe {s.get('universe')} -> history {s.get('enough_history')} -> "
             f"${CFG['min_price']:.0f}-${CFG['max_price']:.0f} {s.get('in_price_range')} -> liquid {s.get('liquid')} -> "
             f"spread <= {CFG['max_spread_pct']}% {s.get('tight_spread')} -> uptrend {s.get('candidates_trend_ok')}", "",
             "| # | Ticker | Type | Close | Score | 3m % | 6m % | Vol % | ATR % | Stop (2 ATR) | Shares @ $20 | @ $100 | Spread % | Note |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in top.iterrows():
        lines.append(f"| {r['rank']} | {r['ticker']} | {r['type']} | {r['close']:.2f} | {r['score']:.2f} | {r['mom_3m_pct']} | "
                     f"{r['mom_6m_pct']} | {r['vol_60d_ann_pct']} | {r['atr14_pct']} | {r['stop_2atr']:.2f} | "
                     f"{r['shares_at_20']} | {r['shares_at_100']} | {r['spread_pct']:.2f} | {r['note']} |")
    lines += ["", f"Source: {s.get('source')}. Prices from Yahoo Finance (delayed). Screen only; every buy still needs a chart-based limit, stop, target and exit date."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only screen the first N symbols (testing)")
    ap.add_argument("--no-quotes", action="store_true", help="skip live bid/ask lookups")
    ap.add_argument("--max-price", type=float)
    a = ap.parse_args()
    if a.max_price:
        CFG["max_price"] = a.max_price
    df = run(a.limit, a.no_quotes)
    write(df)
    print((OUT / "latest.md").read_text())


if __name__ == "__main__":
    main()
