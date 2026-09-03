#!/usr/bin/env python3
"""
earnings_watch.py — Pull earnings releases straight from SEC EDGAR.

Why this instead of news: when a public company reports earnings, it's
legally required to file an 8-K (Item 2.02 "Results of Operations and
Financial Condition") with the SEC, usually within minutes to hours of
the press release going out. That filing is the primary source — every
news article about the print is written *after* reading it. This script
polls EDGAR directly, so you see it the moment it's filed instead of
waiting for a headline to get written.

Setup:
    pip install requests
    Edit USER_AGENT below — the SEC requires a real identifying string
    Aidan Cloud13shulk14@gmail.com

Usage:
    python earnings_watch.py                       # check your default watchlist once
    python earnings_watch.py NVDA TSLA              # check specific tickers once
    python earnings_watch.py --watch                # poll default watchlist every 5 min
    python earnings_watch.py CRDO ALAB --watch --interval 120

Notes / limitations:
    - Covers US filers that report on Form 8-K. Foreign private issuers
      (they file Form 6-K instead, on their own schedule) aren't covered.
    - This tells you when a release has just been filed — it does not
      predict upcoming earnings dates.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

import requests

# --- EDIT THIS: SEC requires a real contact string in the User-Agent ---
USER_AGENT = "Aidan (personal earnings tracker) replace-with-your-email@example.com"
HEADERS = {"User-Agent": USER_AGENT}

# Your current/followed names — edit freely. Used when you run the script
# with no tickers given.
DEFAULT_WATCHLIST = ["CRDO", "ALAB"]

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ticker_cache.json")
CACHE_MAX_AGE = 24 * 3600  # refresh the ticker->CIK map at most once a day

_ticker_cache = None


def load_ticker_map():
    """Load (and cache to disk) SEC's ticker -> CIK map."""
    global _ticker_cache
    if _ticker_cache is not None:
        return _ticker_cache

    if os.path.exists(CACHE_FILE) and time.time() - os.path.getmtime(CACHE_FILE) < CACHE_MAX_AGE:
        try:
            with open(CACHE_FILE) as f:
                _ticker_cache = json.load(f)
            return _ticker_cache
        except (json.JSONDecodeError, OSError):
            pass  # fall through and refetch

    resp = requests.get(TICKER_MAP_URL, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _ticker_cache = {v["ticker"].upper(): v["cik_str"] for v in data.values()}

    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(_ticker_cache, f)
    except OSError:
        pass  # caching is a nice-to-have, not required

    return _ticker_cache


def get_cik(ticker):
    tmap = load_ticker_map()
    cik = tmap.get(ticker.upper())
    if cik is None:
        raise ValueError(f"'{ticker}' not found in SEC's ticker list (check the symbol).")
    return cik


def get_recent_earnings_filings(ticker, lookback=1):
    """Return the most recent 8-K filing(s) that report Item 2.02 (earnings)."""
    cik = get_cik(ticker)
    resp = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    recent = data["filings"]["recent"]

    results = []
    n = len(recent["form"])
    items_list = recent.get("items", [""] * n)
    for i in range(n):
        if recent["form"][i] != "8-K":
            continue
        if "2.02" not in (items_list[i] or "").split(","):
            continue
        accession_dashed = recent["accessionNumber"][i]
        accession_nodash = accession_dashed.replace("-", "")
        results.append({
            "ticker": ticker.upper(),
            "filed": recent["filingDate"][i],
            "accepted": recent["acceptanceDateTime"][i],
            "period": recent["reportDate"][i],
            "index_url": (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession_nodash}/{accession_dashed}-index.htm"
            ),
            "doc_url": (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession_nodash}/{recent['primaryDocument'][i]}"
            ),
        })
        if len(results) >= lookback:
            break
    return results


def print_filing(f):
    print(f"\n{f['ticker']} — earnings 8-K filed {f['filed']}  (accepted {f['accepted']})")
    print(f"  Period covered : {f['period']}")
    print(f"  Filing index   : {f['index_url']}")
    print(f"  Press release  : {f['doc_url']}")


def check_once(tickers):
    for t in tickers:
        try:
            filings = get_recent_earnings_filings(t, lookback=1)
        except Exception as e:
            print(f"{t}: error — {e}")
            continue
        if not filings:
            print(f"{t}: no earnings 8-K found in recent filings.")
        else:
            print_filing(filings[0])


def watch(tickers, interval):
    seen = {}
    # prime `seen` so you're not immediately re-alerted on the last old filing
    for t in tickers:
        try:
            filings = get_recent_earnings_filings(t, lookback=1)
            if filings:
                seen[t] = filings[0]["accepted"]
        except Exception:
            pass

    print(f"Watching {', '.join(t.upper() for t in tickers)} every {interval}s. Ctrl+C to stop.")
    try:
        while True:
            for t in tickers:
                try:
                    filings = get_recent_earnings_filings(t, lookback=1)
                except Exception as e:
                    print(f"{t}: error — {e}")
                    continue
                if filings:
                    latest = filings[0]
                    if seen.get(t) != latest["accepted"]:
                        seen[t] = latest["accepted"]
                        print(f"\n\a🔔 NEW EARNINGS FILING — {datetime.now(timezone.utc).isoformat()}")
                        print_filing(latest)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    parser = argparse.ArgumentParser(description="Pull earnings releases straight from SEC EDGAR.")
    parser.add_argument(
        "tickers", nargs="*", default=DEFAULT_WATCHLIST,
        help=f"Ticker symbols to check (default: {' '.join(DEFAULT_WATCHLIST)})",
    )
    parser.add_argument("--watch", action="store_true", help="Poll continuously for new filings")
    parser.add_argument("--interval", type=int, default=300, help="Poll interval in seconds (default 300)")
    args = parser.parse_args()

    if args.watch:
        watch(args.tickers, args.interval)
    else:
        check_once(args.tickers)


if __name__ == "__main__":
    main()
