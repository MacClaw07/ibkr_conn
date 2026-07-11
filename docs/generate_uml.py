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
    lines.append('<svg viewBox="0 0 1200 1200" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,sans-serif">')
    lines.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--line)"/></marker></defs>')

    # Title
    lines.append('  <text x="600" y="30" text-anchor="middle" class="title">ibkr_conn — Module Architecture</text>')
    lines.append('  <text x="600" y="48" text-anchor="middle" class="subtitle">Updated: July 2026 · 8 Python modules · 3 zones · Typed DTOs · Singleton SessionManager · FOP support · Runtime resources</text>')

    # ═══════════════════════════════════════════════════════════
    # ZONE 1: CLI Entry (Y: 60–200)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="60" width="1140" height="150" class="zone"/>')
    lines.append('  <text x="40" y="77" class="zone-label">CLI Entry</text>')

    lines.extend(box(40, 80, 280, 110, "cat-cli",
        ["run_service.py", "CLI entry point"],
        ["Auto-reinvoke with project venv (os.execv)", "main() — dispatch by --mode",
         "build_ibkr_parser() — argparse", "_clean_stale_pycache()",
         "_handle_status() — health output"]))

    # ═══════════════════════════════════════════════════════════
    # ZONE 2: Application Logic (Y: 220–730)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="220" width="1140" height="520" class="zone"/>')
    lines.append('  <text x="40" y="237" class="zone-label">Application Logic</text>')

    # ── Row 1 (Y: 250) ──
    # session_manager.py — left
    lines.extend(box(40, 250, 290, 190, "cat-app",
        ["session_manager.py  🔒 Singleton", "SessionManager — owns IB + QuestDB"],
        ["get_ib_conn()  (6×5s internal retry)", "get_questdb() → QuestDBManager",
         "on_error()  (signal connection death)", "start() / stop() — gateway + QuestDB lifecycle",
         "get_status() · keep_alive() · set_keepalive()",
         "acquire_pid_lock() / release_pid_lock()",
         "_ensure_gateway_ready() · set_gateway_status()",
         "_get_gateway_status() · _force_disconnect_ib()",
         "_on_gateway_terminated(pid) — callback",
         "→ IBConnectionFatalError (6 fails)"]))

    # data_downloader.py — center
    lines.extend(box(370, 250, 290, 190, "cat-lib",
        ["data_downloader.py  📦 Client", "DataDownloader — uses SessionManager"],
        ["__init__(mgr: SessionManager) — DI", "download_bars() — error recovery + ILP write",
         "  supports FUT + FOP (options) hist bars",
         "start_streaming() — PID-locked entry",
         "stream_data() — keepalive loop + reconnect",
         "Module-level helpers:",
         "  _generate_chunks() · _fetch_chunk()",
         "  _download_bars() — multi-chunk + dedup",
         "  _to_hist_bar() → HistBarData",
         "  _to_hist_option_bar() → HistBarOptionData",
         "  _build_ilp_line() — ticker → ILP line",
         "  _stream_live_ticks() · _subscribe_contracts()",
         "  _flush_pending_lines() · _log_stream_status()"]))

    # utils.py — right
    lines.extend(box(700, 250, 200, 190, "cat-lib",
        ["utils.py", "Shared utilities (no connections)"],
        ["build_ric_contract() → Future/FutOpt/Stock",
         "resolve_contracts() — multi from dict",
         "get_contract() — single from CLI args",
         "parse_date_range()", "load_tick_config() — JSON validation",
         "_month_map()", "resolve_option_underlying()"]))

    # ── Row 2 (Y: 475) ──
    # ibgateway.py
    lines.extend(box(40, 475, 290, 210, "cat-app",
        ["ibgateway.py", "Gateway lifecycle (encapsulated)"],
        ["IBGateway class:", "  __init__(on_gateway_terminated=[])",
         "  get_credentials() — static", "  generate_config_ini(paper) — instance",
         "  add_gateway_terminated_handler()",
         "  start_gateway() — daemon subprocess",
         "  stop_gateway() — socket STOP + Java kill",
         "  ensure_gateway(mgr, timeout) — auto-restart",
         "  wait_for_api(mgr, timeout) — poll loop",
         "  _send_stop_via_nc() — private",
         "  _kill_java_processes() — private",
         "  _probe_gateway_api() — temp IB() probe",
         "    (never exports IB instance)",
         "Module-level:", "  get_credentials() · generate_config_ini()",
         "  install_scripts()"]))

    # questdb.py
    lines.extend(box(370, 475, 290, 210, "cat-app",
        ["questdb.py", "QuestDBManager — ILP writer (no IB dep)"],
        ["QuestDBManager:", "  __init__(host, port=9000)", "  url property → REST base URL",
         "  send_ilp_batch(lines) → int (count written)",
         "  write_bars() → futures_hist / options_hist",
         "    supports FUT + FOP sec types",
         "  write_ticks() → futures_tick",
         "  Static: is_port_open(host, port)",
         "  Static: is_questdb_running()",
         "  Static: find_questdb_pid()",
         "  Static: _ok(val) — NaN guard",
         "  Static: _format_ilp_timestamp(dt) → ns",
         "Module-level:", "  start_questdb() · stop_questdb()",
         "  (called by SessionManager)"]))

    # IB() Guard Rule
    lines.extend(box(700, 490, 240, 120, "cat-risk",
        ["🔐 IB() Guard Rule",
         "Only session_manager.py may",
         "construct ib_insync.IB()",
         "or call ib.connect()."],
        ["ibgateway._probe_gateway_api() uses temp IB()",
         "for availability probing only —",
         "never exports or stores the instance."]))

    # ═══════════════════════════════════════════════════════════
    # ZONE 3: External Dependencies (Y: 760–890)
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="750" width="1140" height="150" class="zone"/>')
    lines.append('  <text x="40" y="767" class="zone-label">External Dependencies</text>')

    # IB Gateway
    lines.extend(box(40, 780, 220, 85, "cat-ext",
        ["IB Gateway (TWS)", "TCP :4002 — Paper/live"],
        ["ib_insync library", "IBC controller"]))

    # QuestDB Server
    lines.extend(box(300, 780, 230, 85, "cat-sto",
        ["QuestDB Server", "HTTP :9000"],
        ["futures_hist · options_hist", "futures_tick · options_tick"]))

    # ═══════════════════════════════════════════════════════════
    # Right panel: Supporting Types
    # ═══════════════════════════════════════════════════════════
    # data_record.py
    lines.extend(box(930, 80, 220, 160, "cat-dto",
        ["data_record.py", "Typed DTOs (NamedTuple)"],
        ["HistBarData:", "  date, open, high, low, close",
         "  volume, bar_count, average",
         "HistBarOptionData:", "  date, underlying_ric, type, strike",
         "  open, high, low, close",
         "  volume, bar_count, average",
         "FutureTickData:", "  time, bid, ask, last",
         "  bid_size, ask_size, last_size"]))

    # logger.py
    lines.extend(box(930, 270, 220, 120, "cat-lib",
        ["logger.py", "Structured logging (Singleton)"],
        ["configure_pipeline_logging()", "  → console (stdout) INFO",
         "  → rotating file DEBUG (10MB×3)",
         "get_logger(name) — idempotent"]))

    # ═══════════════════════════════════════════════════════════
    # Bottom panel: Runtime Resources
    # ═══════════════════════════════════════════════════════════
    lines.append('  <rect x="30" y="910" width="1140" height="140" class="zone"/>')
    lines.append('  <text x="40" y="927" class="zone-label">Runtime Resources</text>')

    lines.extend(box(40, 940, 220, 90, "cat-res",
        ["configs/", "Configuration files"],
        ["download_live_tick.json — RIC list", ".ibkr_keepalive — on/off flag",
         ".ibkr_stream.pid — PID lock", ".ibkr_gateway.pid — PID lock"]))

    lines.extend(box(300, 940, 200, 90, "cat-res",
        ["scripts/", "IBC shell scripts"],
        ["displaybannerandlaunch.sh", "ibcstart.sh, commandsend.sh",
         "stop.sh, version"]))

    lines.extend(box(540, 940, 180, 90, "cat-res",
        ["logs/", "Rotating log files"],
        ["pipeline.log", "pipeline.log.1 / .2 / .3"]))

    lines.extend(box(760, 940, 160, 90, "cat-res",
        ["tests/", "Test suite"],
        ["test_data_downloader.py", "test_ibgateway_readiness.py",
         "test_resolve_contracts.py"]))

    # ═══════════════════════════════════════════════════════════
    # Edges
    # ═══════════════════════════════════════════════════════════
    # run_service → session_mgr
    lines.append('  <path d="M 180 190 L 180 220 L 185 220 L 185 250" class="edge" marker-end="url(#arrow)"/>')
    # run_service → data_dl
    lines.append('  <path d="M 320 135 L 350 135 L 350 345 L 370 345" class="edge" marker-end="url(#arrow)"/>')
    # run_service → data_record (DTOs)
    lines.append('  <path d="M 320 120 L 920 120 L 920 160" class="edge" marker-end="url(#arrow)"/>')
    # run_service → logger
    lines.append('  <path d="M 320 105 L 920 105 L 920 270" class="edge" marker-end="url(#arrow)"/>')

    # data_dl → session_mgr
    lines.append('  <path d="M 370 315 L 330 315" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → utils
    lines.append('  <path d="M 660 325 L 700 325" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → questdb
    lines.append('  <path d="M 515 440 L 515 475" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → data_record
    lines.append('  <path d="M 660 370 L 920 370 L 920 240" class="edge" marker-end="url(#arrow)"/>')
    # data_dl → configs (reads download_live_tick.json)
    lines.append('  <path d="M 515 440 L 515 455 L 150 455 L 150 940" class="edge" marker-end="url(#arrow)"/>')

    # session_mgr → ibgateway (lifecycle delegation)
    lines.append('  <path d="M 185 440 L 185 475" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → questdb
    lines.append('  <path d="M 330 440 L 330 580 L 515 580 L 515 475" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → IB Gateway
    lines.append('  <path d="M 40 360 L 20 360 L 20 820 L 40 820" class="edge" marker-end="url(#arrow)"/>')
    # session_mgr → ibgateway (gateway termination callback flow — dashed)
    lines.append('  <path d="M 60 440 L 60 465 L 85 465 L 85 475" class="dashed" marker-end="url(#arrow)"/>')
    lines.append('  <text x="50" y="473" class="small" fill="var(--muted)">termination cb</text>')

    # ibgateway → IB Gateway
    lines.append('  <path d="M 185 685 L 185 720 L 150 720 L 150 780" class="edge" marker-end="url(#arrow)"/>')
    # ibgateway → configs (generates config.ini)
    lines.append('  <path d="M 185 685 L 185 695 L 150 695 L 150 940" class="edge" marker-end="url(#arrow)"/>')
    # ibgateway → scripts
    lines.append('  <path d="M 330 580 L 390 580 L 390 985 L 400 985" class="edge" marker-end="url(#arrow)"/>')

    # questdb → QuestDB Server
    lines.append('  <path d="M 515 685 L 515 710 L 415 710 L 415 780" class="edge" marker-end="url(#arrow)"/>')

    # logger → various (dashed)
    # logger → data_dl
    lines.append('  <path d="M 930 330 L 660 330 L 660 370" class="dashed" marker-end="url(#arrow)"/>')
    # logger → session_mgr
    lines.append('  <path d="M 930 310 L 750 310 L 750 410" class="dashed" marker-end="url(#arrow)"/>')
    # logger → ibgateway
    lines.append('  <path d="M 930 350 L 800 350 L 800 540" class="dashed" marker-end="url(#arrow)"/>')
    # logger → questdb
    lines.append('  <path d="M 930 370 L 800 370 L 800 560" class="dashed" marker-end="url(#arrow)"/>')
    # logger → utils
    lines.append('  <path d="M 930 355 L 880 355 L 880 410 L 900 410" class="dashed" marker-end="url(#arrow)"/>')

    # IB Guard → session_mgr / data_dl
    lines.append('  <path d="M 820 490 L 820 465 L 330 465 L 330 440" class="edge" marker-end="url(#arrow)"/>')
    lines.append('  <path d="M 940 530 L 660 530 L 660 440" class="edge" marker-end="url(#arrow)"/>')

    # Legend
    legend_y = 1150
    legend_items = [
        (10, "CLI Entry", "cat-cli"),
        (100, "Application", "cat-app"),
        (210, "Library", "cat-lib"),
        (300, "External", "cat-ext"),
        (390, "Storage", "cat-sto"),
        (480, "Constraint", "cat-risk"),
        (590, "DTOs", "cat-dto"),
        (670, "Resources", "cat-res"),
        (790, "─ Import/Call    ─ ─ Logging", None),
        (990, "┅ Callback/Del.", None),
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
