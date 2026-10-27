"""The page a project's tab shows BEFORE it runs — and the one it keeps when
it runs without a dashboard.

Why this exists: selecting a project used to start it immediately, which meant
a click in the sidebar launched whatever the project does (a server, a bot,
sometimes both). Opening a tab should be free; running it should be something
the user asks for. So the tab opens on this page, with one Start button.

The page is plain HTML rendered in the project's own webview, styled from the
app's palette so it matches the rest of the window. The button is an ordinary
link to `https://hub.invalid/start/<project id>`: a custom scheme is NOT an
option, because QtWebEngine drops `hub://...` clicks without ever asking the
page about them (verified). The window intercepts that navigation and starts
the project — see window._HubPage.acceptNavigationRequest.

For a project with no dashboard (a Discord bot, a worker), the same page
becomes a status card once it is running: "Project is running" instead of a
button, because there is nothing to open.
"""

from __future__ import annotations

import html
from urllib.parse import quote

# Where the Start link points. An unresolvable host we always intercept; it
# must never answer DNS, so a click can never escape to a real site.
ACTION_HOST = "hub.invalid"

_DEFAULT_COLORS = {
    "bg": "#1e1f22",
    "fg": "#e6e6e6",
    "muted": "#9aa0a6",
    "accent": "#3b6fd4",
    "accent_fg": "#ffffff",
    "ok": "#3fb950",
    "bad": "#d5434f",
}


def action_url(project_id: str, action: str = "start") -> str:
    """The URL a page button navigates to, intercepted by the window."""
    return f"https://{ACTION_HOST}/{action}/{quote(project_id, safe='')}"


def _colors(colors: dict | None) -> dict:
    out = dict(_DEFAULT_COLORS)
    if colors:
        out.update({k: v for k, v in colors.items() if v})
    return out


def _shell(title: str, body: str, colors: dict) -> str:
    c = _colors(colors)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
  html, body {{ height: 100%; margin: 0; }}
  body {{
    background: {c['bg']}; color: {c['fg']};
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    display: flex; align-items: center; justify-content: center;
    -webkit-user-select: none; user-select: none;
  }}
  .card {{ text-align: center; max-width: 560px; padding: 36px 32px; }}
  h1 {{ font-size: 21px; font-weight: 600; margin: 0 0 6px; }}
  .cmd {{
    font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px;
    color: {c['muted']}; margin: 0 0 28px; word-break: break-all;
  }}
  .btn {{
    display: inline-block; padding: 12px 40px; border-radius: 9px;
    background: {c['accent']}; color: {c['accent_fg']};
    text-decoration: none; font-size: 15px; font-weight: 600;
    cursor: pointer;
  }}
  .btn:hover {{ filter: brightness(1.1); }}
  .hint {{ margin: 18px 0 0; font-size: 12px; color: {c['muted']}; }}
  .status {{ font-size: 16px; font-weight: 600; margin: 0 0 8px; }}
  .dot {{
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    background: {c['ok']}; margin-right: 8px; vertical-align: 1px;
  }}
  .detail {{
    font-size: 12px; color: {c['bad']}; margin: 0 0 22px;
    white-space: pre-wrap; text-align: left;
  }}
</style></head>
<body><div class="card">
{body}
</div></body></html>
"""


def start_page_html(
    rec: dict,
    state: str = "stopped",
    detail: str = "",
    colors: dict | None = None,
) -> str:
    """The tab's page for a project that is not showing a dashboard.

    `state` is the process state: "stopped" / "error" show the Start button,
    "starting" says so and offers nothing to click, "running" becomes the
    status card used by projects that have no dashboard at all. "stopping"
    explains a requested Stop whose child has not actually exited yet.
    """
    name = html.escape(str(rec.get("name") or "Project"))
    command = html.escape(str(rec.get("command") or ""))
    pid = str(rec.get("id") or "")
    c = _colors(colors)

    if state == "stopping":
        body = (
            f'<p class="status">Stopping {name}…</p>'
            '<p class="hint" style="margin-top:0">Waiting for the process to exit. '
            'The Hub will finish stopping it if it does not exit cleanly.</p>'
        )
        return _shell(name, body, c)

    if state == "running":
        body = (
            f'<p class="status"><span class="dot"></span>Project is running</p>'
            f"<p class=\"hint\" style=\"margin-top:0\">{name} has no dashboard to open — "
            f"its output is in its terminal below.</p>"
        )
        return _shell(name, body, c)

    if state == "starting":
        body = (
            f'<p class="status">Starting {name}…</p>'
            f'<p class="hint" style="margin-top:0">This page will show its dashboard '
            f"once it answers, or stay here if it has none.</p>"
        )
        return _shell(name, body, c)

    if state == "error":
        lead = (
            f'<p class="detail">{html.escape(detail)}</p>'
            if detail
            else '<p class="detail">It stopped with an error — its terminal has the details.</p>'
        )
        body = (
            f"<h1>{name}</h1><p class=\"cmd\">{command}</p>{lead}"
            f'<a class="btn" href="{action_url(pid, "start")}">Start</a>'
            f'<p class="hint">Press Start to try again.</p>'
        )
        return _shell(name, body, c)

    # stopped: the ordinary case a tab opens on.
    extra = f'<p class="detail">{html.escape(detail)}</p>' if detail else ""
    body = (
        f"<h1>{name}</h1><p class=\"cmd\">{command}</p>{extra}"
        f'<a class="btn" href="{action_url(pid, "start")}">Start</a>'
        f'<p class="hint">Nothing runs until you press Start.</p>'
    )
    return _shell(name, body, c)
