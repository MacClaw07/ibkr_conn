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
import time
from pathlib import Path

from ib_insync import IB

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

        # Ensure gateway is running before attempting connection
        if not self._ensure_gateway_ready():
            raise IBConnectionFatalError(
                "Gateway failed to become ready"
            )

        # Establish a new connection (with retries)
        for attempt in range(1, 7):
            try:
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

    def start_gateway(self):
        from ibgateway import start_gateway as _start_gw, wait_for_api

        if not self.acquire_pid_lock(self._gateway_pid_file, "Gateway"):
            sys.exit(0)
        try:
            start_questdb()
            import threading
            t = threading.Thread(target=_start_gw, daemon=True)
            t.start()
            if wait_for_api():
                logger.info("Gateway started and API ready.")
                logger.info("NOTICE: .ibkr_keepalive was NOT set. Set manually to enable streaming:")
                logger.info("  echo true > configs/.ibkr_keepalive")
            else:
                logger.warning("API not ready after start.")
                sys.exit(1)
        except Exception:
            self.release_pid_lock(self._gateway_pid_file)
            raise

    def stop_gateway(self):
        from ibgateway import stop_gateway as _stop_gw

        self.set_keepalive(False)
        _stop_gw()
        stop_questdb()
        self.release_pid_lock(self._stream_pid_file)
        self.release_pid_lock(self._gateway_pid_file)
        logger.info("Gateway stopped.")

    # ── Status ──────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        from ibgateway import gateway_status
        s = gateway_status()
        s["keepalive"] = self.keep_alive()
        return s

    # ── Internal helpers ───────────────────────────────────────────────────

    def _ensure_gateway_ready(self) -> bool:
        """Check if Gateway API is reachable; start it if not."""
        from ibgateway import ensure_gateway
        return ensure_gateway()

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
