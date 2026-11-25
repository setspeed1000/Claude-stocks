# Backtest: rule-based TSX swing trades vs XEQT

Run 2026-11-25. Reproduce with `python3 backtest/backtest.py` and `python3 backtest/robustness.py`.

## Verdict

**No reliable edge over XEQT. Confidence: high.** The best rule set beats XEQT over the last 3 years, but it fails over the longer history, depends on three stocks, and has about three times XEQT's drawdown. Treat any one good 3-year stretch as luck until live results say otherwise.

## Setup

- **Data:** Alpha Vantage weekly bars (open, high, low, close, dividends). Daily history is a paid endpoint, and the free key allows 25 calls a day, so this covers XEQT plus 6 of the 13 watchlist names: AQN, BTO, WCP, BTE, TVE, VET. Five of the six are energy or gold, so the universe is narrow.
- **Account:** $20 at the start, $20 on the first week of each month. Same deposits into XEQT for the benchmark.
- **Rules (from the project):** limit entry, stop, target and time exit on every trade; risk at most 10% of equity per trade; no new buys below 50% of deposits; at most 2 positions; whole shares (fractional also run).
- **Fills (pessimistic):** limit buys fill only if the low trades a tick through the limit; stops fill at the worse of open or stop, less 0.65%; time exits pay a 0.15% half-spread; if a week hits both stop and target, the stop counts first. $0 commission. Taxes not modelled.

Three rule sets, fixed before looking at results (no tuning):

| Rule set | Entry | Stop | Target | Exit by |
|---|---|---|---|---|
| Pullback | Above 26-week average, below 5-week average; limit 1% under close | Below 3-week low or 1 ATR | 2R | 3 weeks |
| Momentum | Above rising 40-week average, up 5%+ over 13 weeks | 2 ATR | 3R | 8 weeks |
| Oversold | RSI under 30 and 1 ATR under 10-week average | 1.5 ATR | 10-week average | 4 weeks |

Pullback is closest to how the nightly plans are written (AQN: limit near price, stop under the recent low, about 2 weeks to exit).

## Last 3 years, small account (Nov 2023 to Nov 2026, $740 deposited)

| | Whole shares | Fractional | Max drop | Trades | Win rate | Avg R |
|---|---|---|---|---|---|---|
| XEQT | $898 | $912 | -8% | | | |
| Pullback | $1,275 | $1,282 | -22% | 42 to 45 | 60-67% | +0.26 to +0.38 |
| Momentum | $882 | $881 | -25% | 34 | 53% | +0.12 |
| Oversold | $1,100 | $1,104 | -17% | 27 | 67% | +0.22 |

Parking idle cash in XEQT helped Oversold (+$200) and hurt Momentum and whole-share Pullback. Doubling or tripling spreads and slippage still leaves Pullback ahead ($1,210 and $1,142).

That looks like an edge. The checks below say it isn't.

## Why it doesn't hold up

1. **The long history says the opposite.** Over 2008 to 2026 with total-return prices, Pullback averaged **-0.06R** per trade (234 trades) and Oversold **-0.43R**. Momentum was the only positive one at +0.18R. In rolling 3-year windows, Pullback and Oversold had a positive average R in 4 of 16 windows and **never** beat simply holding the same six stocks. Momentum was positive in 11 of 16 but beat holding in only 6.
2. **Rolling 3-year windows vs real XEQT** (9 windows since Nov 2019): Pullback won 5, Momentum 4, Oversold 1. The windows overlap, so that is roughly a coin flip on 2 or 3 independent samples.
3. **Three names carry it.** In the last 3 years, Pullback's profit came from TVE ($322), WCP ($233) and AQN ($137); the top 3 trades are 90% of the net profit. Dropping TVE alone cuts the result from $1,282 to $916, about XEQT.
4. **Risk is much higher.** Pullback's worst drop was -20% to -35% across windows (all three rule sets: -17% to -48%) against -6% to -20% for XEQT on the same deposits.
5. **Selection bias.** The watchlist was picked recently, and the six names rallied 74% on average over the last 3 years. Rules that buy dips in a rising group look good in that window by construction.

## What this means for the account

- XEQT should be the default home for deposits. Over these windows it is the result to beat, with a fraction of the drawdown.
- If the experiment keeps trading, Momentum-style trades (buy strength, wide stop, longer hold) are the only rules here with a positive long-run average R. Pullback and dip-buying lost money over 18 years.
- At $20 a month the dollar gap is small either way: across the 9 windows Pullback ended between $320 behind and $570 ahead of XEQT.

## Limits of this test

- Weekly bars, not daily, so intra-week stop and target order is guessed (stop first). This makes results slightly worse than reality for trades that hit target first.
- 6 stocks, mostly energy and gold. The other 7 watchlist names (AC, BB, LSPD, BLDP, T, CVE, IMG) can be added in a later run; the free key gets 25 calls a day.
- The nightly picks use judgment, not fixed rules, so this tests the style, not each call.
- No tax: in a non-registered account, frequent trades realize gains each year, while XEQT defers them. That favours XEQT further.
