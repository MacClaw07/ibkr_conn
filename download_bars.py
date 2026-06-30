"""
IBKR Historical Bar Downloader — library module
=================================================
Provides bar-downloading functions imported by ibkr_manager.py.

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
    HOST, PORT, CLIENT_ID, BAR_SIZE, WHAT_TO_SHOW, USE_RTH, OUTPUT_DIR,
)
from questdb_manager import write_bars_to_questdb
from pipeline_logger import get_logger

logger = get_logger(__name__)


# ── chunking & fetching ─────────────────────────────────────────────────────

##
# Split a date range [start, end] into chunks of chunk_days.
#
# @param start: Start datetime.
# @param end: End datetime.
# @param chunk_days: Maximum days per chunk.
# @return: A list of (chunk_start, chunk_end) tuples.
def _generate_chunks(
    start: datetime, end: datetime, chunk_days: int = 5
) -> List[Tuple[datetime, datetime]]:
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


##
# Fetch one chunk of historical bars from IB.
#
# @param ib: Connected ib_insync.IB instance.
# @param contract: The resolved contract.
# @param end_dt: Ending datetime for the request.
# @param duration_str: Duration string (e.g. "5 D").
# @param bar_size: Bar size string (e.g. "1 min").
# @param what_to_show: Data type (e.g. "TRADES").
# @param use_rth: If True, restrict to regular trading hours.
# @param timeout: IB request timeout in seconds.
# @return: A list of ib_insync.BarData.
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


##
# Download historical bars in 5-day chunks, deduplicate, and return.
#
# @param ib: Connected ib_insync.IB instance.
# @param contract: The resolved contract.
# @param start_date: Start datetime for the download.
# @param end_date: End datetime for the download.
# @param bar_size: Bar size string.
# @param what_to_show: Data type.
# @param use_rth: Restrict to RTH.
# @return: A sorted, deduplicated list of ib_insync.BarData.
def _download_bars(
    ib,
    contract,
    start_date: datetime,
    end_date: datetime,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
) -> List[BarData]:
    chunks = _generate_chunks(start_date, end_date, chunk_days=5)
    all_bars: List[BarData] = []
    total_chunks = len(chunks)

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        chunk_end_fixed = chunk_end.replace(hour=23, minute=59, second=59)
        delta_days = (chunk_end - chunk_start).days + 1
        dur_str = f"{delta_days} D"
        logger.info("[%d/%d] Fetching %s -> %s (%s) ...",
                     i, total_chunks, chunk_start.date(), chunk_end.date(), dur_str)

        try:
            bars = _fetch_chunk(
                ib, contract, chunk_end_fixed, dur_str,
                bar_size, what_to_show, use_rth,
            )
        except Exception as e:
            logger.error("ERROR on chunk %d: %s", i, e)
            logger.info("Saving data fetched so far...")
            break

        logger.info("[%d/%d] %d bars", i, total_chunks, len(bars))
        if bars:
            all_bars.extend(bars)

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


##
# Write bars to a CSV file.
#
# @param bars: List of ib_insync.BarData.
# @param path: Output file path.
# @return: Number of rows written.
def _bars_to_csv(bars: List[BarData], path: str) -> int:
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


# ── entry point for ibkr_manager.py ────────────────────────────────────────

##
# Entry point for bar download mode.  Accepts a parsed argparse namespace.
#
# @param args: An argparse.Namespace with connection and bar-pull args.
def main_bars(args):
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
            logger.info("\nDone. %d rows written to QuestDB (futures_hist)", written)
        else:
            if args.output:
                out_path = args.output
            else:
                date_tag = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
                out_path = os.path.join(OUTPUT_DIR, f"{label}_{date_tag}_{args.bar_size.replace(' ', '')}.csv")

            written = _bars_to_csv(all_bars, out_path)
            logger.info("\nDone. %d bars saved to %s", written, out_path)

        if not all_bars:
            logger.warning("No data returned. Possible reasons:")
            logger.info("  - No other TWS/Gateway session can be active (error 162)")
            logger.info("  - Paper accounts get delayed data only")
            logger.info("  - Markets may be closed (check trading hours)")

    finally:
        logger.info("Disconnecting...")
        ib.disconnect()
        logger.info("Disconnected.")
