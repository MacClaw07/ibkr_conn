#!/usr/bin/env python3
"""Single entry point for IBKR data download tools and Gateway lifecycle.

Modes:
    bars    — historical bar download (uses download_bars)
    ticks   — live L1 tick stream (uses download_ticks)
    stream  — keepalive-aware tick streaming loop (uses ibgateway)
    status  — show Gateway/QuestDB status
    start   — start Gateway + QuestDB
    stop    — stop Gateway + QuestDB

Examples:
    %(prog)s --mode bars --date 2026-06-22:2026-06-26 --ric ESU6
    %(prog)s --mode ticks --ric ESU6 --duration 30
    %(prog)s --mode stream
    %(prog)s --mode stream --ric ESU6 NQU6 --duration 3600
    %(prog)s --mode status
    %(prog)s --mode start
    %(prog)s --mode stop
"""

import argparse
import sys
import threading


def build_ibkr_parser():
    """Build the unified argument parser with all modes."""
    epilog = __doc__

    parser = argparse.ArgumentParser(
        description="IBKR data tools & Gateway lifecycle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )

    # ── Mode selector ──────────────────────────────────────────────────
    parser.add_argument(
        "--mode",
        required=True,
        choices=["bars", "ticks", "stream", "status", "start", "stop"],
        help="Operation mode",
    )

    # ── Instrument selection ───────────────────────────────────────────
    inst = parser.add_mutually_exclusive_group()
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

    # ── Ticks / Stream mode options ────────────────────────────────────
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        metavar="N",
        help="Run for N seconds then disconnect (ticks/stream mode, default: 0 = until Ctrl+C)",
    )

    # ── Connection ─────────────────────────────────────────────────────
    parser.add_argument("--host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=100, help="Client ID")

    return parser


def main():
    parser = build_ibkr_parser()
    args = parser.parse_args()

    if args.mode == "bars":
        if not args.ric and not args.es:
            parser.error("--ric or --es is required for --mode bars")
        if not args.date:
            parser.error("--date is required for --mode bars")

        # Delegate to download_bars, but first we need the args format
        # that download_bars expects (same attribute names)
        from download_bars import main_bars
        main_bars(args)

    elif args.mode == "ticks":
        if not args.ric and not args.es:
            parser.error("--ric or --es is required for --mode ticks")

        from download_ticks import main_ticks
        # Convert single --es to a --ric list so download_ticks works
        if args.es and not args.ric:
            # Build a RIC from the ES month string (e.g. 202609 → ESU6)
            # Actually let's just pass it through as-is since main_ticks expects --ric
            # We'll wrap args to have args.ric be a list
            from datetime import datetime
            ym = args.es
            year = int(ym[:4])
            month = int(ym[4:6])
            month_codes = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                           7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
            mc = month_codes[month]
            yd = str(year % 10)
            es_ric = f"ES{mc}{yd}"
            args.ric = [es_ric]

        main_ticks(args)

    elif args.mode == "stream":
        from ibgateway import stream_ticks_loop, ensure_gateway, is_keepalive_enabled

        if args.ric:
            # CLI override mode: use RICs directly, not config file
            if not is_keepalive_enabled():
                print("Keepalive is disabled; enable with --mode start first.",
                      file=sys.stderr)
                sys.exit(1)

            if not ensure_gateway():
                sys.exit(1)

            from ib_insync import IB
            from download_ticks import _resolve_single, _stream_live_ticks

            ib = IB()
            try:
                ib.connect("127.0.0.1", 4002, clientId=2,
                           readonly=True, timeout=10)
                contracts = []
                for ric in args.ric:
                    resolved, label, expiry = _resolve_single(
                        ib, ric, args.exchange, args.sec_type,
                        args.currency, args.multiplier,
                    )
                    contracts.append((resolved, label, expiry))
                try:
                    _stream_live_ticks(
                        ib, contracts, args.duration,
                        "http://127.0.0.1:9000",
                    )
                finally:
                    ib.disconnect()
            except Exception:
                ib.disconnect()
                raise
        else:
            # Use config file
            stream_ticks_loop()

    elif args.mode == "status":
        from ibgateway import gateway_status
        s = gateway_status()
        print("=" * 40)
        print("IBKR Pipeline Status")
        print("=" * 40)
        q = s["questdb"]
        print(f"QuestDB:     {'RUNNING' if q['running'] else 'STOPPED'} "
              f"(port {q['port']}, PID {q['pid'] or 'N/A'})")
        g = s["gateway"]
        print(f"Gateway:     {'RUNNING' if g['running'] else 'STOPPED'} "
              f"(port {g['port']}, PID {g['pid'] or 'N/A'})")
        print(f"Keepalive:   {'ENABLED' if s['keepalive'] else 'DISABLED'}")

    elif args.mode == "start":
        from ibgateway import start_gateway, wait_for_api, set_keepalive
        set_keepalive(True)
        t = threading.Thread(target=start_gateway, daemon=True)
        t.start()
        if wait_for_api():
            print("Gateway started and API ready.")
        else:
            print("WARNING: API not ready after start.", file=sys.stderr)
            sys.exit(1)

    elif args.mode == "stop":
        from ibgateway import stop_gateway
        stop_gateway()
        print("Gateway stopped.")


if __name__ == "__main__":
    main()
