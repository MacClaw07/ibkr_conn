#!/usr/bin/env python3
"""
ibkr_utils — Shared utilities for IBKR data tools
==================================================
Connection, contract resolution, QuestDB ILP writers, and helpers
shared between download_bars.py and download_ticks.py.
"""

import argparse
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import List, Optional, Tuple

from ib_insync import IB, Contract, Future, Stock, BarData


# ── defaults ────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 4002
CLIENT_ID = 100
BAR_SIZE = "1 min"
WHAT_TO_SHOW = "TRADES"
USE_RTH = True
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── connection ──────────────────────────────────────────────────────────────

def connect_ib(host: str = HOST, port: int = PORT, client_id: int = CLIENT_ID) -> IB:
    """Connect to IB Gateway/TWS and return the IB instance.

    Prints connection info; exits on failure.
    """
    ib = IB()
    try:
        print(f"Connecting to IB Gateway at {host}:{port} ...")
        ib.connect(host, port, clientId=client_id)
        print(f"Connected. Account: {ib.managedAccounts()}")
        return ib
    except Exception as e:
        print(f"ERROR: Could not connect to IB Gateway: {e}", file=sys.stderr)
        print("Is the Gateway running? Try: ~/.local/bin/ibkr-start.sh", file=sys.stderr)
        sys.exit(1)


# ── date range parsing ──────────────────────────────────────────────────────

def parse_date_range(date_arg: str) -> Tuple[datetime, datetime]:
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


# ── contract builders ───────────────────────────────────────────────────────

def _month_map():
    """Return the RIC month-code → month-number map."""
    return {
        "H": "03", "M": "06", "U": "09", "Z": "12",
        "F": "01", "G": "02", "J": "04", "K": "05",
        "N": "07", "Q": "08", "V": "10", "X": "11",
    }


def build_es_contract(contract_month: str) -> Future:
    """Build a CME ES future contract.

    Args:
        contract_month: 'YYYYMM' e.g. '202609'
    """
    return Future(
        symbol="ES",
        lastTradeDateOrContractMonth=contract_month,
        exchange="CME",
    )


def build_ric_contract(
    ric: str,
    exchange: str = "CME",
    sec_type: str = "FUT",
    currency: str = "USD",
    multiplier: Optional[str] = None,
) -> Contract:
    """Build a contract from RIC-like parameters.

    RIC format for futures: root symbol + month code + year digit, e.g. ESU6 = ES Sep 2026.
    If sec_type is not FUT, creates a Stock contract.
    """
    if sec_type.upper() == "FUT":
        ric = ric.strip().upper()
        if len(ric) < 3:
            raise SystemExit(f"ERROR: RIC too short: '{ric}'")

        month_code = ric[-2]
        year_digit = ric[-1]
        root = ric[:-2]

        month_map = _month_map()
        if month_code not in month_map:
            raise SystemExit(
                f"ERROR: unknown month code '{month_code}' in RIC '{ric}'\n"
                f"       valid codes: H,M,U,Z (quarterly) or F,G,J,K,N,Q,V,X"
            )

        month_num = month_map[month_code]
        current_year = datetime.now().year
        decade_base = (current_year // 10) * 10
        year_candidate = decade_base + int(year_digit)
        if year_candidate < current_year - 2:
            year_candidate += 10

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
        return Stock(symbol=ric, exchange=exchange, currency=currency)


# ── contract resolution ─────────────────────────────────────────────────────

def get_contract(ib: IB, args) -> Tuple[Contract, str, str]:
    """Build and resolve a contract from CLI args via reqContractDetails.

    Requires an already-connected IB instance.

    Args:
        ib: Connected IB instance.
        args: argparse.Namespace with --es, --ric, --exchange, --sec-type,
              --currency, --multiplier attributes.

    Returns:
        (resolved_contract, ric_label, expiry_date)
        - ric_label: authoritative localSymbol (RIC) from IB, e.g. 'ESU6'
        - expiry_date: YYYY-MM-DD string, may be empty
    """
    if args.es:
        contract = build_es_contract(args.es)
        initial_label = f"ES{args.es}"
    else:
        # args.ric may be a list (ticks mode) or single string (bars mode)
        ric_val = args.ric if isinstance(args.ric, str) else args.ric[0]
        contract = build_ric_contract(
            ric_val,
            exchange=args.exchange,
            sec_type=args.sec_type,
            currency=args.currency,
            multiplier=args.multiplier,
        )
        initial_label = ric_val.strip().upper()

    print(f"Resolving contract: {contract} ...")
    details = ib.reqContractDetails(contract)
    if not details:
        print(f"ERROR: Could not resolve contract {contract}", file=sys.stderr)
        sys.exit(1)

    cd = details[0]
    resolved = cd.contract

    # Use the resolved localSymbol as the authoritative RIC label
    ric_label = resolved.localSymbol if resolved.localSymbol else initial_label

    # Extract expiry date from contract details
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

    print(f"Resolved: {resolved.localSymbol} ({resolved.symbol}) "
          f"Exchange={resolved.exchange} Currency={resolved.currency} "
          f"Multiplier={resolved.multiplier} Expiry={expiry_date}")
    return resolved, ric_label, expiry_date


# ── QuestDB ILP writers ─────────────────────────────────────────────────────

def _format_ilp_timestamp(dt: datetime) -> int:
    """Convert a datetime to nanoseconds since epoch (ILP timestamp)."""
    return int(dt.timestamp() * 1_000_000_000)


def _send_ilp_batch(lines: List[str], questdb_url: str) -> int:
    """Post a batch of ILP lines to QuestDB /write.

    Returns number of lines successfully written.
    """
    if not lines:
        return 0

    body = "\n".join(lines).encode("utf-8")
    write_url = f"{questdb_url}/write"

    req = urllib.request.Request(
        write_url,
        data=body,
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return len(lines)
            else:
                print(f"  WARNING: QuestDB /write returned HTTP {resp.status}",
                      file=sys.stderr)
                return 0
    except urllib.error.URLError as e:
        print(f"  ERROR writing batch to QuestDB: {e}", file=sys.stderr)
        return 0


def write_bars_to_questdb(
    bars: List[BarData],
    ric_label: str,
    expiry_date: str,
    questdb_url: str = "http://127.0.0.1:9000",
) -> int:
    """Write historical BarData to QuestDB futures_hist table via ILP.

    Args:
        bars: List of BarData from ib_insync.
        ric_label: RIC label e.g. 'ESU6'.
        expiry_date: Expiry date as YYYY-MM-DD.
        questdb_url: QuestDB REST base URL.

    Returns:
        Number of rows written.
    """
    if not bars:
        return 0

    measurement = "futures_hist"
    lines = []

    for b in bars:
        ts_ns = _format_ilp_timestamp(b.date)

        fields = []
        if b.open is not None and b.open == b.open:
            fields.append(f"open={b.open}")
        if b.high is not None and b.high == b.high:
            fields.append(f"high={b.high}")
        if b.low is not None and b.low == b.low:
            fields.append(f"low={b.low}")
        if b.close is not None and b.close == b.close:
            fields.append(f"close={b.close}")
        if b.volume is not None:
            fields.append(f"volume={int(b.volume)}i")
        if b.barCount is not None:
            fields.append(f"bar_count={int(b.barCount)}i")
        if b.average is not None and b.average == b.average:
            fields.append(f"average={b.average}")

        if not fields:
            continue

        line = f"{measurement},ric={ric_label},expiry={expiry_date} {','.join(fields)} {ts_ns}"
        lines.append(line)

    # Batch-send in groups of 1000
    batch_size = 1000
    total_written = 0

    for i in range(0, len(lines), batch_size):
        batch = lines[i:i + batch_size]
        total_written += _send_ilp_batch(batch, questdb_url)

    return total_written


def write_ticks_to_questdb(
    ticks: List[dict],
    ric_label: str,
    expiry_date: str,
    questdb_url: str = "http://127.0.0.1:9000",
) -> int:
    """Write tick data dicts to QuestDB futures_tick table via ILP.

    Each tick dict should have keys:
        time (datetime), bid, ask, last, bid_size, ask_size, last_size

    Returns number of rows written.
    """
    if not ticks:
        return 0

    measurement = "futures_tick"
    lines = []

    for t in ticks:
        ts_ns = _format_ilp_timestamp(t["time"])

        fields = []

        def _ok(val):
            return val is not None and val == val  # not NaN

        if _ok(t.get("bid")):
            fields.append(f"bid={t['bid']}")
        if _ok(t.get("ask")):
            fields.append(f"ask={t['ask']}")
        if _ok(t.get("last")):
            fields.append(f"last={t['last']}")
        if _ok(t.get("bid_size")):
            fields.append(f"bid_size={int(t['bid_size'])}i")
        if _ok(t.get("ask_size")):
            fields.append(f"ask_size={int(t['ask_size'])}i")
        if _ok(t.get("last_size")):
            fields.append(f"last_size={int(t['last_size'])}i")

        if not fields:
            continue

        line = f"{measurement},ric={ric_label},expiry={expiry_date} {','.join(fields)} {ts_ns}"
        lines.append(line)

    # Batch-send in groups of 1000
    batch_size = 1000
    total_written = 0

    for i in range(0, len(lines), batch_size):
        batch = lines[i:i + batch_size]
        total_written += _send_ilp_batch(batch, questdb_url)

    return total_written


# ── unified argument parser ─────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build and return the unified ArgumentParser for run_ibkr.

    Includes all arguments for both bars and ticks modes.
    """
    epilog = """
examples:
  %(prog)s --mode bars --date 2026-06-22:2026-06-26 --es 202609
  %(prog)s --mode bars --date 2026-06-22:2026-06-26 --ric ESU6
  %(prog)s --mode bars --date 2026-06-22:2026-06-26 --es 202609 --format csv
  %(prog)s --mode ticks --es 202609 --duration 10
  %(prog)s --mode ticks --ric ESU6 --duration 30
"""
    parser = argparse.ArgumentParser(
        description="IBKR data tools — single entry point for bars & ticks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )

    # ── Mode selector ──────────────────────────────────────────────────
    parser.add_argument(
        "--mode",
        required=True,
        choices=["bars", "ticks"],
        help="Operation mode: bars (historical OHLCV) or ticks (live L1 stream)",
    )

    # ── Instrument selection ───────────────────────────────────────────
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
        nargs="+",
        metavar="RIC",
        help="One or more RIC codes for futures, e.g. ESU6 NQU6 CLU6",
    )

    # --ric overrides
    parser.add_argument("--exchange", default="CME", help="Exchange (default: CME)")
    parser.add_argument("--sec-type", default="FUT", help="Security type: FUT, STK, etc.")
    parser.add_argument("--currency", default="USD", help="Currency (default: USD)")
    parser.add_argument("--multiplier", type=str, default=None, help="Contract multiplier")

    # ── Bars mode options ──────────────────────────────────────────────
    parser.add_argument("--date", help="Date range: yyyy-mm-dd:yyyy-mm-dd (bars mode)")
    parser.add_argument("--format", choices=["questdb", "csv"], default="questdb",
                        help="Output format (bars mode, default: questdb)")
    parser.add_argument("--bar-size", default=BAR_SIZE, help=f"Bar size (bars mode, default: {BAR_SIZE})")
    parser.add_argument("--what-to-show", default=WHAT_TO_SHOW,
                        help=f"Data type (bars mode, default: {WHAT_TO_SHOW})")
    parser.add_argument("--use-rth", action="store_true", default=USE_RTH,
                        help="Regular trading hours only (bars mode)")
    parser.add_argument("--all-hours", action="store_true",
                        help="Include extended hours (bars mode, overrides --use-rth)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output CSV path (bars mode, default: auto-generated)")

    # ── Ticks mode options ─────────────────────────────────────────────
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        metavar="N",
        help="Run for N seconds then disconnect (ticks mode, default: 0 = until Ctrl+C)",
    )

    # ── Connection (both modes) ────────────────────────────────────────
    parser.add_argument("--host", default=HOST, help=f"IB Gateway host (default: {HOST})")
    parser.add_argument("--port", type=int, default=PORT, help=f"IB Gateway port (default: {PORT})")
    parser.add_argument("--client-id", type=int, default=CLIENT_ID,
                        help=f"Client ID (default: {CLIENT_ID})")

    return parser
