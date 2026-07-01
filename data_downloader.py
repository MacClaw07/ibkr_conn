#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_downloader — IBKR data client
=======================================
DataDownloader obtains IB and QuestDB handles from SessionManager
(via its Singleton) and provides bar download and live tick streaming.

No direct IB construction, no QuestDB access — all through
SessionManager.get_instance().
"""

import csv
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from ib_insync import BarData

from utils import (
    get_contract,
    parse_date_range,
    resolve_contracts,
    OUTPUT_DIR,
)
from data_record import HistBarData
from logger import get_logger
from session_manager import SessionManager, IBConnectionFatalError

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  DataDownloader
# ═══════════════════════════════════════════════════════════════════════════════

class DataDownloader:
    """Client for IBKR data operations.

    Obtains connections from SessionManager.get_instance() and
    provides bar download and tick streaming functions.
    """

    def __init__(self):
        self._mgr = SessionManager()

    # ── Bar download ─────────────────────────────────────────────────────

    ##
    # Download historical bars.
    #
    # Handles connection errors by calling mgr.on_error() then
    # mgr.get_ib_conn() for automatic retry (6×5s internally).
    #
    # @param args: An argparse.Namespace with connection and bar-pull args.
    def download_bars(self, args):
        while True:
            try:
                ib = self._mgr.get_ib_conn()
            except IBConnectionFatalError:
                logger.error("Cannot connect to IB. Aborting.")
                sys.exit(1)

            qdb = self._mgr.get_questdb()
            try:
                self._do_bars_download(ib, qdb, args)
                return  # success — done
            except Exception as e:
                logger.warning("IB connection lost: %s", e)
                self._mgr.on_error()
                # loop back to get_ib_conn()

    # Core bar download using the given IB and QuestDB handles.
    def _do_bars_download(self, ib, qdb, args):
        resolved, label, expiry_date = get_contract(ib, args)
        start_date, end_date = parse_date_range(args.date)
        use_rth = False if args.all_hours else args.use_rth

        all_bars = _download_bars(
            ib, resolved,
            start_date, end_date,
            args.bar_size, args.what_to_show, use_rth,
        )

        if args.format == "questdb":
            hist_bars = [_to_hist_bar(b) for b in all_bars]
            written = qdb.write_bars(hist_bars, label, expiry_date)
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

    # ── Tick streaming ───────────────────────────────────────────────────

    ##
    # Start streaming; acquires the stream PID lock.
    #
    # @param args: Parsed argparse.Namespace (for PID lock acquisition only).
    def start_streaming(self, args):
        if not self._mgr.acquire_pid_lock(
            self._mgr._stream_pid_file, "Stream"
        ):
            sys.exit(0)
        try:
            self.stream_ticks()
        finally:
            self._mgr.release_pid_lock(self._mgr._stream_pid_file)

    ##
    # Keepalive-aware tick streaming loop.
    #
    # On IB connection loss:
    #   - calls mgr.on_error()
    #   - calls mgr.get_ib_conn() (retries 6×5s internally)
    #   - if IBConnectionFatalError → abort gracefully
    def stream_ticks(self):
        if not self._mgr.keep_alive():
            logger.info("Keepalive is disabled; stream_ticks exiting.")
            sys.exit(0)

        contracts = self._load_tick_config()
        logger.info("Loaded %d contract(s) from config.", len(contracts))

        while self._mgr.keep_alive():
            # ── Get a live connection ──
            try:
                ib = self._mgr.get_ib_conn()
            except IBConnectionFatalError:
                logger.error("Cannot connect to IB for streaming. Aborting.")
                return

            qdb = self._mgr.get_questdb()

            try:
                rics = [c["ric"] for c in contracts]
                resolved = resolve_contracts(ib, rics)
                if not resolved:
                    logger.warning("No contracts resolved; sleeping 10s...")
                    time.sleep(10)
                    continue

                resolved_labels = {r[1] for r in resolved}
                durations = [c["duration_seconds"] for c in contracts
                             if c["ric"] in resolved_labels]
                max_duration = max(durations) if durations else 0

                stream_live_ticks(ib, resolved, max_duration, qdb.send_ilp_batch)

                if max_duration > 0:
                    logger.info("Duration-based stream completed; rechecking keepalive...")
                if not self._mgr.keep_alive():
                    logger.info("Keepalive disabled during stream.")
                    break

            except Exception as e:
                logger.error("ERROR in stream: %s", e)
                if not self._mgr.keep_alive():
                    break
                self._mgr.on_error()
                # loop back to get_ib_conn() at top of while

        if not self._mgr.keep_alive():
            logger.info("Stream exiting: keepalive disabled.")
            sys.exit(0)

    # ── Tick config loading ──────────────────────────────────────────────

    # Load and validate live tick configuration from configs/download_live_tick.json.
    #
    # Returns a list of validated contract entries.
    def _load_tick_config(self) -> list:
        import json

        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "configs", "download_live_tick.json",
        )
        if not os.path.isfile(config_path):
            logger.error("%s not found", config_path)
            sys.exit(1)

        try:
            with open(config_path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("%s is not valid JSON: %s", config_path, e)
            sys.exit(1)

        if "contracts" not in data or not isinstance(data["contracts"], list) or not data["contracts"]:
            logger.error("%s must contain a non-empty 'contracts' list", config_path)
            sys.exit(1)

        validated = []
        for i, c in enumerate(data["contracts"]):
            if not isinstance(c, dict) or "ric" not in c or not isinstance(c["ric"], str) or not c["ric"].strip():
                logger.error("each contract must have a 'ric' field (contract index %d)", i)
                sys.exit(1)
            validated.append({
                "ric": c["ric"].strip(),
                "duration_seconds": c.get("duration_seconds", 0),
            })

        return validated


# ═══════════════════════════════════════════════════════════════════════════════
#  Historical bar download helpers (module-level)
# ═══════════════════════════════════════════════════════════════════════════════

# Split a date range into contiguous chunks of up to chunk_days days.
#
# Returns a list of (start, end) datetime tuples.
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


# Request a historical data chunk from IB for a single contract.
#
# Returns a list of BarData for the requested end time and duration.
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


# Download bars across the date range by fetching multiple historical chunks.
#
# Returns a deduplicated, sorted list of BarData.
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


def _to_hist_bar(b: BarData) -> HistBarData:
    """Convert ib_insync.BarData to our strongly-typed HistBarData."""
    return HistBarData(
        date=b.date,
        open=b.open,
        high=b.high,
        low=b.low,
        close=b.close,
        volume=int(b.volume) if b.volume is not None else None,
        bar_count=int(b.barCount) if b.barCount is not None else None,
        average=b.average,
    )


# Write a list of BarData rows to a CSV file.
#
# Returns the number of bars written.
def _bars_to_csv(bars: List[BarData], path: str) -> int:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "open", "high", "low", "close", "volume",
                      "bar_count", "average"])
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


# ═══════════════════════════════════════════════════════════════════════════════
#  Live tick streaming
# ═══════════════════════════════════════════════════════════════════════════════

# Build a QuestDB ILP line from an IB ticker update.
#
# Returns None when no valid fields are present.
def _build_ilp_line(ticker, ric_label: str, expiry_date: str) -> Optional[str]:
    measurement = "futures_tick"

    if ticker.time is None:
        return None

    # Timestamp in nanoseconds
    ts_ns = int(ticker.time.timestamp() * 1_000_000_000)

    tags = f"ric={ric_label},expiry={expiry_date}"
    fields = []

    def _ok(val):
        return val is not None and val == val

    if _ok(ticker.bid):
        fields.append(f"bid={ticker.bid}")
    if _ok(ticker.ask):
        fields.append(f"ask={ticker.ask}")
    if _ok(ticker.last):
        fields.append(f"last={ticker.last}")
    if _ok(ticker.bidSize):
        fields.append(f"bid_size={int(ticker.bidSize)}i")
    if _ok(ticker.askSize):
        fields.append(f"ask_size={int(ticker.askSize)}i")
    if _ok(ticker.lastSize):
        fields.append(f"last_size={int(ticker.lastSize)}i")

    if not fields:
        return None

    return f"{measurement},{tags} {','.join(fields)} {ts_ns}"


def stream_live_ticks(
    ib,
    contracts: List[Tuple],
    duration_secs: int,
    send_batch: Callable[[List[str]], int],
) -> Dict[str, int]:
    """Stream live L1 tick data from multiple IBKR contracts to QuestDB.

    Args:
        ib: Connected ib_insync.IB instance (from SessionManager).
        contracts: List of (contract, ric_label, expiry_date) tuples.
        duration_secs: Max seconds to stream (0 = until Ctrl+C).
        send_batch: Callable that posts ILP lines to QuestDB.

    Returns:
        A dict mapping ric_label to written row count.
    """
    ib.reqMarketDataType(3)  # DELAYED — paper account

    tickers = []
    tick_counts: Dict[str, int] = {}
    dup_counts: Dict[str, int] = {}
    written_counts: Dict[str, int] = {}
    _last_fields: Dict[str, tuple] = {}
    lines_buf: List[str] = []
    running = True
    last_status_time = time.time()

    def _fv(val):
        return val if (val is not None and val == val) else None

    for contract, ric_label, expiry_date in contracts:
        tick_counts[ric_label] = 0
        dup_counts[ric_label] = 0
        written_counts[ric_label] = 0
        _last_fields[ric_label] = ()

        ticker = ib.reqMktData(contract, '', False, False)
        tickers.append((ticker, contract))

        def make_handler(label, expiry):
            def on_tick(tick):
                nonlocal running
                tick_counts[label] += 1
                cur = (
                    _fv(tick.bid),
                    _fv(tick.ask),
                    _fv(tick.last),
                    _fv(tick.bidSize),
                    _fv(tick.askSize),
                    _fv(tick.lastSize),
                )
                if cur == _last_fields[label]:
                    dup_counts[label] += 1
                    return
                _last_fields[label] = cur
                line = _build_ilp_line(tick, label, expiry)
                if line:
                    lines_buf.append(line)
            return on_tick

        ticker.updateEvent += make_handler(ric_label, expiry_date)
        logger.info("  Subscribed: %s (expiry: %s)", ric_label, expiry_date)

    def _signal_handler(signum, frame):
        nonlocal running
        logger.info("Ctrl+C received. Shutting down...")
        running = False

    original_sigint = signal.signal(signal.SIGINT, _signal_handler)

    start_time = time.time()
    last_flush = start_time

    logger.info("\nStreaming %d contract(s), duration: %ds (0 = until Ctrl+C)",
                len(contracts), duration_secs)

    try:
        while running:
            now = time.time()

            if duration_secs > 0 and (now - start_time) >= duration_secs:
                logger.info("Duration (%ds) reached.", duration_secs)
                running = False
                break

            elapsed_since_flush = now - last_flush
            if len(lines_buf) >= 100 or elapsed_since_flush >= 1.0:
                if lines_buf:
                    send_batch(lines_buf)
                    for line in lines_buf:
                        ric_start = line.find("ric=") + 4
                        ric_end = line.find(",", ric_start)
                        ric = line[ric_start:ric_end]
                        if ric in written_counts:
                            written_counts[ric] += 1
                    lines_buf.clear()
                last_flush = now

            if now - last_status_time >= 30.0:
                elapsed = int(now - start_time)
                total_ticks = sum(tick_counts.values())
                total_written = sum(written_counts.values())
                total_dupes = sum(dup_counts.values())
                per = " ".join(f"{r}:{tick_counts[r]}" for r in sorted(tick_counts))
                logger.info("[%ds] ticks: %d (%s) | written: %d | dupes: %d",
                            elapsed, total_ticks, per, total_written, total_dupes)
                last_status_time = now

            ib.sleep(0.05)

    finally:
        signal.signal(signal.SIGINT, original_sigint)

        for _, contract in tickers:
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass

        if lines_buf:
            send_batch(lines_buf)
            for line in lines_buf:
                ric_start = line.find("ric=") + 4
                ric_end = line.find(",", ric_start)
                ric = line[ric_start:ric_end]
                if ric in written_counts:
                    written_counts[ric] += 1

        elapsed = int(time.time() - start_time)
        total_ticks = sum(tick_counts.values())
        total_written = sum(written_counts.values())
        total_dupes = sum(dup_counts.values())
        logger.info("\nStreaming complete after %ds.", elapsed)
        logger.info("Total ticks: %d | written: %d | dupes skipped: %d",
                     total_ticks, total_written, total_dupes)
        for ric in sorted(tick_counts):
            logger.info("  %s: %d ticks, %d dupes, %d written",
                        ric, tick_counts[ric], dup_counts[ric], written_counts[ric])

    return written_counts
