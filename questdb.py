#!/usr/bin/env python3
"""
questdb — QuestDB lifecycle & ILP writers
==================================================
QuestDBManager provides ILP write operations for the active QuestDB
connection.  Lifecycle functions (start/stop) are module-level and
called by SessionManager.

QuestDBManager has no ib_insync dependency — all data is passed as
plain dicts, lists, or datetimes.
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

from data_record import HistBarData, FutureTickData
from logger import get_logger

logger = get_logger(__name__)


# ── paths & constants ───────────────────────────────────────────────────────

QUESTDB_HOME = str(Path.home() / "apps" / "questdb-9.4.3")
JAVA_HOME_25 = "/usr/local/Cellar/openjdk@25/25.0.3"
QUESTDB_PORT = 9000


# ═══════════════════════════════════════════════════════════════════════════════
#  QuestDBManager
# ═══════════════════════════════════════════════════════════════════════════════

class QuestDBManager:
    """Live QuestDB connection handle.

    Owned by SessionManager.  Provides ILP batch writes for both
    historical bar data and live tick data.  No ib_insync dependency.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9000):
        """Create a QuestDBManager pointing at a QuestDB REST endpoint.

        Args:
            host: QuestDB HTTP host.
            port: QuestDB HTTP port.
        """
        self._url = f"http://{host}:{port}"

    @property
    def url(self) -> str:
        """Return the QuestDB REST base URL."""
        return self._url

    # ── ILP batch send ──────────────────────────────────────────────────────

    ##
    # Post a batch of ILP lines to QuestDB /write.
    #
    # @param lines: ILP-formatted strings to send.
    # @return: Number of lines successfully written (HTTP 204).
    def send_ilp_batch(self, lines: List[str]) -> int:
        if not lines:
            return 0

        body = "\n".join(lines).encode("utf-8")
        write_url = f"{self._url}/write"

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

    # ── Static helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _ok(val) -> bool:
        """Return True if val is a non-NaN number."""
        return val is not None and val == val

    @staticmethod
    def _format_ilp_timestamp(dt: datetime) -> int:
        """Convert a datetime to nanoseconds since epoch for ILP.

        Args:
            dt: A timezone-naive datetime.

        Returns:
            Nanosecond-precision Unix timestamp as an integer.
        """
        return int(dt.timestamp() * 1_000_000_000)

    # ── Bar writer ─────────────────────────────────────────────────────────

    ##
    # Write historical bar data to QuestDB futures_hist table via ILP.
    #
    # @param bars: List of HistBarData NamedTuples.
    # @param ric_label: RIC label e.g. 'ESU6'.
    # @param expiry_date: Expiry date as YYYY-MM-DD.
    # @param batch_size: Rows per ILP batch.
    # @return: Number of rows written.
    def write_bars(
        self,
        bars: List[HistBarData],
        ric_label: str,
        expiry_date: str,
        batch_size: int = 1000,
    ) -> int:
        if not bars:
            return 0

        measurement = "futures_hist"
        lines = []

        for b in bars:
            ts_ns = self._format_ilp_timestamp(b.date)
            fields = []
            if self._ok(b.open):
                fields.append(f"open={b.open}")
            if self._ok(b.high):
                fields.append(f"high={b.high}")
            if self._ok(b.low):
                fields.append(f"low={b.low}")
            if self._ok(b.close):
                fields.append(f"close={b.close}")
            if b.volume is not None:
                fields.append(f"volume={int(b.volume)}i")
            if b.bar_count is not None:
                fields.append(f"bar_count={int(b.bar_count)}i")
            if self._ok(b.average):
                fields.append(f"average={b.average}")

            if not fields:
                continue

            line = f"{measurement},ric={ric_label},expiry={expiry_date} {','.join(fields)} {ts_ns}"
            lines.append(line)

        total_written = 0
        for i in range(0, len(lines), batch_size):
            batch = lines[i:i + batch_size]
            total_written += self.send_ilp_batch(batch)

        return total_written

    # ── Tick writer ────────────────────────────────────────────────────────

    ##
    # Write tick data to QuestDB futures_tick table via ILP.
    #
    # @param ticks: List of FutureTickData NamedTuples.
    # @param ric_label: RIC label.
    # @param expiry_date: Expiry date as YYYY-MM-DD.
    # @return: Number of rows written.
    def write_ticks(
        self,
        ticks: List[FutureTickData],
        ric_label: str,
        expiry_date: str,
    ) -> int:
        if not ticks:
            return 0

        measurement = "futures_tick"
        lines = []

        for t in ticks:
            ts_ns = self._format_ilp_timestamp(t.time)

            fields = []
            if self._ok(t.bid):
                fields.append(f"bid={t.bid}")
            if self._ok(t.ask):
                fields.append(f"ask={t.ask}")
            if self._ok(t.last):
                fields.append(f"last={t.last}")
            if t.bid_size is not None:
                fields.append(f"bid_size={int(t.bid_size)}i")
            if t.ask_size is not None:
                fields.append(f"ask_size={int(t.ask_size)}i")
            if t.last_size is not None:
                fields.append(f"last_size={int(t.last_size)}i")

            if not fields:
                continue

            line = f"{measurement},ric={ric_label},expiry={expiry_date} {','.join(fields)} {ts_ns}"
            lines.append(line)

        batch_size = 1000
        total_written = 0
        for i in range(0, len(lines), batch_size):
            batch = lines[i:i + batch_size]
            total_written += self.send_ilp_batch(batch)

        return total_written

    # ── Static health checks ────────────────────────────────────────────────

    @staticmethod
    def is_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
        """Check if a TCP port is accepting connections."""
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            return True
        except (OSError, socket.error):
            return False

    @staticmethod
    def is_questdb_running() -> bool:
        """Check if QuestDB's HTTP port is accepting connections."""
        return QuestDBManager.is_port_open("127.0.0.1", QUESTDB_PORT, timeout=1.0)

    @staticmethod
    def find_questdb_pid() -> Optional[int]:
        """Find the QuestDB Java process PID via pgrep."""
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


# ═══════════════════════════════════════════════════════════════════════════════
#  QuestDB lifecycle (module-level, called by SessionManager)
# ═══════════════════════════════════════════════════════════════════════════════

##
# Start QuestDB if it is not already running.
def start_questdb():
    if QuestDBManager.is_questdb_running():
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
        if QuestDBManager.is_questdb_running():
            logger.info("QuestDB started.")
            return
        time.sleep(1)

    logger.warning("QuestDB did not become ready within 30s")


##
# Stop QuestDB gracefully with a force-kill fallback.
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

    pid = QuestDBManager.find_questdb_pid()
    if pid:
        logger.info("Force killing QuestDB PID %d...", pid)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        time.sleep(1)

    if QuestDBManager.is_questdb_running():
        logger.warning("QuestDB still running after stop attempt")
    else:
        logger.info("QuestDB stopped.")
