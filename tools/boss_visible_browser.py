"""Read-only visible-browser status probe for BOSS/Zhipin.

This module intentionally reads only visible browser tab titles and URLs. It does
not touch cookies, storage, browser profiles, page contents, screenshots, or CDP.
It is designed for human-in-the-loop login flows where login, verification, SMS,
account-security, or ambiguous UI states must stop for human handling.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit


BOSS_HOST_MARKERS = ("zhipin.com", "bosszhipin.com", "kanzhun.com")
RED_LIGHT_MARKERS = (
    "captcha",
    "verify",
    "verification",
    "security",
    "safe",
    "risk",
    "login",
    "signin",
    "sms",
    "验证码",
    "验证",
    "安全",
    "异常",
    "登录",
    "短信",
    "手机号",
)
SESSION_LEAK_MARKERS = (
    "cookie",
    "localstorage",
    "sessionstorage",
    "token",
    "password",
    "authorization",
)


@dataclass(frozen=True)
class VisibleTab:
    title: str
    url: str
    active: bool = False


@dataclass(frozen=True)
class TabStatus:
    title_hint: str
    url: str
    state: str
    active: bool
    red_light: bool
    human_action_required: bool


def sanitize_url(url: str) -> str:
    """Return URL without query, fragment, username, or password material."""
    parts = urlsplit(url.strip())
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def is_boss_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == marker or host.endswith(f".{marker}") for marker in BOSS_HOST_MARKERS)


def is_red_light(title: str, url: str) -> bool:
    haystack = f"{title} {url}".lower()
    return any(marker.lower() in haystack for marker in RED_LIGHT_MARKERS)


def title_hint(title: str, url: str) -> str:
    if is_boss_url(url):
        return "BOSS/Zhipin visible tab observed"
    if title:
        return "Non-BOSS tab observed"
    return "Untitled tab observed"


def classify_tab(tab: VisibleTab) -> TabStatus:
    sanitized_url = sanitize_url(tab.url)
    red_light = is_boss_url(sanitized_url) and is_red_light(tab.title, sanitized_url)
    if red_light:
        state = "blocked_human_required"
    elif is_boss_url(sanitized_url):
        state = "boss_visible_readonly"
    else:
        state = "non_boss_ignored"

    return TabStatus(
        title_hint=title_hint(tab.title, sanitized_url),
        url=sanitized_url,
        state=state,
        active=tab.active,
        red_light=red_light,
        human_action_required=red_light,
    )


def parse_osascript_rows(output: str) -> list[VisibleTab]:
    tabs: list[VisibleTab] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        active_raw, title, url = parts
        tabs.append(VisibleTab(title=title, url=url, active=active_raw == "1"))
    return tabs


def _run_osascript(script: str, timeout: int = 10) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout


def _read_chrome_front_tab() -> list[VisibleTab]:
    script = r'''
set tabChar to ASCII character 9
tell application "Google Chrome"
  if (count of windows) = 0 then return ""
  set u to URL of active tab of front window
  set t to title of active tab of front window
  return "1" & tabChar & (t as text) & tabChar & (u as text)
end tell
'''
    return parse_osascript_rows(_run_osascript(script))


def _read_chrome_all_tabs() -> list[VisibleTab]:
    script = r'''
set outputLines to {}
set tabChar to ASCII character 9
tell application "Google Chrome"
  repeat with w in windows
    set activeTabIndex to active tab index of w
    set tabIndex to 1
    repeat with t in tabs of w
      set activeFlag to "0"
      if tabIndex is activeTabIndex then set activeFlag to "1"
      set end of outputLines to activeFlag & tabChar & (title of t as text) & tabChar & (URL of t as text)
      set tabIndex to tabIndex + 1
    end repeat
  end repeat
end tell
set AppleScript's text item delimiters to linefeed
return outputLines as text
'''
    return parse_osascript_rows(_run_osascript(script))


def read_chrome_tabs() -> list[VisibleTab]:
    """Read the front visible Chrome tab title/URL via AppleScript on macOS.

    The acceptance signal must come from the user-visible active tab, not from a
    background tab in another Chrome window. Keeping this front-tab-only also
    prevents unrelated tabs from leaking into evidence beyond the sanitized
    visible title/URL status.
    """
    if platform.system() != "Darwin":
        raise RuntimeError("visible Chrome title/url readback is only supported on macOS")

    return _read_chrome_front_tab()


def read_preflight_tabs(path: Path) -> list[VisibleTab]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tabs = []
    for tab in data.get("tabs", []):
        tabs.append(
            VisibleTab(
                title=str(tab.get("title_hint") or ""),
                url=str(tab.get("url") or ""),
                active=bool(tab.get("active", False)),
            )
        )
    return tabs


def build_status(tabs: Iterable[VisibleTab]) -> dict[str, object]:
    statuses = [classify_tab(tab) for tab in tabs]
    boss_statuses = [status for status in statuses if status.state != "non_boss_ignored"]
    red_lights = [status for status in boss_statuses if status.red_light]

    if red_lights:
        overall_state = "blocked_human_required"
    elif boss_statuses:
        overall_state = "boss_visible_readonly"
    else:
        overall_state = "no_boss_visible_tab"

    return {
        "schema_version": "BossVisibleBrowserStatus.v1",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "title/url readback only; sensitive browser material is not read",
        "mode": "readonly_visible_browser_status",
        "overall_state": overall_state,
        "red_light": bool(red_lights),
        "human_action_required": bool(red_lights),
        "tabs": [asdict(status) for status in boss_statuses],
        "ignored_tab_count": len(statuses) - len(boss_statuses),
    }


def build_unavailable_status(error: Exception) -> dict[str, object]:
    return {
        "schema_version": "BossVisibleBrowserStatus.v1",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "title/url readback only; sensitive browser material is not read",
        "mode": "readonly_visible_browser_status",
        "overall_state": "browser_readback_unavailable",
        "red_light": False,
        "human_action_required": True,
        "tabs": [],
        "ignored_tab_count": 0,
        "error_class": error.__class__.__name__,
        "error_summary": "Visible Chrome title/url readback failed; human handling required.",
    }


def assert_no_session_leak(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    leaked = sorted(marker for marker in SESSION_LEAK_MARKERS if marker in serialized)
    if leaked:
        raise RuntimeError(f"status payload contains forbidden session material markers: {', '.join(leaked)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read sanitized BOSS/Zhipin visible-browser status.")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    parser.add_argument(
        "--from-preflight",
        type=Path,
        help="classify an existing sanitized title/url preflight JSON instead of reading Chrome",
    )
    args = parser.parse_args(argv)

    try:
        tabs = read_preflight_tabs(args.from_preflight) if args.from_preflight else read_chrome_tabs()
        payload = build_status(tabs)
    except Exception as exc:
        payload = build_unavailable_status(exc)
    assert_no_session_leak(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 2 if payload["overall_state"] == "browser_readback_unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
