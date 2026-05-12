---
date: 2026-05-12
topic: boss-visible-browser-login-copilot
title: BOSS Visible Browser Login Copilot Plan
category: plan
source_requirements: https://github.com/wangrenzhu-ola/ai-infra-demand-pool/issues/149
---

# BOSS Visible Browser Login Copilot Plan

## Goal

Create the first safe evidence path for BOSS/Zhipin visible-browser Copilot work. The phase must prove only that Hermes can read sanitized visible-browser status from a user-controlled Chrome session, and must stop when login, verification, SMS, account-security, or ambiguous UI states appear.

## Safety boundary

- Read only Chrome tab title and URL for the current visible browser state.
- Do not read cookies, localStorage, sessionStorage, profile directories, page DOM, private chat contents, passwords, tokens, or screenshots containing private conversations.
- Do not use headless browser login, CAPTCHA handling, stealth parameters, fingerprinting, proxy rotation, or platform security bypass instructions.
- Treat security verification, login challenges, SMS, account exceptions, and ambiguous UI as red-light states that require human handling.

## Implementation units

1. Add a read-only visible-browser status tool at `tools/boss_visible_browser.py`.
2. Use macOS AppleScript title/URL readback as the default source because it can observe the visible Chrome tab without touching session stores.
3. Sanitize URLs by removing query strings, fragments, username, and password fields before writing evidence.
4. Classify BOSS/Zhipin tabs as either `boss_visible_readonly` or `blocked_human_required`.
5. Ignore non-BOSS tabs in the evidence payload except for a count.
6. Add tests proving red-light stop behavior and no browser/session leakage.

## Acceptance mapping

- AC-001: Pass only when a real visible Chrome BOSS/Zhipin tab is observed through sanitized title/URL status.
- AC-002: Pass only when Hermes/Copilot has a fresh read-only command output for the visible authorized page. CDP on `127.0.0.1:9222` is not sufficient unless it is the same visible BOSS browser.
- AC-003: Pass when red-light status returns `blocked_human_required` and gives a human-handling state without bypass instructions.
- AC-004: Pass when tests and command output prove evidence excludes cookies, session storage, localStorage, profile paths, tokens, and passwords.
- AC-005: Pass when a sanitized state JSON and exact acceptance command output are saved under the GCW evidence directory.

## Verification

```bash
python -m pytest tests/tools/test_boss_visible_browser.py
python tools/boss_visible_browser.py --pretty
```

The second command may return `no_boss_visible_tab` when Chrome has no visible BOSS/Zhipin tab, or `blocked_human_required` when the platform asks for login/security verification. Both are valid truthful states, but only `boss_visible_readonly` can support AC-001 and AC-002 delivery.
