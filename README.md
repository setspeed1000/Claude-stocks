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
| To-do | The next trading day's steps: buys, sells, stop-losses and take-profits |
| Trades | The trade log |
| Holdings | Open positions |
| Watchlist | Prices, 30-day ranges and 90-day averages |
| Contributions | Monthly deposits into the account, matched by XEQT on the benchmark side |
| Daily Log (optional) | The "race over time" chart. Add two columns, `Account value (CAD)` and `Benchmark value (CAD)`, and fill one row per trading day at the close. Until two rows exist the chart shows a placeholder. |

## What's on the page

- **The race**: Claude's account against the same deposits held in XEQT, today.
- **Key numbers**: profit from closed trades, win rate, money at risk if every stop-loss fills, and how much room is left above the 30% stop rule.
- **The race over time**: profit over the money put in, day by day, for both sides. Hover or use the arrow keys for any day's numbers.
- **What the account holds**, with a bar showing the split between cash and each stock.
- **Trade plans**: each open or planned trade on a ruler from stop-loss to target, with today's price, the risk-to-reward ratio and days left before the exit date.
- **Watchlist**, **How each trade ended** (profit or loss per closed trade, matched oldest buy first), **Trade log** and **Money put in**.

Don't rename these tabs, the keys in column A of Dashboard feed, or the column headers. The sheet ID is set in `SHEET_ID` at the top of the script in `index.html`.

Note that the repo is public and includes the sheet ID, so anyone who finds it can view the sheet.
