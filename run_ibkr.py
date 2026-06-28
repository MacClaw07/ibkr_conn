#!/usr/bin/env python3
"""Single entry point for IBKR data download tools."""

import sys
from ibkr_utils import build_parser
from download_bars import main_bars
from download_ticks import main_ticks


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.mode == "bars" and not args.date:
        parser.error("--date is required for --mode bars")

    if args.mode == "bars":
        main_bars(args)
    elif args.mode == "ticks":
        main_ticks(args)


if __name__ == "__main__":
    main()
