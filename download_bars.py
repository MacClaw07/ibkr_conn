#!/usr/bin/env python3
"""
IBKR Historical Bar Downloader
================================
Downloads 1-minute OHLCV bar data from Interactive Brokers and saves to CSV.

Two instrument modes:
  --es            CME E-mini S&P 500 front-month contract (default: Sep 2026)
  --ric RIC       Resolve a futures contract by RIC code (e.g. ESU6)

Usage:
  python3 download_bars.py --date 2026-06-22:2026-06-26
  python3 download_bars.py --date 2026-06-22:2026-06-26 --es 202612        # Dec 2026
  python3 download_bars.py --date 2026-06-22:2026-06-26 --ric ESU6
  python3 download_bars.py --date 2026-06-22:2026-06-26 --ric ESU6 --bar-size "5 mins"
  python3 download_bars.py --date 2026-06-22:2026-06-26 --ric ES --exchange CME --sec-type FUT \
      --currency USD --multiplier 50
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from ib_insync import IB, Contract, Future, Stock, BarData


# ── defaults ────────────────────────────────────────────────────────────────
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4002
DEFAULT_CLIENT_ID = 100
DEFAULT_BAR_SIZE = "1 min"
DEFAULT_WHAT_TO_SHOW = "TRADES"
DEFAULT_USE_RTH = True
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_date_range(
    date_arg: str,
) -> Tuple[datetime, datetime]:
    """Parse 'yyyy-mm-dd:yyyy-mm-dd' into (start_date, end_date)."""
    try:
        start_str, end_str = date_arg.split(":")
    except ValueError:
        raise SystemExit(
            "ERROR: --date must be in format yyyy-mm-dd:yyyy-mm-dd\n"
            f"       got: {date_arg}"
        )

    start = datetime.strptime(start_str.strip(), "%Y-%m-%d")
    end = datetime.strptime(end_str.strip(), "%Y-%m-%d")

    if start > end:
        raise SystemExit("ERROR: start date must be before end date")

    return start, end


def _generate_chunks(
    start: datetime, end: datetime, chunk_days: int = 5
) -> List[Tuple[datetime, datetime]]:
    """Split [start, end] into chunks of chunk_days each."""
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _build_es_contract(contract_month: str) -> Future:
    """
    Build a CME ES future contract.
    contract_month: 'YYYYMM' e.g. '202609'
    """
    return Future(symbol="ES", lastTradeDateOrContractMonth=contract_month, exchange="CME")


def _build_ric_contract(
    ric: str,
    exchange: str = "CME",
    sec_type: str = "FUT",
    currency: str = "USD",
    multiplier: Optional[str] = None,
) -> Contract:
    """
    Build a contract from RIC-like parameters.
    RIC format for futures: root symbol + month code + year digit, e.g. ESU6 = ES Sep 2026.

    If sec_type is FUT, we treat it as a Future. Otherwise it's a Stock contract
    (allows stocks, ETFs, indices via --ric with --sec-type STK).
    """
    if sec_type.upper() == "FUT":
        # Parse RIC: extract root symbol (letters before the month code)
        # e.g. ESU6 -> symbol=ES, month_code=U, year_digit=6
        ric = ric.strip().upper()
        # Find where the month code is — usually the last 2 chars for RIC
        if len(ric) >= 3:
            # Common pattern: <root><month_code><year_digit>
            # But root length varies. We'll take the last 2 chars as month+year
            month_code = ric[-2]
            year_digit = ric[-1]
            root = ric[:-2]

            # Map month code to contract month number
            month_map = {"H": "03", "M": "06", "U": "09", "Z": "12",
                         "F": "01", "G": "02", "J": "04", "K": "05",
                         "N": "07", "Q": "08", "V": "10", "X": "11"}

            if month_code not in month_map:
                raise SystemExit(
                    f"ERROR: unknown month code '{month_code}' in RIC '{ric}'\n"
                    f"       valid codes: H,M,U,Z (quarterly) or F,G,J,K,N,Q,V,X"
                )

            month_num = month_map[month_code]
            # Year: digit is last digit of year. We'll infer the decade.
            # '6' could be 2026, 2036, etc. Use current year as baseline.
            current_year = datetime.now().year
            decade_base = (current_year // 10) * 10
            year_candidate = decade_base + int(year_digit)
            if year_candidate < current_year - 2:
                year_candidate += 10  # next decade

            contract_month_str = f"{year_candidate}{month_num}"

            c = Future(
                symbol=root,
                lastTradeDateOrContractMonth=contract_month_str,
                exchange=exchange,
                currency=currency,
            )
            if multiplier:
                c.multiplier = multiplier
            return c
        else:
            raise SystemExit(f"ERROR: RIC too short: '{ric}'")
    else:
        # Stock / ETF / Index
        return Stock(symbol=ric, exchange=exchange, currency=currency)


def _fetch_chunk(
    ib: IB,
    contract: Contract,
    end_dt: datetime,
    duration_str: str,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
    timeout: float = 120,
) -> List[BarData]:
    """Fetch one chunk of historical bars."""
    # IB format: yyyymmdd HH:MM:SS TZ (with spaces between all parts)
    # OR: yyyymmdd-HH:MM:SS for UTC (with dash between date and time).
    # Using UTC format is more reliable across IB versions.
    end_str = end_dt.strftime("%Y%m%d-%H:%M:%S")
    return ib.reqHistoricalData(
        contract,
        endDateTime=end_str,
        durationStr=duration_str,
        barSizeSetting=bar_size,
        whatToShow=what_to_show,
        useRTH=use_rth,
        formatDate=1,
        timeout=timeout,
    )


def _bars_to_csv(bars: List[BarData], path: str) -> int:
    """Write bars to CSV. Returns number of rows written."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "open", "high", "low", "close", "volume", "bar_count", "average"])
        for b in bars:
            w.writerow([
                b.date.strftime("%Y-%m-%d %H:%M:%S"),
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.barCount,
                b.average,
            ])
    return len(bars)


# ── argparse builder ─────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """Build and return the ArgumentParser with all options."""
    parser = argparse.ArgumentParser(
        description="Download IBKR historical 1-minute bar data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Date range
    parser.add_argument(
        "--date",
        required=True,
        help="Date range in ISO format: yyyy-mm-dd:yyyy-mm-dd",
    )

    # Instrument selection (mutually exclusive group)
    inst = parser.add_mutually_exclusive_group(required=True)
    inst.add_argument(
        "--es",
        nargs="?",
        const="202609",
        metavar="YYYYMM",
        help="CME ES futures contract month (default: 202609 = Sep 2026)",
    )
    inst.add_argument(
        "--ric",
        type=str,
        metavar="RIC",
        help="RIC code for futures, e.g. ESU6 for ES Sep 2026",
    )

    # --ric overrides
    parser.add_argument("--exchange", default="CME", help="Exchange (default: CME)")
    parser.add_argument("--sec-type", default="FUT", help="Security type: FUT, STK, etc.")
    parser.add_argument("--currency", default="USD", help="Currency (default: USD)")
    parser.add_argument("--multiplier", type=str, default=None, help="Contract multiplier")

    # Bar options
    parser.add_argument("--bar-size", default=DEFAULT_BAR_SIZE, help=f"Bar size (default: {DEFAULT_BAR_SIZE})")
    parser.add_argument("--what-to-show", default=DEFAULT_WHAT_TO_SHOW, help=f"Data type (default: {DEFAULT_WHAT_TO_SHOW})")
    parser.add_argument("--use-rth", action="store_true", default=DEFAULT_USE_RTH, help="Regular trading hours only")
    parser.add_argument("--all-hours", action="store_true", help="Include extended hours (overrides --use-rth)")

    # Connection
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"IB Gateway host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"IB Gateway port (default: {DEFAULT_PORT})")
    parser.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID, help=f"Client ID (default: {DEFAULT_CLIENT_ID})")

    # Output
    parser.add_argument("--output", "-o", type=str, default=None, help="Output CSV path (default: auto-generated)")

    return parser


# ── contract resolution ─────────────────────────────────────────────────────

def _get_contract(ib: IB, args: argparse.Namespace) -> Tuple[Contract, str]:
    """
    Build a contract from CLI args and resolve it via reqContractDetails.
    Requires an already-connected IB instance.

    Returns:
        (resolved_contract, label) — label is a human-readable string for
        the instrument, used for the output filename.
    """
    if args.es:
        contract = _build_es_contract(args.es)
        label = f"ES{args.es}"
    else:
        contract = _build_ric_contract(
            args.ric,
            exchange=args.exchange,
            sec_type=args.sec_type,
            currency=args.currency,
            multiplier=args.multiplier,
        )
        label = args.ric.strip().upper()

    print(f"Resolving contract: {contract} ...")
    details = ib.reqContractDetails(contract)
    if not details:
        print(f"ERROR: Could not resolve contract {contract}", file=sys.stderr)
        sys.exit(1)

    resolved = details[0].contract
    print(f"Resolved: {resolved.localSymbol} ({resolved.symbol}) "
          f"Exchange={resolved.exchange} Currency={resolved.currency} "
          f"Multiplier={resolved.multiplier}")
    return resolved, label


# ── download loop ────────────────────────────────────────────────────────────

def _download_bars(
    ib: IB,
    contract: Contract,
    start_date: datetime,
    end_date: datetime,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
) -> List[BarData]:
    """
    Download historical bars in chunks, deduplicate, and return sorted list.

    Handles the full chunking → fetching → dedup pipeline for a date range.
    """
    chunks = _generate_chunks(start_date, end_date, chunk_days=5)
    all_bars: List[BarData] = []
    total_chunks = len(chunks)

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        delta_days = (chunk_end - chunk_start).days + 1
        dur_str = f"{delta_days} D"
        print(f"[{i}/{total_chunks}] Fetching {chunk_start.date()} → {chunk_end.date()} "
              f"({dur_str}) ...", end=" ", flush=True)

        try:
            bars = _fetch_chunk(
                ib, contract, chunk_end, dur_str,
                bar_size, what_to_show, use_rth,
            )
        except Exception as e:
            print(f"\nERROR on chunk {i}: {e}", file=sys.stderr)
            print("Saving data fetched so far...", file=sys.stderr)
            break

        print(f"{len(bars)} bars")
        if bars:
            all_bars.extend(bars)

    # Deduplicate bars (chunk boundaries may overlap)
    if all_bars:
        seen = set()
        deduped: List[BarData] = []
        for b in all_bars:
            key = b.date
            if key not in seen:
                seen.add(key)
                deduped.append(b)
        deduped.sort(key=lambda b: b.date)
        all_bars = deduped

    return all_bars


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = _build_parser()
    args = parser.parse_args()

    # Parse date range
    start_date, end_date = _parse_date_range(args.date)
    use_rth = False if args.all_hours else args.use_rth

    # Connect to IB Gateway
    ib = IB()
    try:
        print(f"Connecting to IB Gateway at {args.host}:{args.port} ...")
        ib.connect(args.host, args.port, clientId=args.client_id)
        print(f"Connected. Account: {ib.managedAccounts()}")
    except Exception as e:
        print(f"ERROR: Could not connect to IB Gateway: {e}", file=sys.stderr)
        print("Is the Gateway running? Try: ~/.local/bin/ibkr-start.sh", file=sys.stderr)
        sys.exit(1)

    try:
        # Build and resolve contract
        resolved, label = _get_contract(ib, args)

        # Download bars
        all_bars = _download_bars(
            ib, resolved,
            start_date, end_date,
            args.bar_size, args.what_to_show, use_rth,
        )

        # Save to CSV
        if args.output:
            out_path = args.output
        else:
            date_tag = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
            out_path = os.path.join(OUTPUT_DIR, f"{label}_{date_tag}_{args.bar_size.replace(' ', '')}.csv")

        written = _bars_to_csv(all_bars, out_path)
        print(f"\nDone. {written} bars saved to {out_path}")
        if not all_bars:
            print("WARNING: No data returned. Possible reasons:")
            print("  - No other TWS/Gateway session can be active (error 162)")
            print("  - Paper accounts get delayed data only")
            print("  - Markets may be closed (check trading hours)")

    finally:
        print("Disconnecting...")
        ib.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
