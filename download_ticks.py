"""
IBKR Live Tick Streamer — library module
=========================================
Provides tick-streaming functions imported by run_ibkr.py.

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


# ── contract resolution helper ─────────────────────────────────────────────

def _resolve_single(ib, ric: str, exchange: str, sec_type: str,
                    currency: str, multiplier) -> Tuple:
    """Resolve one RIC and return (contract, ric_label, expiry_date)."""
    contract = build_ric_contract(ric, exchange, sec_type, currency, multiplier)
    print(f"Resolving contract: {contract} ...")
    details = ib.reqContractDetails(contract)
    if not details:
        print(f"ERROR: Could not resolve contract {contract}", file=sys.stderr)
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
    print(f"Resolved: {resolved.localSymbol} ({resolved.symbol}) "
          f"Exchange={resolved.exchange} Currency={resolved.currency} "
          f"Multiplier={resolved.multiplier} Expiry={expiry_date}")
    return resolved, ric_label, expiry_date


# ── live streaming loop ─────────────────────────────────────────────────────

def _stream_live_ticks(
    ib,
    contracts: List[Tuple],  # [(contract, ric_label, expiry_date), ...]
    duration_secs: int,
    questdb_url: str,
) -> Dict[str, dict]:
    """Stream live L1 tick data from multiple IBKR contracts to QuestDB.

    Returns per-contract stats dict keyed by ric_label.
    """
    ib.reqMarketDataType(3)  # DELAYED — paper account has no live data subscription

    # Per-contract state
    tickers = []
    tick_counts: Dict[str, int] = {}
    dup_counts: Dict[str, int] = {}
    written_counts: Dict[str, int] = {}
    _last_fields: Dict[str, tuple] = {}  # ric_label -> field tuple
    lines_buf: List[str] = []
    running = True
    last_status_time = time.time()

    def _fv(val):
        """Normalize value: None/NaN → None."""
        return val if (val is not None and val == val) else None

    for contract, ric_label, expiry_date in contracts:
        tick_counts[ric_label] = 0
        dup_counts[ric_label] = 0
        written_counts[ric_label] = 0
        _last_fields[ric_label] = ()

        ticker = ib.reqMktData(contract, '', False, False)
        tickers.append((ticker, contract))

        # Closure captures per-contract ric_label, expiry_date
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
        print(f"  Subscribed: {ric_label} (expiry: {expiry_date})")

    def _signal_handler(signum, frame):
        nonlocal running
        print("\nCtrl+C received. Shutting down...")
        running = False

    original_sigint = signal.signal(signal.SIGINT, _signal_handler)

    start_time = time.time()
    last_flush = start_time

    print(f"\nStreaming {len(contracts)} contract(s), duration: {duration_secs}s (0 = until Ctrl+C)\n")

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
                    from ibkr_utils import _send_ilp_batch
                    _send_ilp_batch(lines_buf, questdb_url)
                    # Increment per-contract written counts from this batch
                    for line in lines_buf:
                        # Parse ric= from ILP line: "measurement,ric=XXX,..."
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
                print(f"[{elapsed}s] ticks: {total_ticks} ({per}) | written: {total_written} | dupes: {total_dupes}")
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
            from ibkr_utils import _send_ilp_batch
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
        print(f"\nStreaming complete after {elapsed}s.")
        print(f"Total ticks: {total_ticks} | written: {total_written} | dupes skipped: {total_dupes}")
        for ric in sorted(tick_counts):
            print(f"  {ric}: {tick_counts[ric]} ticks, {dup_counts[ric]} dupes, {written_counts[ric]} written")

    return written_counts


# ── entry point for run_ibkr.py ────────────────────────────────────────────

def main_ticks(args):
    """Entry point for tick streaming mode. Supports multiple --ric values."""
    ib = connect_ib(args.host, args.port, args.client_id)

    try:
        contracts = []
        for ric in args.ric:
            resolved, label, expiry = _resolve_single(
                ib, ric, args.exchange, args.sec_type,
                args.currency, args.multiplier,
            )
            contracts.append((resolved, label, expiry))

        _stream_live_ticks(
            ib, contracts,
            args.duration,
            "http://127.0.0.1:9000",
        )

    finally:
        print("Disconnecting...")
        ib.disconnect()
        print("Disconnected.")
