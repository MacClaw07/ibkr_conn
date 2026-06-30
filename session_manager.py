#!/usr/bin/env python3
"""
session_manager — Centralised session orchestration
=====================================================
Owns keepalive, PID locks, gateway/questdb lifecycle orchestration,
status reporting, and streaming dispatch.

Composes ibgateway_manager and questdb_manager.
"""

import os
import secrets
import socket
import sys
from pathlib import Path

from pipeline_logger import get_logger

logger = get_logger(__name__)


# ── Paths & constants ──────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent
KEEPALIVE_FILE = PROJECT_DIR / ".ibkr_keepalive"
STREAM_PID_FILE = PROJECT_DIR / ".ibkr_stream.pid"
GATEWAY_PID_FILE = PROJECT_DIR / ".ibkr_gateway.pid"

IB_GW_PORT = 4002
QUESTDB_PORT = 9000


def _force_disconnect_ib(ib):
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


class SessionManager:
    """Central orchestrator for IBKR pipeline sessions.

    Composes gateway and questdb lifecycle functions and owns the keepalive
    flag and PID-file locking that were previously scattered across multiple
    modules.
    """

    def __init__(self):
        """Create a SessionManager bound to the project directory."""
        self._project_dir = PROJECT_DIR
        self._keepalive_file = KEEPALIVE_FILE
        self._stream_pid_file = STREAM_PID_FILE
        self._gateway_pid_file = GATEWAY_PID_FILE

    # ── Keepalive ──────────────────────────────────────────────────────────

    ##
    # Check whether the keepalive flag file exists and is set to "true".
    #
    # @return: True if keepalive is enabled.
    def is_keepalive_enabled(self) -> bool:
        if not self._keepalive_file.exists():
            return False
        return self._keepalive_file.read_text().strip().lower() == "true"

    ##
    # Write the keepalive flag file with "true" or "false".
    #
    # @param val: True to enable keepalive, False to disable.
    def set_keepalive(self, val: bool):
        content = "true" if val else "false"
        self._keepalive_file.write_text(content + "\n")
        logger.info("Keepalive set to %s", content)

    # ── PID file locking ────────────────────────────────────────────────────

    ##
    # Read a PID from a file.
    #
    # @param pid_file: Path to a PID file.
    # @return: PID as an int, or None.
    def _read_pid(self, pid_file: Path) -> int | None:
        try:
            text = pid_file.read_text().strip()
            if not text:
                return None
            return int(text)
        except (FileNotFoundError, ValueError):
            return None

    ##
    # Check whether a process with the given PID currently exists.
    #
    # @param pid: Process ID to check.
    # @return: True if a process with pid exists.
    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    ##
    # Idempotency guard against duplicate process instances.
    #
    # If the PID file contains a live PID, log a message and return False.
    # Otherwise write the current PID and return True.
    #
    # @param pid_file: Path to the PID file.
    # @param label: Human-readable label for log messages.
    # @return: True if the current process should proceed.
    def acquire_pid_lock(self, pid_file: Path, label: str) -> bool:
        pid = self._read_pid(pid_file)
        if pid is not None and self._pid_alive(pid):
            logger.info("%s is already running (PID %d). Exiting.", label, pid)
            return False

        pid_file.write_text(str(os.getpid()) + "\n")
        return True

    ##
    # Remove the PID file if it still belongs to the current process.
    #
    # @param pid_file: Path to the PID file to release.
    def release_pid_lock(self, pid_file: Path):
        pid = self._read_pid(pid_file)
        if pid == os.getpid():
            try:
                pid_file.unlink()
            except FileNotFoundError:
                pass

    # ── Gateway lifecycle ─────────────────────────────────────────────────

    ##
    # Start the full pipeline: QuestDB then IB Gateway, wait for API.
    #
    # Acquires the gateway PID lock first.
    def start_gateway(self):
        from questdb_manager import start_questdb
        from ibgateway_manager import start_gateway as _start_gw, wait_for_api

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
                logger.info("  echo true > ~/Documents/ibkr_conn/.ibkr_keepalive")
            else:
                logger.warning("API not ready after start.")
                sys.exit(1)
        except Exception:
            self.release_pid_lock(self._gateway_pid_file)
            raise

    ##
    # Stop the full pipeline: Gateway then QuestDB, clear keepalive, release PIDs.
    def stop_gateway(self):
        from questdb_manager import stop_questdb
        from ibgateway_manager import stop_gateway as _stop_gw

        self.set_keepalive(False)
        _stop_gw()
        stop_questdb()
        self.release_pid_lock(self._stream_pid_file)
        self.release_pid_lock(self._gateway_pid_file)
        logger.info("Gateway stopped.")

    # ── Status ──────────────────────────────────────────────────────────────

    ##
    # Return a dict summarising all pipeline component statuses.
    #
    # @return: Dict with keys questdb, gateway, and keepalive.
    def get_status(self) -> dict:
        from ibgateway_manager import gateway_status
        s = gateway_status()
        s["keepalive"] = self.is_keepalive_enabled()
        return s

    # ── Streaming dispatch ─────────────────────────────────────────────────

    ##
    # Start tick streaming: CLI-ric mode or config-file-driven loop.
    #
    # If args.ric is set, stream those RICs directly.  Otherwise
    # delegates to ibgateway_manager.stream_ticks_loop with this
    # manager's keepalive callable.
    #
    # @param args: Parsed argparse.Namespace.
    def start_streaming(self, args):
        if not self.acquire_pid_lock(self._stream_pid_file, "Stream"):
            sys.exit(0)

        try:
            if args.ric:
                self._stream_with_rics(args)
            else:
                from ibgateway_manager import stream_ticks_loop
                stream_ticks_loop(self.is_keepalive_enabled)
        finally:
            self.release_pid_lock(self._stream_pid_file)

    ##
    # Stream RICs directly from CLI arguments (no config file).
    #
    # @param args: Parsed argparse.Namespace.
    def _stream_with_rics(self, args):
        from ibgateway_manager import ensure_gateway

        if not self.is_keepalive_enabled():
            logger.error("Keepalive is disabled; enable with --mode start first.")
            sys.exit(1)

        if not ensure_gateway():
            sys.exit(1)

        from ib_insync import IB
        from ibkr_utils import resolve_contracts
        from download_ticks import stream_live_ticks

        client_id = secrets.randbelow(900) + 100

        ib = None
        try:
            ib = IB()
            ib.connect("127.0.0.1", IB_GW_PORT,
                       clientId=client_id,
                       readonly=True, timeout=10)

            contracts = resolve_contracts(
                ib, args.ric,
                args.exchange, args.sec_type,
                args.currency, args.multiplier,
            )
            if not contracts:
                logger.error("Could not resolve any contracts")
                sys.exit(1)

            stream_live_ticks(
                ib, contracts, args.duration,
                "http://127.0.0.1:9000",
            )
        except Exception as e:
            logger.error("Stream error: %s", e)
            raise
        finally:
            _force_disconnect_ib(ib)
