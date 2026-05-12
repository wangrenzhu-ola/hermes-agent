import json

from tools import boss_visible_browser
from tools.boss_visible_browser import (
    VisibleTab,
    assert_no_session_leak,
    build_status,
    build_unavailable_status,
    classify_tab,
    is_boss_url,
    parse_osascript_rows,
    read_chrome_tabs,
    read_preflight_tabs,
    sanitize_url,
)


def test_sanitize_url_removes_query_fragment_and_userinfo():
    assert (
        sanitize_url("https://user:secret@www.zhipin.com/web/chat/airecruitement?token=abc#frag")
        == "https://www.zhipin.com/web/chat/airecruitement"
    )


def test_boss_host_matching_requires_exact_host_or_subdomain():
    assert is_boss_url("https://www.zhipin.com/web/chat/airecruitement") is True
    assert is_boss_url("https://zhipin.com/web/chat/airecruitement") is True
    assert is_boss_url("https://notzhipin.com/web/chat/airecruitement") is False
    assert is_boss_url("https://zhipin.com.evil.example/web/chat/airecruitement") is False


def test_visible_boss_tab_is_readonly_and_sanitized():
    status = build_status(
        [
            VisibleTab(
                title="BOSS直聘",
                url="https://www.zhipin.com/web/chat/airecruitement?secret=value",
                active=True,
            )
        ]
    )

    assert status["overall_state"] == "boss_visible_readonly"
    assert status["red_light"] is False
    assert status["tabs"][0]["url"] == "https://www.zhipin.com/web/chat/airecruitement"
    assert status["tabs"][0]["title_hint"] == "BOSS/Zhipin visible tab observed"
    assert "secret=value" not in json.dumps(status, ensure_ascii=False)


def test_red_light_state_requires_human_and_does_not_suggest_bypass():
    tab_status = classify_tab(
        VisibleTab(
            title="安全验证 - BOSS直聘",
            url="https://www.zhipin.com/web/user/safe/verify?ticket=abc",
            active=True,
        )
    )

    assert tab_status.state == "blocked_human_required"
    assert tab_status.red_light is True
    assert tab_status.human_action_required is True
    serialized = json.dumps(tab_status.__dict__, ensure_ascii=False).lower()
    assert "bypass" not in serialized
    assert "stealth" not in serialized


def test_non_boss_tabs_are_ignored_from_evidence():
    status = build_status(
        [
            VisibleTab(title="Nimbalyst", url="file:///Applications/Nimbalyst.app/index.html"),
            VisibleTab(title="Search", url="https://www.google.com.hk/search?q=zhipin"),
        ]
    )

    assert status["overall_state"] == "no_boss_visible_tab"
    assert status["tabs"] == []
    assert status["ignored_tab_count"] == 2


def test_osascript_parser_tracks_active_flag_without_page_content():
    rows = "1\tBOSS直聘\thttps://www.zhipin.com/web/chat/airecruitement\n0\tOther\thttps://example.com/"
    tabs = parse_osascript_rows(rows)

    assert tabs == [
        VisibleTab(title="BOSS直聘", url="https://www.zhipin.com/web/chat/airecruitement", active=True),
        VisibleTab(title="Other", url="https://example.com/", active=False),
    ]


def test_chrome_readback_uses_front_visible_tab_only(monkeypatch):
    front_tab = VisibleTab(title="Search", url="https://www.google.com/search?q=boss", active=True)

    monkeypatch.setattr(boss_visible_browser.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(boss_visible_browser, "_read_chrome_front_tab", lambda: [front_tab])
    monkeypatch.setattr(
        boss_visible_browser,
        "_read_chrome_all_tabs",
        lambda: (_ for _ in ()).throw(AssertionError("background tabs must not drive visible evidence")),
    )

    assert read_chrome_tabs() == [front_tab]
    assert build_status(read_chrome_tabs())["overall_state"] == "no_boss_visible_tab"


def test_session_leak_guard_rejects_sensitive_payload_markers():
    payload = {
        "schema_version": "BossVisibleBrowserStatus.v1",
        "tabs": [{"url": "https://www.zhipin.com/web/chat/airecruitement", "cookie": "secret"}],
    }

    try:
        assert_no_session_leak(payload)
    except RuntimeError as exc:
        assert "cookie" in str(exc)
    else:
        raise AssertionError("expected cookie marker to be rejected")


def test_unavailable_status_is_structured_and_requires_human():
    status = build_unavailable_status(RuntimeError("raw operating system error"))

    assert status["overall_state"] == "browser_readback_unavailable"
    assert status["human_action_required"] is True
    assert "raw operating system error" not in json.dumps(status, ensure_ascii=False)


def test_preflight_reader_uses_only_sanitized_tab_fields(tmp_path):
    preflight = tmp_path / "preflight.json"
    preflight.write_text(
        json.dumps(
            {
                "tabs": [
                    {
                        "title_hint": "BOSS/Zhipin visible tab observed",
                        "url": "https://www.zhipin.com/web/chat/airecruitement?ignored=1",
                        "cookie": "must-not-be-read",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    status = build_status(read_preflight_tabs(preflight))

    assert status["overall_state"] == "boss_visible_readonly"
    assert status["tabs"][0]["url"] == "https://www.zhipin.com/web/chat/airecruitement"
    assert "must-not-be-read" not in json.dumps(status, ensure_ascii=False)
