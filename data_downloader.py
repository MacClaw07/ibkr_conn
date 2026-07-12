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

import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from ib_async import BarData, IB, Contract, Ticker
from utils import (
    build_ric_contract,
    get_contract,
    parse_date_range,
    resolve_contracts,
    resolve_option_underlying,
    load_tick_config,
)
from data_record import HistBarData, HistBarOptionData
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

    def __init__(self, mgr: SessionManager):
        self._mgr = mgr

    # ── Bar download ─────────────────────────────────────────────────────

    ##
    # Download historical bars.
    #
    # Handles connection errors by calling mgr.on_error() then
    # mgr.get_ib_conn() for automatic retry (6×5s internally).
    #
    # @param date        Date range string "yyyy-mm-dd:yyyy-mm-dd".
    # @param bar_size    Bar size setting, e.g. "1 min", "1 day".
    # @param what_to_show  Data type, e.g. "TRADES", "MIDPOINT".
    # @param use_rth     If True, use regular trading hours only.
    # @param all_hours   If True, include extended hours (overrides use_rth).
    # @param ric         RIC label e.g. "ESU6" or "ESU67500C" (overrides tick config).
    # @param exchange    Exchange name (default "CME").
    # @param sec_type    Security type: "FUT", "FOP", "STK", etc. (default "FUT").
    # @param currency    Currency code (default "USD").
    # @param multiplier  Optional contract multiplier.
    def download_bars(
        self, date: str, bar_size: str, what_to_show: str,
        use_rth: bool, all_hours: bool,
        ric: str = "",
        exchange: str = "CME",
        sec_type: str = "FUT",
        currency: str = "USD",
        multiplier: str = None,
    ):
        while True:
            try:
                ib = self._mgr.get_ib_conn()
            except IBConnectionFatalError:
                logger.error("Cannot connect to IB. Aborting.")
                sys.exit(1)

            qdb = self._mgr.get_questdb()
            try:
                if ric:
                    # Resolve from CLI args — build contract and resolve directly
                    contract = build_ric_contract(
                        ric,
                        exchange=exchange,
                        sec_type=sec_type,
                        currency=currency,
                        multiplier=multiplier,
                    )
                    logger.info("Resolving contract: %s ...", contract)
                    details = ib.reqContractDetails(contract)
                    if not details:
                        logger.error("Could not resolve contract %s", contract)
                        sys.exit(1)
                    cd = details[0]
                    resolved = cd.contract
                    sec_type_upper = sec_type.upper()
                    if sec_type_upper in ("OPT", "FOP"):
                        label = ric.strip().upper()
                    else:
                        label = resolved.localSymbol if resolved.localSymbol else ric.strip().upper()
                    expiry_date = ""
                    if hasattr(resolved, 'lastTradeDateOrContractMonth') and resolved.lastTradeDateOrContractMonth:
                        ltd = resolved.lastTradeDateOrContractMonth
                        if len(ltd) == 8:
                            expiry_date = f"{ltd[0:4]}-{ltd[4:6]}-{ltd[6:8]}"
                        elif len(ltd) == 6:
                            expiry_date = f"{ltd[0:4]}-{ltd[4:6]}-01"
                    if not expiry_date and hasattr(cd, 'realExpirationDate') and cd.realExpirationDate:
                        expiry_date = cd.realExpirationDate
                        if len(expiry_date) == 8:
                            expiry_date = f"{expiry_date[0:4]}-{expiry_date[4:6]}-{expiry_date[6:8]}"
                    logger.info("Resolved: %s (%s) Exchange=%s Currency=%s Multiplier=%s Expiry=%s",
                                resolved.localSymbol, resolved.symbol,
                                resolved.exchange, resolved.currency,
                                resolved.multiplier, expiry_date)
                else:
                    # Fall back to tick config (existing behavior)
                    resolved, label, expiry_date = get_contract(ib)
                    
                sec_type = resolved.secType.upper() if hasattr(resolved, 'secType') else 'FUT'
                start_date, end_date = parse_date_range(date)
                use_rth = False if all_hours else use_rth

                all_bars = _download_bars_in_chunks(
                    ib, resolved,
                    start_date, end_date,
                    bar_size, what_to_show, use_rth,
                )

                if not all_bars:
                    logger.warning("No data returned. Possible reasons:")
                    logger.info("  - No other TWS/Gateway session can be active (error 162)")
                    logger.info("  - Paper accounts get delayed data only")
                    logger.info("  - Markets may be closed (check trading hours)")

                if sec_type == 'FOP':
                    try:
                        underlying_ric = resolve_option_underlying(label)
                    except (ValueError, TypeError) as e:
                        logger.warning("Cannot resolve underlying RIC from '%s': %s. Using fallback.", label, e)
                        # Fallback: parse from the resolved contract's underlying fields
                        underlying = getattr(resolved, 'underlying', None)
                        underlying_ric = underlying.localSymbol if (underlying and hasattr(underlying, 'localSymbol')) else label.split()[0] if ' ' in label else label
                    option_type = getattr(resolved, 'right', '').upper()
                    strike = float(getattr(resolved, 'strike', 0.0))
                    hist_bars = [_to_hist_option_bar(b, underlying_ric, option_type, strike) for b in all_bars]
                    written = qdb.write_bars(
                        hist_bars, label, expiry_date,
                        sec_type='FOP',
                        underlying_ric=underlying_ric,
                        option_type=option_type,
                        strike=strike,
                    )
                    logger.info("\nDone. %d rows written to QuestDB (options_hist)", written)
                else:
                    hist_bars = [_to_hist_bar(b) for b in all_bars]
                    written = qdb.write_bars(hist_bars, label, expiry_date)
                    logger.info("\nDone. %d rows written to QuestDB (futures_hist)", written)

                return  # success — done
            except Exception as e:
                logger.warning("IB connection lost: %s", e)
                self._mgr.on_error()
                # loop back to get_ib_conn()

    # ── Tick streaming ───────────────────────────────────────────────────

    ##
    # Start streaming; acquires the stream PID lock.
    def start_streaming(self):
        if not self._mgr.acquire_pid_lock(
            self._mgr._stream_pid_file, "Stream"
        ):
            sys.exit(0)
        try:
            self.stream_data()
        finally:
            self._mgr.release_pid_lock(self._mgr._stream_pid_file)

    ##
    # Keepalive-aware tick streaming loop.
    #
    # On IB connection loss:
    #   - calls mgr.on_error()
    #   - calls mgr.get_ib_conn() (retries 6×5s internally)
    #   - if IBConnectionFatalError → abort gracefully
    def stream_data(self):
        contracts = load_tick_config()
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
                resolved_contracts = resolve_contracts(ib, contracts)
                if not resolved_contracts:
                    logger.warning("No contracts resolved; sleeping 10s...")
                    time.sleep(10)
                    continue

                resolved_labels = {r[1] for r in resolved_contracts}
                durations = [c["duration_seconds"] for c in contracts
                             if c["ric"] in resolved_labels]
                max_duration = max(durations) if durations else 0

                _stream_live_ticks(ib, resolved_contracts, max_duration, qdb.send_ilp_batch)

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
    ib: IB,
    contract: Contract,
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
def _download_bars_in_chunks(
    ib: IB,
    contract: Contract,
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
    """Convert ib_async.BarData to our strongly-typed HistBarData."""
    return HistBarData(
        date=getattr(b, "date", None),
        open=getattr(b, "open", None),
        high=getattr(b, "high", None),
        low=getattr(b, "low", None),
        close=getattr(b, "close", None),
        volume=int(getattr(b, "volume", None)) if getattr(b, "volume", None) is not None else None,
        bar_count=int(getattr(b, "barCount", None)) if getattr(b, "barCount", None) is not None else None,
        average=getattr(b, "average", None),
    )


def _to_hist_option_bar(b: BarData, underlying_ric: str, option_type: str, strike: float) -> HistBarOptionData:
    """Convert ib_async.BarData to our strongly-typed HistBarOptionData."""
    return HistBarOptionData(
        date=getattr(b, "date", None),
        underlying_ric=underlying_ric,
        type=option_type,
        strike=strike,
        open=getattr(b, "open", None),
        high=getattr(b, "high", None),
        low=getattr(b, "low", None),
        close=getattr(b, "close", None),
        volume=int(getattr(b, "volume", None)) if getattr(b, "volume", None) is not None else None,
        bar_count=int(getattr(b, "barCount", None)) if getattr(b, "barCount", None) is not None else None,
        average=getattr(b, "average", None),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Live tick streaming
# ═══════════════════════════════════════════════════════════════════════════════

# Build a QuestDB ILP line from an IB ticker update.
#
# Returns None when no valid fields are present.
def _build_ilp_line(contract: Contract, ticker: Ticker, ric_label: str, expiry_date: str) -> Optional[str]:    
    if ticker.time is None:
        return None
    # Timestamp in nanoseconds
    ts_ns = int(ticker.time.timestamp() * 1_000_000_000)

    contract_type = contract.secType.upper()
    measurement = None
    tags = None

    if contract_type == "FUT":
        measurement = "futures_tick"
        tags = f"ric={ric_label},expiry={expiry_date}"
    elif contract_type == "FOP":
        measurement = "options_tick"
        underlying = resolve_option_underlying(ric_label)
        tags = f"ric={ric_label},underlying_ric={underlying},expiry={expiry_date},type={contract.right}"
    else:
        logger.error("Unsupported contract type '%s' for RIC '%s'; skipping tick.", contract_type, ric_label)
        return None  # unsupported contract type
    
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
    if _ok(contract.strike):
        fields.append(f"strike={contract.strike}")
    # insertion_ts: local time of data insertion
    insertion_ns = int(datetime.now().timestamp() * 1_000_000_000)
    fields.append(f"insertion_ts={insertion_ns}i")

    if not fields:
        return None

    return f"{measurement},{tags} {','.join(fields)} {ts_ns}"


def _flush_pending_lines(lines_buf: List[str], send_batch: Callable[[List[str]], int], written_counts: Dict[str, int]) -> None:
    if not lines_buf:
        return

    send_batch(lines_buf)
    for line in lines_buf:
        ric_start = line.find("ric=") + 4
        ric_end = line.find(",", ric_start)
        ric = line[ric_start:ric_end]
        if ric in written_counts:
            written_counts[ric] += 1

    lines_buf.clear()


def _subscribe_contracts(ib: IB, contracts: List[Tuple], state: Dict[str, object]) -> List[Tuple[Ticker, Contract]]:
    tickers: List[Tuple[Ticker, Contract]] = []
    for contract, ric_label, expiry_date in contracts:
        state["tick_counts"][ric_label] = 0
        state["dup_counts"][ric_label] = 0
        state["written_counts"][ric_label] = 0
        state["last_fields"][ric_label] = ()

        ticker = ib.reqMktData(contract, '', False, False)
        tickers.append((ticker, contract))

        def make_handler(contract: Contract, label: str, expiry: str):
            def on_tick(ticker):
                state["tick_counts"][label] += 1
                cur = (
                    ticker.bid if (ticker.bid is not None and ticker.bid == ticker.bid) else None,
                    ticker.ask if (ticker.ask is not None and ticker.ask == ticker.ask) else None,
                    ticker.last if (ticker.last is not None and ticker.last == ticker.last) else None,
                    ticker.bidSize if (ticker.bidSize is not None and ticker.bidSize == ticker.bidSize) else None,
                    ticker.askSize if (ticker.askSize is not None and ticker.askSize == ticker.askSize) else None,
                    ticker.lastSize if (ticker.lastSize is not None and ticker.lastSize == ticker.lastSize) else None,
                )
                if cur == state["last_fields"][label]:
                    state["dup_counts"][label] += 1
                    return
                state["last_fields"][label] = cur
                line = _build_ilp_line(contract, ticker, label, expiry)
                if line:
                    state["lines_buf"].append(line)
            return on_tick

        ticker.updateEvent += make_handler(contract, ric_label, expiry_date)
        logger.info("  Subscribed: %s (expiry: %s)", ric_label, expiry_date)

    return tickers


def _log_stream_status(start_time: float, state: Dict[str, object], last_status_time: float) -> float:
    now = time.time()
    if now - last_status_time < 30.0:
        return last_status_time

    elapsed = int(now - start_time)
    total_ticks = sum(state["tick_counts"].values())
    total_written = sum(state["written_counts"].values())
    total_dupes = sum(state["dup_counts"].values())
    per = " ".join(f"{r}:{state['tick_counts'][r]}" for r in sorted(state["tick_counts"]))
    logger.info("[%ds] ticks: %d (%s) | written: %d | dupes: %d",
                elapsed, total_ticks, per, total_written, total_dupes)
    return now


def _stream_live_ticks(
    ib: IB,
    contracts: List[Tuple],
    duration_secs: int,
    send_batch: Callable[[List[str]], int],
) -> Dict[str, int]:
    """Stream live L1 tick data from multiple IBKR contracts to QuestDB."""
    ib.reqMarketDataType(3)  # DELAYED — paper account

    state: Dict[str, object] = {
        "tick_counts": {},
        "dup_counts": {},
        "written_counts": {},
        "last_fields": {},
        "lines_buf": [],
    }
    tickers = _subscribe_contracts(ib, contracts, state)
    running = True
    last_status_time = time.time()

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
            if len(state["lines_buf"]) >= 100 or elapsed_since_flush >= 1.0:
                _flush_pending_lines(state["lines_buf"], send_batch, state["written_counts"])
                last_flush = now

            last_status_time = _log_stream_status(start_time, state, last_status_time)
            ib.sleep(0.05)

    finally:
        signal.signal(signal.SIGINT, original_sigint)

        for _, contract in tickers:
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass

        _flush_pending_lines(state["lines_buf"], send_batch, state["written_counts"])

        elapsed = int(time.time() - start_time)
        total_ticks = sum(state["tick_counts"].values())
        total_written = sum(state["written_counts"].values())
        total_dupes = sum(state["dup_counts"].values())
        logger.info("\nStreaming complete after %ds.", elapsed)
        logger.info("Total ticks: %d | written: %d | dupes skipped: %d",
                     total_ticks, total_written, total_dupes)
        for ric in sorted(state["tick_counts"]):
            logger.info("  %s: %d ticks, %d dupes, %d written",
                        ric, state["tick_counts"][ric], state["dup_counts"][ric], state["written_counts"][ric])

    return state["written_counts"]
