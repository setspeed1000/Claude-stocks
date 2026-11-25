# Backtest

Weekly-bar backtest of rule-based TSX swing trades against XEQT on the same $20 + $20/month deposits. Findings are in [RESULTS.md](RESULTS.md).

```
python3 backtest/backtest.py      # main run -> results.json
python3 backtest/robustness.py    # rolling windows, cost and ticker checks -> robustness.json
```

Needs Python 3.10+ and pandas. Price files in `data/` are Alpha Vantage `TIME_SERIES_WEEKLY_ADJUSTED` csv exports; add a ticker by saving its csv there and adding it to `UNIVERSE` in `backtest.py`.
