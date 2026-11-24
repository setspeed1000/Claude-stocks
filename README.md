# Claude's $20 vs XEQT

A one-page dashboard for a $20 trading experiment: Claude picks TSX trades, and the account is measured against the same $20 held in XEQT.

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
| Trades | Orders to place (Status "Planned") and the trade log |
| Holdings | Open positions |
| Watchlist | Prices, 30-day ranges and 90-day averages |
| Contributions | The monthly $20 into XEQT |

Don't rename these tabs, the keys in column A of Dashboard feed, or the column headers. The sheet ID is set in `SHEET_ID` at the top of the script in `index.html`.

Note that the repo is public and includes the sheet ID, so anyone who finds it can view the sheet.
