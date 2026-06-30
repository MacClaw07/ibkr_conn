"""
IBKR Live Tick Streamer — library module
=========================================
Provides tick-streaming functions imported by ibkr_manager.py.

Supports multiple contracts via --ric RIC1 RIC2 ...

Contains: TickCollector, main_ticks
"""

import signal
import sys
import time
from typing import Dict, List, Optional, Tuple

from ibkr_utils import (
    build_ric_contract,
    connect_ib,
    HOST, PORT, CLIENT_ID,
)
from questdb_manager import (
    _format_ilp_timestamp,
    _send_ilp_batch,
)
from pipeline_logger import get_logger

logger = get_logger(__name__)


# ── ILP line builder (tick-specific) ────────────────────────────────────────

##
# Build a single ILP line from an ib_insync Ticker for the futures_tick table.
#
# @param ticker: An ib_insync.Ticker instance.
# @param ric_label: RIC label string (e.g. "ESU6").
# @param expiry_date: Expiry date as YYYY-MM-DD.
# @return: An ILP-formatted string, or None if the ticker has no useful data.
def _build_ilp_line(ticker, ric_label: str, expiry_date: str) -> Optional[str]:
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


# ── contract resolution helper ─────────────────────────────────────────────

##
# Resolve one RIC and return a (contract, ric_label, expiry_date) tuple.
#
# @param ib: Connected ib_insync.IB instance.
# @param ric: RIC string (e.g. "ESU6").
# @param exchange: Exchange name.
# @param sec_type: Security type.
# @param currency: Currency code.
# @param multiplier: Optional contract multiplier.
# @return: A tuple of (resolved_contract, ric_label, expiry_date).
# @raise SystemExit: If the contract cannot be resolved.
def _resolve_single(ib, ric: str, exchange: str, sec_type: str,
                    currency: str, multiplier) -> Tuple:
    contract = build_ric_contract(ric, exchange, sec_type, currency, multiplier)
    logger.info("Resolving contract: %s ...", contract)
    details = ib.reqContractDetails(contract)
    if not details:
        logger.error("Could not resolve contract %s", contract)
        sys.exit(1)
    cd = details[0]
    resolved = cd.contract
    ric_label = resolved.localSymbol if resolved.localSymbol else ric.strip().upper()
    expiry_date = ""
    ltd = getattr(resolved, 'lastTradeDateOrContractMonth', '')
    if ltd:
        if len(ltd) == 8:
            expiry_date = f"{ltd[0:4]}-{ltd[4:6]}-{ltd[6:8]}"
        elif len(ltd) == 6:
            expiry_date = f"{ltd[0:4]}-{ltd[4:6]}-01"
    if not expiry_date:
        re = getattr(cd, 'realExpirationDate', '')
        if re:
            if len(re) == 8:
                expiry_date = f"{re[0:4]}-{re[4:6]}-{re[6:8]}"
            else:
                expiry_date = re
    logger.info("Resolved: %s (%s) Exchange=%s Currency=%s Multiplier=%s Expiry=%s",
                resolved.localSymbol, resolved.symbol,
                resolved.exchange, resolved.currency,
                resolved.multiplier, expiry_date)
    return resolved, ric_label, expiry_date


# ── live streaming loop ─────────────────────────────────────────────────────

##
# Stream live L1 tick data from multiple IBKR contracts to QuestDB.
#
# Subscribes to market data for each contract, deduplicates unchanged
# ticks, and flushes ILP batches to QuestDB every second (or every 100
# lines, whichever comes first).
#
# @param ib: Connected ib_insync.IB instance.
# @param contracts: List of (contract, ric_label, expiry_date) tuples.
# @param duration_secs: Max seconds to stream (0 = until Ctrl+C).
# @param questdb_url: QuestDB REST base URL.
# @return: A dict mapping ric_label to written row count.
def stream_live_ticks(
    ib,
    contracts: List[Tuple],  # [(contract, ric_label, expiry_date), ...]
    duration_secs: int,
    questdb_url: str,
) -> Dict[str, dict]:
    ib.reqMarketDataType(3)  # DELAYED — paper account has no live data subscription

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
                    _send_ilp_batch(lines_buf, questdb_url)
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
            _send_ilp_batch(lines_buf, questdb_url)
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


# ── entry point for ibkr_manager.py ────────────────────────────────────────

##
# Entry point for tick streaming mode.  Supports multiple --ric values.
#
# @param args: An argparse.Namespace with connection and instrument args.
def main_ticks(args):
    ib = connect_ib(args.host, args.port, args.client_id)

    try:
        contracts = []
        for ric in args.ric:
            resolved, label, expiry = _resolve_single(
                ib, ric, args.exchange, args.sec_type,
                args.currency, args.multiplier,
            )
            contracts.append((resolved, label, expiry))

        stream_live_ticks(
            ib, contracts,
            args.duration,
            "http://127.0.0.1:9000",
        )

    finally:
        logger.info("Disconnecting...")
        ib.disconnect()
        logger.info("Disconnected.")
