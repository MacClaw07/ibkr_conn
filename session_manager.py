#!/usr/bin/env python3
"""
session_manager — Singleton connection service
================================================
Owns the live IB connection and QuestDB handle.  Clients request
handles via get_ib_conn() / get_questdb() and report errors via
on_error().  The manager internally retries IB connections up to
6 times with 5-second sleep intervals.

No streaming logic, no tick config loading, no download logic.
Those live in data_downloader.py.
"""

import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from ib_insync import IB

from ibgateway import IBGateway
from logger import get_logger
from questdb import QuestDBManager, start_questdb, stop_questdb

logger = get_logger(__name__)


# ── Paths & constants ──────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent
CONFIGS_DIR = PROJECT_DIR / "configs"
KEEPALIVE_FILE = CONFIGS_DIR / ".ibkr_keepalive"
STREAM_PID_FILE = CONFIGS_DIR / ".ibkr_stream.pid"
GATEWAY_PID_FILE = CONFIGS_DIR / ".ibkr_gateway.pid"

IB_GW_PORT = 4002


# ═══════════════════════════════════════════════════════════════════════════════
#  Custom exception
# ═══════════════════════════════════════════════════════════════════════════════

class IBConnectionFatalError(Exception):
    """Raised by SessionManager when IB connection is unrecoverable
    after 6 retry attempts."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
#  SessionManager — Singleton
# ═══════════════════════════════════════════════════════════════════════════════

class SessionManager:
    """Singleton connection service.

    Owns the live IB connection and QuestDB handle.  Clients call
    get_ib_conn() to obtain an IB instance and on_error() to signal
    that the connection has died.

    Internal retry: on first get_ib_conn() after an error, the manager
    attempts up to 6 reconnects with 5-second sleep intervals.  If all
    fail it raises IBConnectionFatalError.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Prevent re-init on subsequent calls (Singleton)
        if hasattr(self, '_initialised') and self._initialised:
            return

        self._project_dir = PROJECT_DIR
        self._keepalive_file = KEEPALIVE_FILE
        self._stream_pid_file = STREAM_PID_FILE
        self._gateway_pid_file = GATEWAY_PID_FILE

        self._ib: IB | None = None
        self._questdb = QuestDBManager()
        self._gateway_ready_lock = threading.Lock()
        self._gateway_ready = False
        self._gateway = IBGateway(on_gateway_terminated=[self._on_gateway_terminated])
        self._error_reported = False

        self._initialised = True

    # ── Public API ──────────────────────────────────────────────────────────

    ##
    # Return a live IB connection.
    #
    # If no connection exists, or the client previously reported an error
    # via on_error(), this method attempts to establish a new connection.
    # Up to 6 retries with 5-second sleep intervals are performed
    # internally.
    #
    # @return: A connected ib_insync.IB instance.
    # @raise IBConnectionFatalError: If connection cannot be established
    #     after 6 attempts.
    def get_ib_conn(self) -> IB:
        if self._ib is not None and not self._error_reported:
            if self._ib.isConnected():
                return self._ib
            else:
                self._ib = None

        # Establish a new connection (with retries)
        for attempt in range(1, 7):
            try:
                if not self._get_gateway_status():
                    if not self._ensure_gateway_ready():
                        raise IBConnectionFatalError("Gateway not ready; cannot connect to IB")
                    
                cid = secrets.randbelow(900) + 100
                ib = IB()
                ib.connect("127.0.0.1", IB_GW_PORT,
                           clientId=cid,
                           readonly=True, timeout=10)
                self._ib = ib
                self._error_reported = False
                logger.info("IB connected (clientId=%d, attempt %d)", cid, attempt)
                return self._ib
            except Exception as e:
                logger.warning("IB connect failed (attempt %d/6): %s", attempt, e)
                if attempt < 6:
                    time.sleep(5)

        raise IBConnectionFatalError(
            "IB connection unrecoverable after 6 attempts"
        )

    ##
    # Return the live QuestDB handle.
    #
    # @return: The QuestDBManager instance.
    def get_questdb(self) -> QuestDBManager:
        return self._questdb

    ##
    # Signal that the IB connection has died.
    #
    # The next call to get_ib_conn() will attempt to establish a fresh
    # connection (with internal retries).
    def on_error(self):
        logger.warning("Client reported IB connection error")
        self._ib = None
        self._error_reported = True

    def set_gateway_status(self, ready: bool) -> None:
        with self._gateway_ready_lock:
            logger.info("Setting gateway ready status to %s", ready)
            self._gateway_ready = ready

    def _get_gateway_status(self) -> bool:
        with self._gateway_ready_lock:
            return self._gateway_ready

    def _on_gateway_terminated(self, pid: int) -> None:
        logger.warning("Gateway terminated (PID %d); marking gateway as not ready", pid)
        self.set_gateway_status(False)

    # ── Keepalive ──────────────────────────────────────────────────────────

    def keep_alive(self) -> bool:
        if not self._keepalive_file.exists():
            return False
        return self._keepalive_file.read_text().strip().lower() == "true"

    def set_keepalive(self, val: bool):
        content = "true" if val else "false"
        self._keepalive_file.write_text(content + "\n")
        logger.info("Keepalive set to %s", content)

    # ── PID file locking ───────────────────────────────────────────────────

    def _read_pid(self, pid_file: Path) -> int | None:
        try:
            text = pid_file.read_text().strip()
            if not text:
                return None
            return int(text)
        except (FileNotFoundError, ValueError):
            return None

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def acquire_pid_lock(self, pid_file: Path, label: str) -> bool:
        pid = self._read_pid(pid_file)
        if pid is not None and self._pid_alive(pid):
            logger.info("%s is already running (PID %d). Exiting.", label, pid)
            return False
        pid_file.write_text(str(os.getpid()) + "\n")
        return True

    def release_pid_lock(self, pid_file: Path):
        pid = self._read_pid(pid_file)
        if pid == os.getpid():
            try:
                pid_file.unlink()
            except FileNotFoundError:
                pass

    # ── Gateway lifecycle ─────────────────────────────────────────────────

    def start(self):
        """Start QuestDB and IB Gateway.

        Acquires the gateway PID lock, starts QuestDB, and delegates
        gateway startup to ibgateway.start_gateway().
        """
        if not self.acquire_pid_lock(self._gateway_pid_file, "Gateway"):
            sys.exit(0)
        try:
            start_questdb()
            self._gateway.start_gateway()
            if self._gateway.wait_for_api(self):
                self.set_gateway_status(True)
                logger.info("Gateway started and API ready.")
                logger.info("NOTICE: .ibkr_keepalive was NOT set. Set manually to enable streaming:")
                logger.info("  echo true > configs/.ibkr_keepalive")
            else:
                logger.warning("API not ready after start.")
                sys.exit(1)
        except Exception:
            self.release_pid_lock(self._gateway_pid_file)
            raise

    def stop(self):
        """Stop IB Gateway and QuestDB.

        Clears keepalive, stops the gateway, stops QuestDB, and releases
        stream and gateway PID locks.
        """
        self.set_keepalive(False)
        self._gateway.stop_gateway()
        self.set_gateway_status(False)
        stop_questdb()
        self.release_pid_lock(self._stream_pid_file)
        self.release_pid_lock(self._gateway_pid_file)
        logger.info("Gateway stopped.")

    # ── Status ──────────────────────────────────────────────────────────────

    def session_status(self) -> dict:
        status = {
            "questdb": {"running": False, "port": 9000, "pid": None},
            "gateway": {"running": False, "port": IB_GW_PORT, "pid": None},
            "keepalive": self.keep_alive(),
        }

        qpid = QuestDBManager.find_questdb_pid()
        if qpid:
            status["questdb"]["running"] = True
            status["questdb"]["pid"] = qpid

        status["gateway"]["running"] = QuestDBManager.is_port_open("127.0.0.1", IB_GW_PORT, timeout=1.0)

        try:
            result = subprocess.run(
                ["pgrep", "-f", "displaybannerandlaunch"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                status["gateway"]["pid"] = int(result.stdout.strip().split()[0])
        except Exception:
            pass

        return status

    def get_status(self) -> dict:
        return self.session_status()

    # ── Internal helpers ───────────────────────────────────────────────────

    def _ensure_gateway_ready(self) -> bool:
        """Check if Gateway API is reachable; start it if not."""
        ready = self._gateway.ensure_gateway(self)
        if ready:
            self.set_gateway_status(True)
        return ready

    def _force_disconnect_ib(self, ib: IB | None):
        """Aggressively close an ib_insync IB connection."""
        if ib is None:
            return
        try:
            if hasattr(ib, 'client') and hasattr(ib.client, '_socket'):
                sock = ib.client._socket
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    try:
                        sock.close()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            ib.disconnect()
        except Exception:
            pass
