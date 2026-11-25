"""Offline test: synthetic prices, no network. Run: python screener/test_screen.py"""
import sys, tempfile
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import screen

assert screen.to_yahoo("BBD.B") == "BBD-B.TO" and screen.to_yahoo("REI.UN") == "REI-UN.TO"
for bad in ["ENB.PR.A", "ABC.WT", "XYZ.DB.B", "DLR.U"]:
    assert screen.EXCLUDE.search(bad), bad
for good in ["REI.UN", "BBD.B", "AQN", "XEQT"]:
    assert not screen.EXCLUDE.search(good), good

rng = np.random.default_rng(0)
idx = pd.bdate_range(end="2026-11-20", periods=260)
def series(start, drift, vol, volume, spread):
    c = start * np.exp(np.cumsum(rng.normal(drift, vol, len(idx))))
    h, l = c * (1 + spread + abs(rng.normal(0, vol, len(idx)))), c * (1 - spread - abs(rng.normal(0, vol, len(idx))))
    return pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": volume}, index=idx)
data = {
    "STEADY.TO": series(8, 0.0012, 0.008, 400_000, 0.001),   # should rank first
    "CHOPPY.TO": series(8, 0.0012, 0.04, 400_000, 0.001),    # same drift, bumpy
    "DOWN.TO": series(8, -0.002, 0.01, 400_000, 0.001),      # downtrend: score 0
    "PRICEY.TO": series(60, 0.001, 0.01, 400_000, 0.001),    # over $15: filtered
    "THIN.TO": series(5, 0.001, 0.01, 2_000, 0.001),         # illiquid: filtered
    "WIDE.TO": series(3, 0.001, 0.005, 900_000, 0.02),       # wide spread: filtered
}
uni = pd.DataFrame({"ticker": [k[:-3] for k in data], "name": ["Steady Corp", "Choppy Inc", "Down Ltd", "Pricey ETF", "Thin Co", "Wide Co"]})
uni["yahoo"] = uni["ticker"] + ".TO"
screen.load_universe = lambda limit: (uni, "test")
screen.download_history = lambda syms: data
df = screen.run(None, skip_quotes=True)
print(df[["rank", "ticker", "close", "score", "trend_ok", "spread_est_pct", "shares_at_20", "shares_at_100", "note"]])
t = list(df["ticker"])
assert "PRICEY" not in t and "THIN" not in t and "WIDE" not in t, t
assert t[0] == "STEADY", t
assert df.loc[0, "score"] > 0, df.loc[0]
assert df.set_index("ticker").loc["DOWN", "score"] == 0
screen.OUT = Path(tempfile.mkdtemp())
screen.write(df)
assert (screen.OUT / "latest.md").exists()
print(open(screen.OUT / "latest.md").read())
print("OK")
