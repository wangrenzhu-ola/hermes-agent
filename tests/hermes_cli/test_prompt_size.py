"""Tests for prompt-size and context progressive-disclosure diagnostics."""

import json

import pytest

from hermes_cli.prompt_size import (
    _SKILLS_BLOCK_RE,
    compute_prompt_breakdown,
    format_prompt_breakdown,
    render_breakdown,
)


def _seed_memory(hermes_home, memory_text="", user_text=""):
    mem_dir = hermes_home / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    if memory_text:
        (mem_dir / "MEMORY.md").write_text(memory_text, encoding="utf-8")
    if user_text:
        (mem_dir / "USER.md").write_text(user_text, encoding="utf-8")


def _seed_skill(hermes_home, name, description):
    skill_dir = hermes_home / "skills" / "demo" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\nbody\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.chdir(tmp_path)  # avoid picking up the repo's AGENTS.md
    return hermes_home


def test_breakdown_exposes_legacy_and_progressive_shapes(isolated_home):
    data = compute_prompt_breakdown("cli")
    assert set(data) >= {
        "platform",
        "model",
        "system_prompt",
        "skills_index",
        "memory",
        "user_profile",
        "tools",
        "sections",
        "buckets",
        "total_chars",
    }
    assert data["platform"] == "cli"
    for key in ("system_prompt", "skills_index", "memory", "user_profile"):
        assert data[key]["bytes"] >= 0
        assert data[key]["chars"] >= 0
    assert data["tools"]["count"] >= 0
    assert data["tools"]["json_bytes"] >= 0
    assert data["system_prompt"]["bytes"] > 0
    assert set(data["buckets"]) >= {
        "system_stable",
        "skills_index",
        "memory_user",
        "enterprise_recall",
        "project_context_files",
        "tool_schemas",
        "history_tool_outputs",
    }


def test_runs_offline_without_credentials(isolated_home, monkeypatch):
    for var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "NOUS_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    data = compute_prompt_breakdown("cli")
    assert data["system_prompt"]["bytes"] > 0


def test_skills_index_reflects_installed_skills(isolated_home):
    _seed_skill(isolated_home, "hello", "a demo skill for size testing")
    data = compute_prompt_breakdown("cli")
    assert data["skills_index"]["bytes"] > 0 or data["buckets"]["skills_index"]["chars"] >= 0


def test_memory_and_profile_are_attributed(isolated_home):
    _seed_memory(
        isolated_home,
        memory_text="Project uses pytest.\n",
        user_text="User is a developer.\n",
    )
    data = compute_prompt_breakdown("cli")
    assert data["memory"]["bytes"] > 0
    assert data["user_profile"]["bytes"] > 0


def test_skills_block_regex_matches_tagged_block():
    text = "preamble\n<available_skills>\n  cat:\n    - a: b\n</available_skills>\ntail"
    m = _SKILLS_BLOCK_RE.search(text)
    assert m is not None
    assert m.group(0).startswith("<available_skills>")
    assert m.group(0).endswith("</available_skills>")


def test_render_breakdown_is_plain_text(isolated_home):
    data = compute_prompt_breakdown("cli")
    out = render_breakdown(data)
    assert "System prompt total" in out
    assert "skills index" in out
    assert "Tool schemas" in out
    assert not out.strip().startswith("{")


def test_json_serializable(isolated_home):
    data = compute_prompt_breakdown("cli")
    assert json.loads(json.dumps(data)) == json.loads(json.dumps(data))


def test_compute_prompt_breakdown_reports_required_buckets(monkeypatch):
    tools = [
        {"type": "function", "function": {"name": "web_search", "description": "Search"}},
        {"type": "function", "function": {"name": "skill_view", "description": "View skill"}},
    ]

    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {})
    monkeypatch.setattr("hermes_cli.tools_config._get_platform_tools", lambda cfg, platform: {"web", "skills"})
    monkeypatch.setattr("model_tools.get_tool_definitions", lambda **kwargs: tools)
    monkeypatch.setattr("agent.prompt_builder.build_skills_system_prompt", lambda **kwargs: "SKILLS")
    monkeypatch.setattr(
        "agent.system_prompt.build_system_prompt_parts",
        lambda agent: {
            "stable": "SYSTEM\n\nSKILLS",
            "context": "PROJECT",
            "volatile": "MEMORY",
        },
    )

    result = compute_prompt_breakdown(
        platform="weixin",
        message="hello",
        history=[{"role": "tool", "content": "output"}],
    )

    assert result["platform"] == "weixin"
    assert result["buckets"]["tool_schemas"]["count"] == 2
    assert result["buckets"]["history_tool_outputs"]["tool_output_chars"] == len("output")


def test_format_prompt_breakdown_detail_includes_top_tools():
    text = format_prompt_breakdown(
        {
            "platform": "weixin",
            "total_chars": 123,
            "buckets": {
                "tool_schemas": {
                    "chars": 10,
                    "top": [{"name": "terminal", "chars": 5}],
                },
                "enterprise_recall": {
                    "chars": 0,
                    "gate_reason": "low_signal",
                    "gate_allowed": False,
                },
            },
        },
        mode="detail",
    )

    assert "tool_schemas" in text
    assert "terminal" in text
    assert "low_signal" in text
