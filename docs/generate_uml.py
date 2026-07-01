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
  main { max-width: 1240px; margin: 32px auto; padding: 0 20px; }
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
    lines.append('<svg viewBox="0 0 1200 1100" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,sans-serif">')
    lines.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--line)"/></marker></defs>')

    # Title
    lines.append('  <text x="600" y="30" text-anchor="middle" class="title">ibkr_conn — Module Architecture</text>')
    lines.append('  <text x="600" y="48" text-anchor="middle" class="subtitle">8 Python modules · 3 zones · Typed DTOs · Singleton SessionManager · Runtime resources</text>')

    # ═══════════════════════════════════════════════════════════
    # ZONE 1: CLI Entry (Y: 70–220)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="60" width="1140" height="170" class="zone"/>')
    lines.append('  <text x="40" y="77" class="zone-label">CLI Entry</text>')

    lines.extend(box(40, 95, 240, 120, "cat-cli",
        ["run_service.py", "CLI entry point"],
        ["main() — dispatch by --mode", "build_ibkr_parser() — argparse",
         "_clean_stale_pycache()", "_handle_status() — health output",
         "configure_pipeline_logging() — init"]))

    # ═══════════════════════════════════════════════════════════
    # ZONE 2: Application Logic (Y: 250–700)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="240" width="1140" height="470" class="zone"/>')
    lines.append('  <text x="40" y="257" class="zone-label">Application Logic</text>')

    # ── Row 1 (Y: 270) ──
    # session_manager.py — left
    lines.extend(box(40, 275, 270, 155, "cat-app",
        ["session_manager.py  🔒 Singleton", "SessionManager — owns IB + QuestDB"],
        ["get_ib_conn()  (6×5s internal retry)", "get_questdb() → QuestDBManager",
         "on_error()  (signal connection death)", "start() / stop() — gateway lifecycle",
         "get_status() · keepalive · PID locks",
         "→ IBConnectionFatalError (6 fails)"]))

    # data_downloader.py — center
    lines.extend(box(350, 275, 270, 155, "cat-lib",
        ["data_downloader.py  📦 Client", "DataDownloader — uses SessionManager"],
        ["download_bars()  (error recovery loop)", "start_streaming()  (PID-locked entry)",
         "stream_ticks()  (keepalive loop)", "  → IBConnectionFatalError on abort",
         "_load_tick_config()  (JSON config)",
         "_do_bars_download()  (core bars logic)"]))

    # utils.py — right
    lines.extend(box(660, 275, 200, 155, "cat-lib",
        ["utils.py", "Shared utilities (no connections)"],
        ["build_ric_contract()", "resolve_contracts()",
         "get_contract()", "parse_date_range()",
         "_month_map()"]))

    # ── Row 2 (Y: 470) ──
    # ibgateway.py
    lines.extend(box(40, 475, 270, 150, "cat-app",
        ["ibgateway.py", "Gateway lifecycle (no ib_insync)"],
        ["IBGateway class:", "  start_gateway() — subprocess",
         "  stop_gateway() — nc + kill", "  ensure_gateway() — auto-restart",
         "  wait_for_api() — poll", "  generate_config_ini()",
         "  get_credentials()",
         "Module-level: install_scripts()"]))

    # questdb.py
    lines.extend(box(350, 475, 270, 150, "cat-app",
        ["questdb.py", "QuestDBManager — ILP write operations"],
        ["QuestDBManager (class):", "  send_ilp_batch() — HTTP POST /write",
         "  write_bars() → futures_hist table",
         "  write_ticks() → futures_tick table",
         "Static: is_port_open(), is_questdb_running(), find_questdb_pid()",
         "Module-level: start_questdb(), stop_questdb()"]))

    # IB() Guard Rule
    lines.extend(box(660, 475, 240, 130, "cat-risk",
        ["🔐 IB() Guard Rule",
         "Only session_manager.py may",
         "construct ib_insync.IB()",
         "or call ib.connect()."],
        ["Enforce:", 'grep -rn "IB()" --include="*.py" .',
         "  | grep -v venv | grep -v __pycache__"]))

    # ═══════════════════════════════════════════════════════════
    # ZONE 3: External Dependencies (Y: 730–880)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="720" width="1140" height="170" class="zone"/>')
    lines.append('  <text x="40" y="737" class="zone-label">External Dependencies</text>')

    # IB Gateway
    lines.extend(box(40, 750, 220, 90, "cat-ext",
        ["IB Gateway (TWS)", "TCP :4002 — Paper/live"],
        ["ib_insync library", "IBC controller"]))

    # QuestDB Server
    lines.extend(box(300, 750, 220, 90, "cat-sto",
        ["QuestDB Server", "HTTP :9000 / ILP :9009"],
        ["futures_hist table", "futures_tick table"]))

    # CSV File System
    lines.extend(box(560, 750, 180, 90, "cat-sto",
        ["CSV File System", "Data directory"],
        ["bars CSV export", "(--format csv mode)"]))

    # ═══════════════════════════════════════════════════════════
    # Right panel: Supporting Types
    # ═══════════════════════════════════════════════════════════
    # data_record.py
    lines.extend(box(930, 95, 200, 130, "cat-dto",
        ["data_record.py", "Typed DTOs (NamedTuple)"],
        ["HistBarData:", "  date, open, high, low, close",
         "  volume, bar_count, average",
         "FutureTickData:", "  time, bid, ask, last",
         "  bid_size, ask_size, last_size"]))

    # logger.py
    lines.extend(box(930, 250, 200, 130, "cat-lib",
        ["logger.py", "Structured logging (Singleton)"],
        ["configure_pipeline_logging()", "  → console (stdout) INFO",
         "  → rotating file DEBUG (10MB×3)",
         "get_logger(name) — idempotent"]))

    # ═══════════════════════════════════════════════════════════
    # Bottom panel: Runtime Resources
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="900" width="1140" height="140" class="zone"/>')
    lines.append('  <text x="40" y="917" class="zone-label">Runtime Resources</text>')

    lines.extend(box(40, 930, 220, 90, "cat-res",
        ["configs/", "Configuration files"],
        ["download_live_tick.json — RIC list", ".ibkr_keepalive — on/off flag",
         ".ibkr_stream.pid — PID lock", ".ibkr_gateway.pid — PID lock"]))

    lines.extend(box(300, 930, 200, 90, "cat-res",
        ["scripts/", "IBC shell scripts"],
        ["displaybannerandlaunch.sh", "ibcstart.sh, commandsend.sh",
         "stop.sh, version"]))

    lines.extend(box(540, 930, 180, 90, "cat-res",
        ["logs/", "Rotating log files"],
        ["pipeline.log", "pipeline.log.1 / .2 / .3"]))

    lines.extend(box(760, 930, 160, 90, "cat-res",
        ["tests/", "Test suite"],
        ["test_*.py files", "(in development)"]))

    # ═══════════════════════════════════════════════════════════
    # Edges
    # ═══════════════════════════════════════════════════════════
    # run_service → session_mgr
    lines.append('  <path d="M 160 215 L 160 237 L 175 237 L 175 275" class="edge" marker-end="url(#arrow)"/>')
    # run_service → data_dl
    lines.append('  <path d="M 280 155 L 320 155 L 320 350 L 350 350" class="edge" marker-end="url(#arrow)"/>')
    # run_service → data_record (DTOs)
    lines.append('  <path d="M 280 130 L 920 130 L 920 160" class="edge" marker-end="url(#arrow)"/>')
    # run_service → logger
    lines.append('  <path d="M 280 120 L 920 120" class="edge" marker-end="url(#arrow)"/>')

    # data_dl → session_mgr
    lines.append('  <path d="M 350 330 L 310 330" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → utils
    lines.append('  <path d="M 620 345 L 660 345" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → questdb
    lines.append('  <path d="M 485 430 L 485 475" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → data_record
    lines.append('  <path d="M 620 390 L 920 390 L 920 225" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → CSV
    lines.append('  <path d="M 620 410 L 650 410 L 650 780 L 560 780" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → configs
    lines.append('  <path d="M 485 430 L 485 460 L 150 460 L 150 930" class="edge" marker-end="url(#arrow)"/>')

    # session_mgr → ibgateway
    lines.append('  <path d="M 175 430 L 175 475" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → questdb
    lines.append('  <path d="M 310 430 L 310 460 L 485 460 L 485 475" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → IB Gateway
    lines.append('  <path d="M 40 420 L 20 420 L 20 790 L 40 790" class="edge" marker-end="url(#arrow)"/>')

    # ibgateway → IB Gateway
    lines.append('  <path d="M 175 625 L 175 665 L 150 665 L 150 750" class="edge" marker-end="url(#arrow)"/>')
    # ibgateway → configs
    lines.append('  <path d="M 310 540 L 330 540 L 330 970 L 260 970" class="edge" marker-end="url(#arrow)"/>')
    # ibgateway → scripts
    lines.append('  <path d="M 310 560 L 380 560 L 380 980 L 400 980" class="edge" marker-end="url(#arrow)"/>')

    # questdb → QuestDB Server
    lines.append('  <path d="M 485 625 L 485 665 L 410 665 L 410 750" class="edge" marker-end="url(#arrow)"/>')

    # logger → various (dashed)
    lines.append('  <path d="M 930 275 L 920 275 L 920 350" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 290 L 750 290 L 750 430" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 305 L 640 305 L 640 500" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 320 L 900 320 L 900 370 L 620 370" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 930 335 L 900 335 L 900 395 L 620 395" class="dashed" marker-end="url(#arrow)"/>')

    # IB Guard → session_mgr / data_dl
    lines.append('  <path d="M 780 475 L 780 460 L 310 460 L 310 430" class="edge" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 900 500 L 770 500 L 620 500" class="edge" marker-end="url(#arrow)"/>')

    # Legend
    legend_y = 1070
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
    ]
    for lx, ltxt, cls in legend_items:
        if cls:
            lines.append(f'  <rect x="{lx+28}" y="{legend_y}" width="12" height="12" class="node {cls}" />')
            lines.append(f'  <text x="{lx+44}" y="{legend_y+10}" class="small">{ltxt}</text>')
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
