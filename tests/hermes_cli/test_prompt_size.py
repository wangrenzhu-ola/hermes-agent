from hermes_cli.prompt_size import compute_prompt_breakdown, format_prompt_breakdown


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
    assert set(result["buckets"]) >= {
        "system_stable",
        "skills_index",
        "memory_user",
        "enterprise_recall",
        "project_context_files",
        "tool_schemas",
        "history_tool_outputs",
    }
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
