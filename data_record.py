#!/usr/bin/env python3
# /**
#  * data_record — Strongly-typed data transfer objects
#  * ====================================================
#  * Immutable record types for passing data between the IBKR data
#  * downloader and QuestDB ILP writers.
#  */

from datetime import datetime
from typing import NamedTuple, Optional


# /**
#  * A single historical bar row for QuestDB ILP write.
#  *
#  * Fields correspond to ib_async.BarData and the futures_hist
#  * QuestDB table schema.
#  */
class HistBarData(NamedTuple):
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None
    bar_count: Optional[int] = None
    average: Optional[float] = None


# /**
#  * A single tick snapshot for QuestDB ILP write.
#  *
#  * Fields correspond to ib_async ticker fields and the futures_tick
#  * QuestDB table schema.
#  */
# /**
#  * A single historical bar row for an option contract — for QuestDB ILP write.
#  *
#  * Fields correspond to ib_async.BarData combined with option-specific
#  * metadata (underlying_ric, type, strike) matching the options_hist table.
#  */
class HistBarOptionData(NamedTuple):
    date: datetime
    underlying_ric: str
    type: str  # "C" or "P"
    strike: float
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None
    bar_count: Optional[int] = None
    average: Optional[float] = None


class FutureTickData(NamedTuple):
    time: datetime
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    last_size: Optional[int] = None
