#!/usr/bin/env python3
"""
utils — Shared utilities for IBKR data tools
==================================================
Contract building, date parsing, and RIC resolution.
No IB connection logic — connections are managed by SessionManager.
"""

import os
import re
import sys
from datetime import datetime
from typing import Any, List, Optional, Tuple

from ib_insync import Contract, Future, FuturesOption, Stock

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


def resolve_option_underlying(option_ric: str) -> str:
    """Return the underlying futures RIC for a CME-style option RIC.

    Examples:
        "ESU62000C" -> "ESU6"
        "ESU6" -> "ESU6"
    """
    if not isinstance(option_ric, str):
        raise TypeError("option_ric must be a string")

    ric = option_ric.strip().upper()
    if not ric:
        raise ValueError("option_ric cannot be empty")

    future_match = re.fullmatch(r"([A-Z0-9]+)([A-Z])([0-9])", ric)
    if future_match:
        return ric

    # CME RIC format: ESU67500C or EW3U67500C
    option_match = re.fullmatch(r"([A-Z0-9]+)([A-Z])([0-9])(\d+)([CP])", ric)
    if option_match:
        return f"{option_match.group(1)}{option_match.group(2)}{option_match.group(3)}"

    # IBKR localSymbol format: ESU6 C7500 or EW3U6 C7500 (root may contain digits)
    option_match = re.fullmatch(r"([A-Z0-9]+)([A-Z])([0-9])\s+([CP])(\d+)", ric)
    if option_match:
        return f"{option_match.group(1)}{option_match.group(2)}{option_match.group(3)}"

    raise ValueError(f"Unsupported option RIC format: {option_ric}")


def _parse_future_ric(ric: str) -> Tuple[str, str]:
    """Parse a futures-style RIC into the underlying root symbol and expiry."""
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
    return root, contract_month_str


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
    sec_type = sec_type.upper()
    if sec_type == "FUT":
        root, contract_month_str = _parse_future_ric(ric)

        c = Future(
            symbol=root,
            lastTradeDateOrContractMonth=contract_month_str,
            exchange=exchange,
            currency=currency,
        )
        if multiplier:
            c.multiplier = multiplier
        return c

    if sec_type in ("OPT", "FOP"):
        option_ric = ric.strip().upper()
        option_match = re.fullmatch(r"([A-Z]+)([A-Z])([0-9])(\d+)([CP])", option_ric)
        if not option_match:
            raise SystemExit(f"ERROR: unsupported option RIC format: '{ric}'")

        root, contract_month_str = _parse_future_ric(
            f"{option_match.group(1)}{option_match.group(2)}{option_match.group(3)}"
        )
        c = FuturesOption(
            symbol=root,
            lastTradeDateOrContractMonth=contract_month_str,
            strike=float(option_match.group(4)),
            right=option_match.group(5),
            exchange=exchange,
            currency=currency,
        )
        if multiplier:
            c.multiplier = multiplier
        return c

    return Stock(symbol=ric, exchange=exchange, currency=currency)


# ── contract resolution ─────────────────────────────────────────────────────

def resolve_contracts(
    ib,
    contracts: List[dict],
) -> List[Tuple]:
    """Resolve one or more contract descriptors via reqContractDetails.

    Each entry in contracts must be a dict containing at least a RIC and the
    contract parameters needed to build the IB contract.

    Returns a list of (resolved_contract, ric_label, expiry_date) tuples.
    RICs that fail to resolve are skipped with a warning.
    """
    results: List[Tuple] = []
    for entry in contracts:
        if not isinstance(entry, dict):
            logger.warning("Skipping unsupported contract entry: %s", entry)
            continue

        ric = entry.get("ric")
        if not isinstance(ric, str) or not ric.strip():
            logger.warning("Skipping contract entry without a valid 'ric': %s", entry)
            continue

        ric = ric.strip()
        contract_exchange = entry.get("exchange") or entry.get("exch") or "CME"
        contract_sec_type = entry.get("sec_type") or entry.get("secType") or "FUT"
        contract_currency = entry.get("currency") or "USD"
        contract_multiplier = entry.get("multiplier")

        contract = build_ric_contract(
            ric,
            contract_exchange,
            contract_sec_type,
            contract_currency,
            contract_multiplier,
        )
        logger.info("Resolving %s...", ric)
        details = ib.reqContractDetails(contract)
        if not details:
            logger.warning("Could not resolve %s, skipping", ric)
            continue
        cd = details[0]
        resolved_contract = cd.contract
        if contract_sec_type in ("OPT", "FOP"):
            ric_label = ric.strip().upper()
        else:
            ric_label = resolved_contract.localSymbol if resolved_contract.localSymbol else ric.strip().upper()
        expiry_date = ""
        ltd = getattr(resolved_contract, 'lastTradeDateOrContractMonth', '')
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
        results.append((resolved_contract, ric_label, expiry_date))
        logger.info("  Resolved: %s (expiry: %s)", ric_label, expiry_date)
    return results


def get_contract(ib) -> Tuple[Contract, str, str]:
    """Build and resolve a single contract from tick config.

    Loads the first contract from configs/download_live_tick.json
    and resolves it using the provided IB instance.

    Args:
        ib: Connected ib_insync.IB instance.

    Returns:
        A tuple of (resolved_contract, ric_label, expiry_date).

    Raises:
        SystemExit: If the contract cannot be loaded or resolved.
    """
    contracts = load_tick_config()
    if not contracts:
        logger.error("No contracts found in config")
        sys.exit(1)

    cfg = contracts[0]
    ric_val = cfg["ric"]
    
    # Map config keys to build_ric_contract parameter names
    exchange = cfg.get("exchange") or cfg.get("exch")
    sec_type = cfg.get("sec_type") or cfg.get("secType")
    currency = cfg.get("currency")
    multiplier = cfg.get("multiplier")
    
    contract = build_ric_contract(
        ric_val,
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


def load_tick_config() -> list:
    """Load and validate live tick configuration from configs/download_live_tick.json.

    Returns a list of validated contract entries.
    Exits the process with an error message on failure (mirrors previous behavior).
    """
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
        entry = {
            "ric": c["ric"].strip(),
            "duration_seconds": c.get("duration_seconds", 0),
        }
        for key in ("exchange", "exch", "sec_type", "secType", "currency", "multiplier"):
            if key in c:
                entry[key] = c[key]
        validated.append(entry)

    return validated
