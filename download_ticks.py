"""
IBKR Live Tick Streamer — library module
=========================================
Provides tick-streaming functions imported by run_ibkr.py.

Contains: TickCollector, main_ticks
"""

import signal
import sys
import time
from typing import List, Optional

from ibkr_utils import (
    connect_ib,
    get_contract,
    write_ticks_to_questdb,
    _format_ilp_timestamp,
    HOST, PORT, CLIENT_ID,
)


# ── ILP line builder (tick-specific) ────────────────────────────────────────

def _build_ilp_line(ticker, ric_label: str, expiry_date: str) -> Optional[str]:
    """Build a single ILP line from an ib_insync Ticker for the futures_tick table.

    Returns None if no useful data is present.
    """
    measurement = "futures_tick"

    if ticker.time is None:
        return None
    ts_ns = _format_ilp_timestamp(ticker.time)

    tags = f"ric={ric_label},expiry={expiry_date}"
    fields = []

    def _ok(val):
        return val is not None and val == val  # not NaN

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


# ── live streaming loop ─────────────────────────────────────────────────────

def _stream_live_ticks(
    ib,
    contract,
    ric_label: str,
    expiry_date: str,
    duration_secs: int,
    questdb_url: str,
) -> int:
    """Stream live L1 tick data from IBKR to QuestDB.

    Returns total number of ticks written.
    """
    ticker = ib.reqMktData(contract, '', False, False)

    lines_buf: List[str] = []
    total_written = 0
    tick_count = 0
    running = True
    last_status_time = time.time()

    def on_tick(tick):
        nonlocal tick_count, total_written
        line = _build_ilp_line(tick, ric_label, expiry_date)
        if line:
            lines_buf.append(line)
        tick_count += 1

    ticker.updateEvent += on_tick

    def _signal_handler(signum, frame):
        nonlocal running
        print("\nCtrl+C received. Shutting down...")
        running = False

    original_sigint = signal.signal(signal.SIGINT, _signal_handler)

    start_time = time.time()
    last_flush = start_time

    print(f"Streaming L1 ticks for {ric_label} (expiry: {expiry_date})...")
    print(f"Duration: {duration_secs}s (0 = until Ctrl+C)")
    print()

    try:
        while running:
            now = time.time()

            if duration_secs > 0 and (now - start_time) >= duration_secs:
                print(f"Duration ({duration_secs}s) reached.")
                running = False
                break

            elapsed_since_flush = now - last_flush
            if len(lines_buf) >= 100 or elapsed_since_flush >= 1.0:
                if lines_buf:
                    # Convert raw ILP lines to dicts for write_ticks_to_questdb
                    # Actually, we already have ILP lines. We'll use the _send_ilp_batch
                    # directly since we built lines, not dicts.
                    # For the public API, convert approach: flush ILP directly.
                    from ibkr_utils import _send_ilp_batch
                    written = _send_ilp_batch(lines_buf, questdb_url)
                    total_written += written
                    lines_buf.clear()
                last_flush = now

            if now - last_status_time >= 30.0:
                elapsed = int(now - start_time)
                print(f"[{elapsed}s] ticks: {tick_count} | written: {total_written}")
                last_status_time = now

            ib.sleep(0.05)

    finally:
        signal.signal(signal.SIGINT, original_sigint)

        try:
            ib.cancelMktData(contract)
        except Exception:
            pass

        if lines_buf:
            from ibkr_utils import _send_ilp_batch
            written = _send_ilp_batch(lines_buf, questdb_url)
            total_written += written

        elapsed = int(time.time() - start_time)
        print(f"\nStreaming complete after {elapsed}s.")
        print(f"Total ticks received: {tick_count}")
        print(f"Total rows written to QuestDB: {total_written}")

    return total_written


# ── entry point for run_ibkr.py ────────────────────────────────────────────

def main_ticks(args):
    """Entry point for tick streaming mode. Accepts parsed argparse namespace."""
    ib = connect_ib(args.host, args.port, args.client_id)

    try:
        resolved, label, expiry_date = get_contract(ib, args)

        _stream_live_ticks(
            ib, resolved, label, expiry_date,
            args.duration,
            "http://127.0.0.1:9000",
        )

    finally:
        print("Disconnecting...")
        ib.disconnect()
        print("Disconnected.")
