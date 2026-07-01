#!/usr/bin/env python3
"""
utils — Shared utilities for IBKR data tools
==================================================
Contract building, date parsing, and RIC resolution.
No IB connection logic — connections are managed by SessionManager.
"""

import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple

from ib_insync import Contract, Future, Stock

from logger import get_logger

logger = get_logger(__name__)


# ── defaults ────────────────────────────────────────────────────────────────
BAR_SIZE = "1 min"
WHAT_TO_SHOW = "TRADES"
USE_RTH = True
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── date range parsing ──────────────────────────────────────────────────────

def parse_date_range(date_arg: str) -> Tuple[datetime, datetime]:
    """Parse a yyyy-mm-dd:yyyy-mm-dd date range string.

    Args:
        date_arg: Date range in the format "YYYY-MM-DD:YYYY-MM-DD".

    Returns:
        A (start_date, end_date) tuple of datetime objects.

    Raises:
        SystemExit: If the string is malformed or start > end.
    """
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

def _month_map() -> dict:
    """Return the RIC month-code to month-number mapping."""
    return {
        "H": "03", "M": "06", "U": "09", "Z": "12",
        "F": "01", "G": "02", "J": "04", "K": "05",
        "N": "07", "Q": "08", "V": "10", "X": "11",
    }


def build_ric_contract(
    ric: str,
    exchange: str = "CME",
    sec_type: str = "FUT",
    currency: str = "USD",
    multiplier: Optional[str] = None,
) -> Contract:
    """Build an ib_insync contract from a RIC-style instrument code.

    RIC format for futures: root symbol + month code + year digit,
    e.g. ESU6 = ES Sep 2026.

    If sec_type is not FUT, creates a Stock contract instead.

    Args:
        ric: RIC string (e.g. "ESU6").
        exchange: Exchange name (default "CME").
        sec_type: Security type: "FUT" or "STK".
        currency: Currency code (default "USD").
        multiplier: Optional contract multiplier override.

    Returns:
        An ib_insync.Contract (either Future or Stock).

    Raises:
        SystemExit: If the RIC is too short or the month code is invalid.
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

def resolve_contracts(
    ib,
    rics: List[str],
    exchange: str = "CME",
    sec_type: str = "FUT",
    currency: str = "USD",
    multiplier: Optional[str] = None,
) -> List[Tuple]:
    """Resolve one or more RICs via reqContractDetails.

    Returns a list of (resolved_contract, ric_label, expiry_date) tuples.
    RICs that fail to resolve are skipped with a warning.

    Args:
        ib: Connected ib_insync.IB instance.
        rics: List of RIC strings (e.g. ["ESU6", "NQU6"]).
        exchange: Exchange name forwarded to build_ric_contract.
        sec_type: Security type forwarded to build_ric_contract.
        currency: Currency code forwarded to build_ric_contract.
        multiplier: Optional multiplier forwarded to build_ric_contract.

    Returns:
        A list of (contract, ric_label, expiry_date) tuples.
    """
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


def get_contract(ib, args) -> Tuple[Contract, str, str]:
    """Build and resolve a single contract from CLI args.

    Requires an already-connected IB instance.  Uses the --ric argument
    (which may be a list or a single string).

    Args:
        ib: Connected ib_insync.IB instance.
        args: An argparse.Namespace with --ric, --exchange, --sec-type,
            --currency, and --multiplier attributes.

    Returns:
        A tuple of (resolved_contract, ric_label, expiry_date).

    Raises:
        SystemExit: If the contract cannot be resolved.
    """
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
