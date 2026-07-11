-- ============================================================================
-- IBKR Connector — QuestDB Schema
-- ============================================================================
-- This file defines all tables used by the IBKR data connector.
-- Run against QuestDB's REST /exec endpoint or via the QuestDB Console.
--
-- Tables:
--   futures_hist    — Historical OHLCV bar data (1-min, 5-min, etc.)
--   futures_tick    — Real-time L1 tick data for futures
--   options_tick    — Real-time L1 tick data for options on futures (FOP)
--   options_hist    — Historical OHLCV bar data for options on futures (FOP)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- futures_hist — Historical OHLCV bars
-- ----------------------------------------------------------------------------
-- Written by QuestDBManager.write_bars() from HistBarData records.
-- Timestamps are the bar open time in UTC.
CREATE TABLE IF NOT EXISTS futures_hist (
    datetime  TIMESTAMP,        -- bar opening time (UTC)
    ric       SYMBOL,           -- RIC label, e.g. "ESU6"
    expiry    SYMBOL,           -- contract expiry date, e.g. "2026-09-20"
    open      DOUBLE,           -- open price
    high      DOUBLE,           -- high price
    low       DOUBLE,           -- low price
    close     DOUBLE,           -- close price
    volume    LONG,             -- tick volume
    bar_count INT,              -- number of individual trades in the bar
    average   DOUBLE            -- volume-weighted average price (VWAP)
) TIMESTAMP(datetime) PARTITION BY DAY;
-- Partition by day enables efficient time-range pruning for backtests and
-- replay of specific date ranges.

-- ----------------------------------------------------------------------------
-- futures_tick — Real-time L1 ticks for futures contracts
-- ----------------------------------------------------------------------------
-- Written by QuestDBManager.write_ticks() from FutureTickData records,
-- and also by _build_ilp_line() in data_downloader.py for live stream.
CREATE TABLE IF NOT EXISTS futures_tick (
    datetime  TIMESTAMP,        -- tick time (UTC)
    ric       SYMBOL,           -- RIC label, e.g. "ESU6"
    expiry    SYMBOL,           -- contract expiry date, e.g. "2026-09-20"
    bid       DOUBLE,           -- best bid price
    ask       DOUBLE,           -- best ask price
    last      DOUBLE,           -- last traded price
    bid_size  LONG,             -- bid size (contracts)
    ask_size  LONG,             -- ask size (contracts)
    last_size LONG              -- last trade size (contracts)
) TIMESTAMP(datetime) PARTITION BY DAY;

-- ----------------------------------------------------------------------------
-- options_tick — Real-time L1 ticks for options on futures (FOP)
-- ----------------------------------------------------------------------------
-- Written by _build_ilp_line() in data_downloader.py for live stream.
-- Tags include underlying_ric and option type (C/P).
CREATE TABLE IF NOT EXISTS options_tick (
    datetime       TIMESTAMP,   -- tick time (UTC)
    ric            SYMBOL,      -- option RIC label, e.g. "ESU67500C"
    underlying_ric SYMBOL,      -- underlying futures RIC, e.g. "ESU6"
    expiry         SYMBOL,      -- option expiry date, e.g. "2026-09-20"
    type           SYMBOL,      -- option type: "C" = call, "P" = put
    strike         DOUBLE,      -- strike price
    bid            DOUBLE,      -- best bid price
    ask            DOUBLE,      -- best ask price
    last           DOUBLE,      -- last traded price
    bid_size       LONG,        -- bid size (contracts)
    ask_size       LONG,        -- ask size (contracts)
    last_size      LONG         -- last trade size (contracts)
) TIMESTAMP(datetime) PARTITION BY DAY;

-- ----------------------------------------------------------------------------
-- options_hist — Historical OHLCV bars for options on futures (FOP)
-- ----------------------------------------------------------------------------
-- Designed for ib_insync BarData from options contracts.
-- Combines OHLCV bar columns (as in futures_hist) with option metadata
-- fields (underlying_ric, type, strike) from options_tick.
CREATE TABLE IF NOT EXISTS options_hist (
    datetime       TIMESTAMP,   -- bar opening time (UTC)
    ric            SYMBOL,      -- option RIC label, e.g. "ESU67500C"
    underlying_ric SYMBOL,      -- underlying futures RIC, e.g. "ESU6"
    expiry         SYMBOL,      -- option expiry date, e.g. "2026-09-20"
    type           SYMBOL,      -- option type: "C" = call, "P" = put
    strike         DOUBLE,      -- strike price
    open           DOUBLE,      -- open price
    high           DOUBLE,      -- high price
    low            DOUBLE,      -- low price
    close          DOUBLE,      -- close price
    volume         LONG,        -- tick volume
    bar_count      INT,         -- number of individual trades in the bar
    average        DOUBLE       -- volume-weighted average price (VWAP)
) TIMESTAMP(datetime) PARTITION BY DAY;
