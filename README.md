# Claude's $20 vs XEQT

A one-page dashboard for a small trading experiment: Claude picks TSX trades with a $20 start plus $20 a month, and the account is measured against the same deposits bought into XEQT on the same days.

The page reads everything live from the experiment's Google Sheet every time it loads, and again every 5 minutes. Daily updates happen in the sheet only, so this repo doesn't need to change.

## Setup

1. **Share the sheet.** In Google Sheets, open Share and set General access to "Anyone with the link" as Viewer. The page can't read it otherwise.
2. **Turn on GitHub Pages.** In this repo, go to Settings > Pages, set Source to "Deploy from a branch", and choose `main` and `/ (root)`.
3. Open `https://setspeed1000.github.io/claude-stocks/`.

To preview the layout with sample numbers, add `#demo` to the URL.

## What it reads

| Tab | Used for |
|---|---|
| Dashboard feed | Headline numbers: account value, benchmark value, cash, stop rule |
| To-do | Steps to place in Wealthsimple. Only rows whose `Status` is Open show on the Overview; Done, Replaced and Expired rows move to the Journal. Without a Status column, the Done tick box decides. |
| Trades | The trade log |
| Holdings | Open positions |
| Watchlist | Prices, 30-day ranges and 90-day averages |
| Contributions | Monthly deposits into the account, matched by XEQT on the benchmark side |
| Daily Log (optional) | The "race over time" chart. Add two columns, `Account value (CAD)` and `Benchmark value (CAD)`, and fill one row per trading day at the close. Until two rows exist the chart shows a placeholder. |

## What's on the page

The site has six tabs. Link straight to one with `#trades`, `#performance` and so on; `#demo/trades` shows a tab with sample numbers.

- **Overview**: the race against XEQT, key numbers, profit over time, today's to-do steps, holdings with a cash and stock split, and trade plans.
- **Trades**: a trading record (win rate, average win and loss, profit factor, expectancy, average R, hold time, fill rate, best and worst trade, fees), trade plans on a stop-to-target ruler, a profit or loss bar per closed trade, profit by stock, and the full trade log with status filters, search and a CSV download.
- **Performance**: profit over time, Claude against XEQT side by side (time-weighted return, worst drop, best and worst day, up days, streaks, volatility), return and drawdown charts, a month-by-month table, and every deposit.
- **Watchlist**: the watchlist with sorting, a momentum map (price against the 90-day average across, position in the 30-day range up), and plain-language signals.
- **Journal**: trades with Claude's reasoning, to-do steps, deposits and Daily Log notes on one timeline.
- **Tools**: a position size calculator, a what-if projection of the monthly deposits, and the stop rule in numbers.

The header also shows whether the TSX is open (regular hours only; holidays aren't counted).

## TSX screener

`screener/screen.py` scans every TSX-listed stock and ETF and keeps the ones a $20-$100 account can actually trade:

- **Price** $1 to $15, so whole shares fit.
- **Liquidity**: 20-day median of at least 50,000 shares and $500,000 traded a day, with no zero-volume days in the last 60.
- **Spread** at most 0.6%, from a live bid/ask quote for the top 60 names and a Corwin-Schultz high-low estimate otherwise.
- **Excluded**: preferred shares, warrants, debentures, US-dollar lines, and leveraged or inverse ETFs.

Survivors are ranked by risk-adjusted momentum (blended 3- and 6-month return over 60-day volatility), with penalties for spread cost and 6-month drawdown. Anything below its 50- or 100-day average, or pinned by a takeover bid, scores zero. Each row also has ATR(14), a 2 x ATR stop, and the whole shares a $20 and a $100 account could buy under the 10%-risk rule.

It runs on GitHub Actions every Friday at 2:30 PM ET (3:30 PM in summer), or on demand from **Actions > TSX screener > Run workflow**, using the TSX company directory and Yahoo Finance, so it uses no Alpha Vantage calls. Results are committed to `data/screener/`: `latest.md` (top 15), `latest.csv` and `latest.json` (everything that passed), and `history/` (one file per run). A weekly scheduled task then copies the top 10 into the sheet's Watchlist tab, marked with a "Screener" note. The screen is a starting list only; every buy still needs a chart-based limit, stop, target and exit date.

Test offline with `python screener/test_screen.py`.
