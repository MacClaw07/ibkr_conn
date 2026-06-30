#!/usr/bin/env python3
"""
questdb_manager — QuestDB lifecycle & ILP writers
==================================================
QuestDB start/stop, health checks, and InfluxDB Line Protocol (ILP)
write helpers for the IBKR data pipeline.
"""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ib_insync import BarData

from pipeline_logger import get_logger

logger = get_logger(__name__)


# ── paths & constants ───────────────────────────────────────────────────────

QUESTDB_HOME = str(Path.home() / "apps" / "questdb-9.4.3")
JAVA_HOME_25 = "/usr/local/Cellar/openjdk@25/25.0.3"
QUESTDB_PORT = 9000


# ── port & process helpers ─────────────────────────────────────────────────

##
# Check if a TCP port is accepting connections.
#
# @param host: Hostname or IP address.
# @param port: TCP port number.
# @param timeout: Connection timeout in seconds.
# @return: True if the port accepted a connection.
def is_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except (OSError, socket.error):
        return False


##
# Check if QuestDB's HTTP port is accepting connections.
#
# @return: True if QuestDB appears responsive on the default port.
def is_questdb_running() -> bool:
    return is_port_open("127.0.0.1", QUESTDB_PORT, timeout=1.0)


##
# Find the QuestDB Java process PID via pgrep.
#
# @return: PID as an integer, or None if not found.
def find_questdb_pid() -> Optional[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "QuestDB-Runtime"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass
    return None


# ── QuestDB lifecycle ──────────────────────────────────────────────────────

##
# Start QuestDB if it is not already running.
#
# Uses JAVA_HOME_25 to ensure the correct Java runtime is picked up.
# Exits with error if questdb.sh is not found.
def start_questdb():
    if is_questdb_running():
        logger.info("QuestDB is already running.")
        return

    questdb_sh = Path(QUESTDB_HOME) / "questdb.sh"
    if not questdb_sh.exists():
        logger.error("%s not found", questdb_sh)
        sys.exit(1)

    env = os.environ.copy()
    env["JAVA_HOME"] = JAVA_HOME_25

    logger.info("Starting QuestDB...")
    subprocess.Popen(
        [str(questdb_sh), "start"],
        cwd=QUESTDB_HOME,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(30):
        if is_questdb_running():
            logger.info("QuestDB started.")
            return
        time.sleep(1)

    logger.warning("QuestDB did not become ready within 30s")


##
# Stop QuestDB gracefully with a force-kill fallback.
#
# PID file cleanup is handled by SessionManager — this function only
# stops the QuestDB process.
def stop_questdb():
    questdb_sh = Path(QUESTDB_HOME) / "questdb.sh"
    if questdb_sh.exists():
        env = os.environ.copy()
        env["JAVA_HOME"] = JAVA_HOME_25
        subprocess.run(
            [str(questdb_sh), "stop"],
            cwd=QUESTDB_HOME, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=15,
        )

    pid = find_questdb_pid()
    if pid:
        logger.info("Force killing QuestDB PID %d...", pid)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        time.sleep(1)

    if is_questdb_running():
        logger.warning("QuestDB still running after stop attempt")
    else:
        logger.info("QuestDB stopped.")


# ── ILP timestamp helpers ──────────────────────────────────────────────────

##
# Convert a datetime to nanoseconds since epoch for ILP.
#
# @param dt: A timezone-naive datetime.
# @return: Nanosecond-precision Unix timestamp as an integer.
def _format_ilp_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


##
# Post a batch of ILP lines to QuestDB /write.
#
# @param lines: ILP-formatted strings to send.
# @param questdb_url: QuestDB REST base URL.
# @return: Number of lines successfully written (HTTP 204).
def _send_ilp_batch(lines: List[str], questdb_url: str) -> int:
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
                logger.warning("QuestDB /write returned HTTP %d", resp.status)
                return 0
    except urllib.error.URLError as e:
        logger.error("Writing batch to QuestDB: %s", e)
        return 0


# ── ILP table writers ──────────────────────────────────────────────────────

##
# Write historical BarData to QuestDB futures_hist table via ILP.
#
# @param bars: List of BarData from ib_insync.
# @param ric_label: RIC label e.g. 'ESU6'.
# @param expiry_date: Expiry date as YYYY-MM-DD.
# @param questdb_url: QuestDB REST base URL.
# @return: Number of rows written.
def write_bars_to_questdb(
    bars: List[BarData],
    ric_label: str,
    expiry_date: str,
    questdb_url: str = "http://127.0.0.1:9000",
) -> int:
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

    batch_size = 1000
    total_written = 0

    for i in range(0, len(lines), batch_size):
        batch = lines[i:i + batch_size]
        total_written += _send_ilp_batch(batch, questdb_url)

    return total_written


##
# Write tick data dicts to QuestDB futures_tick table via ILP.
#
# Each tick dict should have keys: time (datetime), bid, ask, last,
# bid_size, ask_size, last_size.
#
# @param ticks: List of tick data dicts.
# @param ric_label: RIC label.
# @param expiry_date: Expiry date as YYYY-MM-DD.
# @param questdb_url: QuestDB REST base URL.
# @return: Number of rows written.
def write_ticks_to_questdb(
    ticks: List[dict],
    ric_label: str,
    expiry_date: str,
    questdb_url: str = "http://127.0.0.1:9000",
) -> int:
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

    batch_size = 1000
    total_written = 0

    for i in range(0, len(lines), batch_size):
        batch = lines[i:i + batch_size]
        total_written += _send_ilp_batch(batch, questdb_url)

    return total_written
