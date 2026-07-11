# ibkr_conn / db — QuestDB Schema

This directory contains the QuestDB schema definitions for the IBKR data connector project.

## Tables

| Table | Type | Written by | Description |
|-------|------|-----------|-------------|
| `futures_hist` | OHLCV bars | `questdb.py::write_bars()` | Historical bar data (1-min, 5-min, etc.) from `ib_insync` |
| `futures_tick` | L1 ticks | `questdb.py::write_ticks()` / `data_downloader.py` live stream | Real-time L1 ticks for futures contracts |
| `options_tick` | L1 ticks | `data_downloader.py` live stream | Real-time L1 ticks for options on futures (FOP) |

## Schema files

| File | Usage |
|------|-------|
| `schema.sql` | Run via QuestDB REST `/exec` endpoint or pasted into the QuestDB Console (http://localhost:9000) |
| `schema.psql` | Run via `psql` against QuestDB's PostgreSQL wire-protocol port (8812) |

## Applying the schema

### Via REST (HTTP Console)

Open http://localhost:9000 and paste each `CREATE TABLE` statement, or send via curl:

```bash
while IFS= read -r line; do
  encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$line'''))" 2>/dev/null || curl -s --data-urlencode "query=$line")
  curl -s "http://localhost:9000/exec?query=$encoded"
done < schema.sql
```

### Via psql

```bash
PGPASSWORD=quest psql -h localhost -p 8812 -U admin -d qdb -f schema.psql
```

## ILP ingestion details

All three tables are written via the QuestDB InfluxDB Line Protocol endpoint (`/write` on port 9000). The ILP encoding is handled in:

- `questdb.py` — `QuestDBManager.write_bars()`, `QuestDBManager.write_ticks()`
- `data_downloader.py` — `_build_ilp_line()` (live stream)

### Design notes

- **Designated timestamp column** is always `datetime`, partitioned by `DAY` for efficient time-range queries.
- **Tags** (`ric`, `expiry`, `underlying_ric`, `type`) are stored as `SYMBOL` for compressed storage and fast filtering.
- **ILP lines** include tags as the measurement key, e.g.:
  ```
  futures_tick,ric=ESU6,expiry=2026-09-20 bid=4892.25,ask=4892.50,last=4892.30,bid_size=10i,ask_size=15i,last_size=1i 1720800000000000000
  ```
- All timestamps are **UTC** with nanosecond precision.
