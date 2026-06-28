"""
IBKR Historical Bar Downloader — library module
=================================================
Provides bar-downloading functions imported by run_ibkr.py.

Contains: _fetch_chunk, _generate_chunks, _download_bars, _bars_to_csv, main_bars
"""

import csv
import os
import sys
from datetime import datetime, timedelta
from typing import List, Tuple

from ib_insync import BarData

from ibkr_utils import (
    connect_ib,
    get_contract,
    parse_date_range,
    write_bars_to_questdb,
    HOST, PORT, CLIENT_ID, BAR_SIZE, WHAT_TO_SHOW, USE_RTH, OUTPUT_DIR,
)


# ── chunking & fetching ─────────────────────────────────────────────────────

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


def _fetch_chunk(
    ib,
    contract,
    end_dt: datetime,
    duration_str: str,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
    timeout: float = 120,
) -> List[BarData]:
    """Fetch one chunk of historical bars from IB."""
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


def _download_bars(
    ib,
    contract,
    start_date: datetime,
    end_date: datetime,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
) -> List[BarData]:
    """Download historical bars in chunks, deduplicate, and return sorted list."""
    chunks = _generate_chunks(start_date, end_date, chunk_days=5)
    all_bars: List[BarData] = []
    total_chunks = len(chunks)

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        chunk_end_fixed = chunk_end.replace(hour=23, minute=59, second=59)
        delta_days = (chunk_end - chunk_start).days + 1
        dur_str = f"{delta_days} D"
        print(f"[{i}/{total_chunks}] Fetching {chunk_start.date()} → {chunk_end.date()} "
              f"({dur_str}) ...", end=" ", flush=True)

        try:
            bars = _fetch_chunk(
                ib, contract, chunk_end_fixed, dur_str,
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


# ── entry point for run_ibkr.py ────────────────────────────────────────────

def main_bars(args):
    """Entry point for bar download mode. Accepts parsed argparse namespace."""
    ib = connect_ib(args.host, args.port, args.client_id)

    try:
        resolved, label, expiry_date = get_contract(ib, args)
        start_date, end_date = parse_date_range(args.date)
        use_rth = False if args.all_hours else args.use_rth

        all_bars = _download_bars(
            ib, resolved,
            start_date, end_date,
            args.bar_size, args.what_to_show, use_rth,
        )

        if args.format == "questdb":
            written = write_bars_to_questdb(all_bars, label, expiry_date)
            print(f"\nDone. {written} rows written to QuestDB (futures_hist)")
        else:
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
