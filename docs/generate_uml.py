#!/usr/bin/env python3
"""Generate ibkr_conn UML architecture diagram as standalone HTML with inline SVG."""

from pathlib import Path

HERE = Path(__file__).resolve().parent

CSS = """<!doctype html>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ibkr_conn — Architecture Diagram</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f8fafc;
    --fg: #172033;
    --muted: #5b6475;
    --line: #64748b;
    --cli: #bfdbfe; --cli-border: #60a5fa;
    --app: #c7d2fe; --app-border: #818cf8;
    --lib: #e2e8f0; --lib-border: #94a3b8;
    --ext: #fde68a; --ext-border: #facc15;
    --sto: #99f6e4; --sto-border: #2dd4bf;
    --dto: #c4b5fd; --dto-border: #a78bfa;
    --risk: #fecaca; --risk-border: #f87171;
    --res: #d9ead3; --res-border: #86efac;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f172a; --fg: #e5e7eb; --muted: #a3adbd; --line: #94a3b8;
      --cli: #1d4ed8; --cli-border: #60a5fa;
      --app: #4338ca; --app-border: #818cf8;
      --lib: #334155; --lib-border: #64748b;
      --ext: #92400e; --ext-border: #facc15;
      --sto: #0f766e; --sto-border: #2dd4bf;
      --dto: #5b21b6; --dto-border: #a78bfa;
      --risk: #991b1b; --risk-border: #f87171;
      --res: #14532d; --res-border: #86efac;
    }
  }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.4 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  main { max-width: 1280px; margin: 32px auto; padding: 0 20px; }
  svg { width: 100%; height: auto; display: block; }
  .title    { font-size: 20px; font-weight: 650; fill: var(--fg); }
  .subtitle { font-size: 13px; fill: var(--muted); }
  .label    { font-size: 13px; font-weight: 600; fill: var(--fg); }
  .small    { font-size: 11px; fill: var(--muted); }
  .method   { font-size: 10px; fill: var(--muted); }
  .node     { stroke-width: 1.5; rx: 6; ry: 6; }
  .cat-cli  { fill: var(--cli); stroke: var(--cli-border); }
  .cat-app  { fill: var(--app); stroke: var(--app-border); }
  .cat-lib  { fill: var(--lib); stroke: var(--lib-border); }
  .cat-ext  { fill: var(--ext); stroke: var(--ext-border); }
  .cat-sto  { fill: var(--sto); stroke: var(--sto-border); }
  .cat-dto  { fill: var(--dto); stroke: var(--dto-border); }
  .cat-risk { fill: var(--risk); stroke: var(--risk-border); }
  .cat-res  { fill: var(--res); stroke: var(--res-border); }
  .edge     { stroke: var(--line); stroke-width: 1.5; fill: none; }
  .dashed   { stroke: var(--line); stroke-width: 1.5; fill: none; stroke-dasharray: 5 4; }
  .zone     { fill: none; stroke: var(--line); stroke-width: 1; stroke-dasharray: 6 5; opacity: 0.6; }
  .zone-label { font-size: 11px; fill: var(--muted); }
</style>"""

def box(x, y, w, h, cls, label_lines, method_lines):
    """Return SVG elements for a node box + text."""
    lines = []
    lines.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" class="node {cls}" />')
    ly = y + 20
    for line in label_lines:
        lines.append(f'  <text x="{x + w//2}" y="{ly}" text-anchor="middle" class="label">{line}</text>')
        ly += 16
    ly += 2
    for line in method_lines:
        lines.append(f'  <text x="{x + 8}" y="{ly}" class="method">{line}</text>')
        ly += 13
    return lines


def main():
    lines = []
    lines.append(CSS)
    lines.append('<main>')
    lines.append('<svg viewBox="0 0 1200 1180" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,sans-serif">')
    lines.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--line)"/></marker></defs>')

    # Title
    lines.append('  <text x="600" y="30" text-anchor="middle" class="title">ibkr_conn — Module Architecture</text>')
    lines.append('  <text x="600" y="48" text-anchor="middle" class="subtitle">Updated: July 2026 · 8 Python modules · 3 zones · Typed DTOs · Singleton SessionManager · Runtime resources</text>')

    # ═══════════════════════════════════════════════════════════
    # ZONE 1: CLI Entry (Y: 60–240)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="60" width="1140" height="190" class="zone"/>')
    lines.append('  <text x="40" y="77" class="zone-label">CLI Entry</text>')

    lines.extend(box(40, 95, 280, 140, "cat-cli",
        ["run_service.py", "CLI entry point"],
        ["Auto-reinvoke with project venv (os.execv)", "main() — dispatch by --mode",
         "build_ibkr_parser() — argparse", "_clean_stale_pycache()",
         "_handle_status() — health output", "configure_pipeline_logging() — init"]))

    # ═══════════════════════════════════════════════════════════
    # ZONE 2: Application Logic (Y: 270–720)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="260" width="1140" height="470" class="zone"/>')
    lines.append('  <text x="40" y="277" class="zone-label">Application Logic</text>')

    # ── Row 1 (Y: 290) ──
    # session_manager.py — left
    lines.extend(box(40, 290, 290, 175, "cat-app",
        ["session_manager.py  🔒 Singleton", "SessionManager — owns IB + QuestDB"],
        ["get_ib_conn()  (6×5s internal retry)", "get_questdb() → QuestDBManager",
         "on_error()  (signal connection death)", "start() / stop() — gateway lifecycle",
         "get_status() · keepalive · set_keepalive()",
         "acquire_pid_lock() / release_pid_lock()",
         "_ensure_gateway_ready() · set_gateway_status()",
         "_get_gateway_status() · _force_disconnect_ib()",
         "_on_gateway_terminated(pid) — callback",
         "→ IBConnectionFatalError (6 fails)"]))

    # data_downloader.py — center
    lines.extend(box(370, 290, 290, 175, "cat-lib",
        ["data_downloader.py  📦 Client", "DataDownloader — uses SessionManager"],
        ["download_bars()  (error recovery loop)", "start_streaming()  (PID-locked entry)",
         "stream_data()  (keepalive loop)", "  → IBConnectionFatalError on abort",
         "_load_tick_config()  (JSON config)",
         "_do_bars_download()  (core bars logic)",
         "Module-level helpers:",
         "  _generate_chunks() · _fetch_chunk()",
         "  _download_bars() · _to_hist_bar() · _bars_to_csv()",
         "  _build_ilp_line() — ILP formatter",
         "  stream_live_ticks(ib, ..., send_batch=...)"]))

    # utils.py — right
    lines.extend(box(700, 290, 200, 175, "cat-lib",
        ["utils.py", "Shared utilities (no connections)"],
        ["build_ric_contract()", "resolve_contracts()",
         "get_contract()", "parse_date_range()",
         "_month_map()"]))

    # ── Row 2 (Y: 500) ──
    # ibgateway.py
    lines.extend(box(40, 500, 290, 180, "cat-app",
        ["ibgateway.py", "Gateway lifecycle (no ib_insync)"],
        ["IBGateway class:", "  __init__(on_gateway_terminated=[])",
         "  generate_config_ini(self) — instance method",
         "  get_credentials() — static method",
         "  add_gateway_terminated_handler()",
         "  start_gateway() — subprocess start",
         "  stop_gateway() — nc + kill",
         "  ensure_gateway(mgr) — auto-restart",
         "  wait_for_api(mgr) — poll",
         "Module-level:", "  get_credentials() · generate_config_ini()",
         "  install_scripts()"]))

    # questdb.py
    lines.extend(box(370, 500, 290, 180, "cat-app",
        ["questdb.py", "QuestDBManager — ILP write operations"],
        ["QuestDBManager:", "  __init__(host, port=9000)",
         "  url property → REST base URL",
         "  send_ilp_batch() → int (count written)",
         "  write_bars() → futures_hist table",
         "  write_ticks() → futures_tick table",
         "  Static: is_port_open(), is_questdb_running()",
         "  Static: find_questdb_pid()",
         "  Static: _ok(val) — NaN check",
         "  Static: _format_ilp_timestamp(dt) → nanosec",
         "Module-level:", "  start_questdb() · stop_questdb()",
         "  (called by SessionManager)"]))

    # IB() Guard Rule
    lines.extend(box(700, 515, 240, 130, "cat-risk",
        ["🔐 IB() Guard Rule",
         "Only session_manager.py may",
         "construct ib_insync.IB()",
         "or call ib.connect()."],
        ["Enforce:", 'grep -rn "IB()" --include="*.py" .',
         "  | grep -v venv | grep -v __pycache__",
         "(ibgateway.py probes use temp IB",
         " but never export it)"]))

    # ═══════════════════════════════════════════════════════════
    # ZONE 3: External Dependencies (Y: 750–900)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="740" width="1140" height="170" class="zone"/>')
    lines.append('  <text x="40" y="757" class="zone-label">External Dependencies</text>')

    # IB Gateway
    lines.extend(box(40, 770, 220, 90, "cat-ext",
        ["IB Gateway (TWS)", "TCP :4002 — Paper/live"],
        ["ib_insync library", "IBC controller"]))

    # QuestDB Server
    lines.extend(box(300, 770, 220, 90, "cat-sto",
        ["QuestDB Server", "HTTP :9000 / ILP :9009"],
        ["futures_hist table", "futures_tick table"]))

    # CSV File System
    lines.extend(box(560, 770, 180, 90, "cat-sto",
        ["CSV File System", "Data directory"],
        ["bars CSV export", "(--format csv mode)"]))

    # ═══════════════════════════════════════════════════════════
    # Right panel: Supporting Types
    # ═══════════════════════════════════════════════════════════
    # data_record.py
    lines.extend(box(930, 95, 220, 140, "cat-dto",
        ["data_record.py", "Typed DTOs (NamedTuple)"],
        ["HistBarData:", "  date, open, high, low, close",
         "  volume, bar_count, average",
         "FutureTickData:", "  time, bid, ask, last",
         "  bid_size, ask_size, last_size"]))

    # logger.py
    lines.extend(box(930, 265, 220, 140, "cat-lib",
        ["logger.py", "Structured logging (Singleton)"],
        ["configure_pipeline_logging()", "  → console (stdout) INFO",
         "  → rotating file DEBUG (10MB×3)",
         "get_logger(name) — idempotent"]))

    # stream_live_ticks() module-level function callout
    lines.extend(box(930, 450, 220, 125, "cat-lib",
        ["stream_live_ticks()", "Module-level (data_downloader.py)"],
        ["ib, contracts, duration_secs, send_batch",
         "→ Dict[str, int] (written per ric)",
         "Uses _build_ilp_line() helper",
         "Calls send_batch (qdb.send_ilp_batch)"]))

    # ═══════════════════════════════════════════════════════════
    # Bottom panel: Runtime Resources
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="920" width="1140" height="140" class="zone"/>')
    lines.append('  <text x="40" y="937" class="zone-label">Runtime Resources</text>')

    lines.extend(box(40, 950, 220, 90, "cat-res",
        ["configs/", "Configuration files"],
        ["download_live_tick.json — RIC list", ".ibkr_keepalive — on/off flag",
         ".ibkr_stream.pid — PID lock", ".ibkr_gateway.pid — PID lock"]))

    lines.extend(box(300, 950, 200, 90, "cat-res",
        ["scripts/", "IBC shell scripts"],
        ["displaybannerandlaunch.sh", "ibcstart.sh, commandsend.sh",
         "stop.sh, version"]))

    lines.extend(box(540, 950, 180, 90, "cat-res",
        ["logs/", "Rotating log files"],
        ["pipeline.log", "pipeline.log.1 / .2 / .3"]))

    lines.extend(box(760, 950, 160, 90, "cat-res",
        ["tests/", "Test suite"],
        ["test_*.py files", "(in development)"]))

    # ═══════════════════════════════════════════════════════════
    # Edges
    # ═══════════════════════════════════════════════════════════
    # run_service → session_mgr
    lines.append('  <path d="M 180 235 L 180 260 L 185 260 L 185 290" class="edge" marker-end="url(#arrow)"/>')
    # run_service → data_dl
    lines.append('  <path d="M 320 160 L 350 160 L 350 370 L 370 370" class="edge" marker-end="url(#arrow)"/>')
    # run_service → data_record (DTOs)
    lines.append('  <path d="M 320 140 L 920 140 L 920 165" class="edge" marker-end="url(#arrow)"/>')
    # run_service → logger
    lines.append('  <path d="M 320 125 L 920 125" class="edge" marker-end="url(#arrow)"/>')

    # data_dl → session_mgr
    lines.append('  <path d="M 370 340 L 330 340" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → utils
    lines.append('  <path d="M 660 360 L 700 360" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → questdb
    lines.append('  <path d="M 515 465 L 515 500" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → data_record
    lines.append('  <path d="M 660 425 L 920 425 L 920 235" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → CSV
    lines.append('  <path d="M 660 440 L 680 440 L 680 800 L 560 800" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → configs
    lines.append('  <path d="M 515 465 L 515 480 L 150 480 L 150 950" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → stream_live_ticks() (module-level)
    lines.append('  <path d="M 660 490 L 920 490 L 920 450" class="edge" marker-end="url(#arrow)"/>')

    # session_mgr → ibgateway (lifecycle delegation)
    lines.append('  <path d="M 185 465 L 185 500" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → questdb
    lines.append('  <path d="M 330 460 L 330 480 L 515 480 L 515 500" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → IB Gateway
    lines.append('  <path d="M 40 430 L 20 430 L 20 810 L 40 810" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → ibgateway (gateway termination callback flow — dashed)
    lines.append('  <path d="M 60 465 L 60 490 L 85 490 L 85 500" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <text x="50" y="498" class="small" fill="var(--muted)">termination cb</text>')

    # ibgateway → IB Gateway
    lines.append('  <path d="M 185 680 L 185 710 L 150 710 L 150 770" class="edge" marker-end="url(#arrow)"/>')
    # ibgateway → configs
    lines.append('  <path d="M 330 575 L 350 575 L 350 990 L 260 990" class="edge" marker-end="url(#arrow)"/>')
    # ibgateway → scripts
    lines.append('  <path d="M 330 595 L 390 595 L 390 1000 L 400 1000" class="edge" marker-end="url(#arrow)"/>')

    # questdb → QuestDB Server
    lines.append('  <path d="M 515 680 L 515 710 L 410 710 L 410 770" class="edge" marker-end="url(#arrow)"/>')

    # stream_live_ticks → QuestDB Server (send_batch ILP path)
    lines.append('  <path d="M 930 575 L 920 575 L 920 700 L 520 700 L 520 770" class="edge" marker-end="url(#arrow)"/>')

    # logger → various (dashed)
    lines.append('  <path d="M 930 290 L 910 290 L 910 370" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 310 L 750 310 L 750 465" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 325 L 660 325 L 660 530" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 340 L 880 340 L 880 400 L 660 400" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 355 L 880 355 L 880 420 L 660 420" class="dashed" marker-end="url(#arrow)"/>')

    # IB Guard → session_mgr / data_dl
    lines.append('  <path d="M 820 515 L 820 490 L 330 490 L 330 465" class="edge" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 940 525 L 800 525 L 660 525" class="edge" marker-end="url(#arrow)"/>')

    # Legend
    legend_y = 1130
    legend_items = [
        (10, "CLI Entry", "cat-cli"),
        (100, "Application", "cat-app"),
        (210, "Library", "cat-lib"),
        (300, "External", "cat-ext"),
        (390, "Storage", "cat-sto"),
        (480, "Constraint", "cat-risk"),
        (590, "DTOs", "cat-dto"),
        (670, "Resources", "cat-res"),
        (790, "─ Import/Call  ─ ─ Logging", None),
        (970, "┅ Callback/Del.", None),
    ]
    for lx, ltxt, cls in legend_items:
        if cls:
            lines.append(f'  <rect x="{lx+28}" y="{legend_y}" width="12" height="12" class="node {cls}" />')
            lines.append(f'  <text x="{lx+44}" y="{legend_y+10}" class="small">{ltxt}</text>')
        elif "Callback" in ltxt:
            lines.append(f'  <line x1="{lx+20}" y1="{legend_y+6}" x2="{lx+40}" y2="{legend_y+6}" class="dashed" />')
            lines.append(f'  <text x="{lx+46}" y="{legend_y+10}" class="small">{ltxt}</text>')
        else:
            lines.append(f'  <line x1="{lx+20}" y1="{legend_y+6}" x2="{lx+40}" y2="{legend_y+6}" class="edge" />')
            lines.append(f'  <line x1="{lx+50}" y1="{legend_y+6}" x2="{lx+70}" y2="{legend_y+6}" class="dashed" />')
            lines.append(f'  <text x="{lx+76}" y="{legend_y+10}" class="small">{ltxt}</text>')

    lines.append('</svg>')
    lines.append('</main>')
    lines.append('</html>')

    out_path = HERE / "ibkr_conn_uml.html"
    out_path.write_text('\n'.join(lines) + '\n')
    print(f"Written: {out_path}")

if __name__ == "__main__":
    main()
