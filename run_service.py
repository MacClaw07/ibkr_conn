#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
from pathlib import Path

# ── Auto-reinvoke with project venv if running system Python ──
_venv_python = Path(__file__).resolve().parent / "venv" / "bin" / "python3"
if _venv_python.exists() and not sys.executable.startswith(str(_venv_python)):
    os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)
"""Single CLI entry point for IBKR data tools and Gateway lifecycle.

Modes:
    bars    — historical bar download
    stream  — keepalive-aware tick streaming loop
    status  — show Gateway/QuestDB status
    start   — start Gateway + QuestDB
    stop    — stop Gateway + QuestDB

Examples:
    %(prog)s --mode bars --date 2026-06-22:2026-06-26 --ric ESU6
    %(prog)s --mode stream
    %(prog)s --mode stream --ric ESU6 NQU6 --duration 3600
    %(prog)s --mode status
    %(prog)s --mode start
    %(prog)s --mode stop
"""

import argparse
import sys
from pathlib import Path

from logger import configure_pipeline_logging, get_logger
from session_manager import SessionManager
from data_downloader import DataDownloader

logger = get_logger(__name__)


def _clean_stale_pycache():
    """Remove .pyc files for modules whose .py source no longer exists."""
    cache_dir = Path(__file__).resolve().parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    project_dir = Path(__file__).resolve().parent
    for pyc in cache_dir.glob("*.pyc"):
        base = pyc.name.split(".cpython")[0]
        source_py = project_dir / f"{base}.py"
        if not source_py.exists():
            logger.info("Cleaning stale pycache: %s", pyc)
            pyc.unlink()


def build_ibkr_parser() -> argparse.ArgumentParser:
    """Build the unified argument parser for all modes."""
    epilog = __doc__

    parser = argparse.ArgumentParser(
        description="IBKR data tools & Gateway lifecycle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )

    # ── Mode selector ──
    parser.add_argument(
        "--mode",
        required=True,
        choices=["bars", "stream", "status", "start", "stop"],
        help="Operation mode",
    )

    # ── Instrument selection ──
    parser.add_argument(
        "--ric",
        nargs="+",
        metavar="RIC",
        help="One or more RIC codes for futures, e.g. ESU6 NQU6 CLU6",
    )

    parser.add_argument("--exchange", default="CME", help="Exchange (default: CME)")
    parser.add_argument("--sec-type", default="FUT", help="Security type: FUT, STK, etc.")
    parser.add_argument("--currency", default="USD", help="Currency (default: USD)")
    parser.add_argument("--multiplier", type=str, default=None, help="Contract multiplier")

    # ── Bars mode options ──
    parser.add_argument("--date", help="Date range: yyyy-mm-dd:yyyy-mm-dd (bars mode)")
    parser.add_argument("--format", choices=["questdb", "csv"], default="questdb",
                        help="Output format (bars mode, default: questdb)")
    parser.add_argument("--bar-size", default="1 min",
                        help="Bar size (bars mode, default: 1 min)")
    parser.add_argument("--what-to-show", default="TRADES",
                        help="Data type (bars mode, default: TRADES)")
    parser.add_argument("--use-rth", action="store_true", default=True,
                        help="Regular trading hours only (bars mode)")
    parser.add_argument("--all-hours", action="store_true",
                        help="Include extended hours (bars mode, overrides --use-rth)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output CSV path (bars mode)")

    # ── Stream mode options ──
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        metavar="N",
        help="Run for N seconds then disconnect (stream mode, default: 0 = until Ctrl+C)",
    )

    # ── Connection ──
    parser.add_argument("--host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=100, help="Client ID")

    return parser


def _handle_status(args, mgr):
    """Print Gateway, QuestDB, and keepalive status."""
    s = mgr.get_status()
    logger.info("=" * 40)
    logger.info("IBKR Pipeline Status")
    logger.info("=" * 40)
    q = s["questdb"]
    logger.info("QuestDB:     %s (port %d, PID %s)",
                "RUNNING" if q["running"] else "STOPPED",
                q["port"], q["pid"] or "N/A")
    g = s["gateway"]
    logger.info("Gateway:     %s (port %d, PID %s)",
                "RUNNING" if g["running"] else "STOPPED",
                g["port"], g["pid"] or "N/A")
    logger.info("Keepalive:   %s",
                "ENABLED" if s["keepalive"] else "DISABLED")


def main():
    """Parse CLI args and dispatch to the appropriate mode handler."""
    configure_pipeline_logging()
    _clean_stale_pycache()
    parser = build_ibkr_parser()
    args = parser.parse_args()

    mgr = SessionManager()
    downloader = DataDownloader()

    if args.mode == "bars":
        if not args.ric:
            parser.error("--ric is required for --mode bars")
        if not args.date:
            parser.error("--date is required for --mode bars")
        downloader.download_bars(args)
    elif args.mode == "stream":
        downloader.start_streaming(args)
    elif args.mode == "status":
        _handle_status(args, mgr)
    elif args.mode == "start":
        mgr.start_gateway()
    elif args.mode == "stop":
        mgr.stop_gateway()


if __name__ == "__main__":
    main()
