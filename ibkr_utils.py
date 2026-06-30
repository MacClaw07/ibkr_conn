#!/usr/bin/env python3
"""
ibkr_utils — Shared utilities for IBKR data tools
==================================================
Connection, contract resolution, and helpers shared between
download_bars.py and download_ticks.py.
"""

import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple

from ib_insync import IB, Contract, Future, Stock

from pipeline_logger import get_logger

logger = get_logger(__name__)


# ── defaults ────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 4002
CLIENT_ID = 100
BAR_SIZE = "1 min"
WHAT_TO_SHOW = "TRADES"
USE_RTH = True
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── keepalive guard ─────────────────────────────────────────────────────────

##
# Check if .ibkr_keepalive exists and is set to "true".
#
# Prints an error and exits if keepalive is not enabled.  Call this
# before any IB API connection attempt.
#
# @param exit_code: Exit code to use if keepalive is disabled.
def require_keepalive(exit_code: int = 1):
    keepalive_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ibkr_keepalive")
    if not os.path.isfile(keepalive_path):
        logger.error("keepalive is not enabled -- aborting IB API calls")
        sys.exit(exit_code)
    try:
        value = open(keepalive_path).read().strip().lower()
    except OSError:
        logger.error("keepalive is not enabled -- aborting IB API calls")
        sys.exit(exit_code)
    if value != "true":
        logger.error("keepalive is not enabled -- aborting IB API calls")
        sys.exit(exit_code)


# ── connection ──────────────────────────────────────────────────────────────

##
# Connect to IB Gateway/TWS and return the IB instance.
#
# Checks keepalive first; prints connection info; exits on failure.
#
# @param host: IB Gateway hostname or IP.
# @param port: IB Gateway API port.
# @param client_id: Client ID to use for the connection.
# @return: A connected ib_insync.IB instance.
def connect_ib(host: str = HOST, port: int = PORT, client_id: int = CLIENT_ID) -> IB:
    require_keepalive()
    ib = IB()
    try:
        logger.info("Connecting to IB Gateway at %s:%d ...", host, port)
        ib.connect(host, port, clientId=client_id, readonly=True)
        logger.info("Connected. Account: %s", ib.managedAccounts())
        return ib
    except Exception as e:
        logger.error("Could not connect to IB Gateway: %s", e)
        logger.info("Is the Gateway running? Try: ~/.local/bin/ibkr-start.sh")
        sys.exit(1)


# ── date range parsing ──────────────────────────────────────────────────────

##
# Parse a yyyy-mm-dd:yyyy-mm-dd date range string.
#
# @param date_arg: Date range in the format "YYYY-MM-DD:YYYY-MM-DD".
# @return: A (start_date, end_date) tuple of datetime objects.
# @raise SystemExit: If the string is malformed or start > end.
def parse_date_range(date_arg: str) -> Tuple[datetime, datetime]:
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


# ── contract builder ─────────────────────────────────────────────────────────

##
# Return the RIC month-code to month-number mapping.
#
# @return: A dict mapping single-letter month codes to two-digit month strings.
def _month_map() -> dict:
    return {
        "H": "03", "M": "06", "U": "09", "Z": "12",
        "F": "01", "G": "02", "J": "04", "K": "05",
        "N": "07", "Q": "08", "V": "10", "X": "11",
    }


##
# Build an ib_insync contract from a RIC-style instrument code.
#
# RIC format for futures: root symbol + month code + year digit,
# e.g. ESU6 = ES Sep 2026.
#
# If sec_type is not FUT, creates a Stock contract instead.
#
# @param ric: RIC string (e.g. "ESU6").
# @param exchange: Exchange name (default "CME").
# @param sec_type: Security type: "FUT" or "STK".
# @param currency: Currency code (default "USD").
# @param multiplier: Optional contract multiplier override.
# @return: An ib_insync.Contract (either Future or Stock).
# @raise SystemExit: If the RIC is too short or the month code is invalid.
def build_ric_contract(
    ric: str,
    exchange: str = "CME",
    sec_type: str = "FUT",
    currency: str = "USD",
    multiplier: Optional[str] = None,
) -> Contract:
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

##
# Resolve one or more RICs via reqContractDetails.
#
# Returns a list of (resolved_contract, ric_label, expiry_date) tuples.
# RICs that fail to resolve are skipped with a warning.
#
# @param ib: Connected ib_insync.IB instance.
# @param rics: List of RIC strings (e.g. ["ESU6", "NQU6"]).
# @param exchange: Exchange name forwarded to build_ric_contract.
# @param sec_type: Security type forwarded to build_ric_contract.
# @param currency: Currency code forwarded to build_ric_contract.
# @param multiplier: Optional multiplier forwarded to build_ric_contract.
# @return: A list of (contract, ric_label, expiry_date) tuples.
def resolve_contracts(
    ib,
    rics: List[str],
    exchange: str = "CME",
    sec_type: str = "FUT",
    currency: str = "USD",
    multiplier: Optional[str] = None,
) -> List[Tuple]:
    results: List[Tuple] = []
    for ric in rics:
        contract = build_ric_contract(ric, exchange, sec_type, currency, multiplier)
        logger.info("Resolving %s...", ric)
        details = ib.reqContractDetails(contract)
        if not details:
            logger.warning("Could not resolve %s, skipping", ric)
            continue
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
        results.append((resolved, ric_label, expiry_date))
        logger.info("  Resolved: %s (expiry: %s)", ric_label, expiry_date)
    return results


##
# Build and resolve a contract from CLI args via reqContractDetails.
#
# Requires an already-connected IB instance.  Uses the --ric argument
# (which may be a list or a single string).
#
# @param ib: Connected ib_insync.IB instance.
# @param args: An argparse.Namespace with --ric, --exchange, --sec-type,
#   --currency, and --multiplier attributes.
# @return: A tuple of (resolved_contract, ric_label, expiry_date).
# @raise SystemExit: If the contract cannot be resolved.
def get_contract(ib: IB, args) -> Tuple[Contract, str, str]:
    ric_val = args.ric if isinstance(args.ric, str) else args.ric[0]
    contract = build_ric_contract(
        ric_val,
        exchange=args.exchange,
        sec_type=args.sec_type,
        currency=args.currency,
        multiplier=args.multiplier,
    )

    logger.info("Resolving contract: %s ...", contract)
    details = ib.reqContractDetails(contract)
    if not details:
        logger.error("Could not resolve contract %s", contract)
        sys.exit(1)

    cd = details[0]
    resolved = cd.contract

    ric_label = resolved.localSymbol if resolved.localSymbol else ric_val.strip().upper()

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
    return resolved, ric_label, expiry_date
