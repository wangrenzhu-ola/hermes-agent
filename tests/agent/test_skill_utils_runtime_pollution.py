import json
from pathlib import Path


def _write_skill(path: Path, name: str, description: str = "test") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n",
        encoding="utf-8",
    )


def test_iter_skill_index_files_ignores_runtime_pollution_dirs(tmp_path):
    from agent.skill_utils import iter_skill_index_files

    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "software-development" / "galeharness-compound-workflow", "galeharness-compound-workflow")
    _write_skill(
        skills_root
        / "software-development"
        / "galeharness-compound-workflow"
        / ".pmo"
        / "hermes-subagent-runs"
        / "run-1"
        / "worktree"
        / "skills"
        / "galeharness-compound-workflow",
        "galeharness-compound-workflow",
    )
    _write_skill(skills_root / "other" / ".qoder" / "skills" / "qoder-copy", "qoder-copy")
    _write_skill(skills_root / "business" / "memory" / "skills" / "memory-copy", "memory-copy")
    _write_skill(skills_root / ".archive" / "archived-copy", "archived-copy")

    discovered = [p.relative_to(skills_root) for p in iter_skill_index_files(skills_root, "SKILL.md")]

    assert discovered == [
        Path("business/memory/skills/memory-copy/SKILL.md"),
        Path("software-development/galeharness-compound-workflow/SKILL.md"),
    ]


def test_skills_tool_find_prefers_canonical_skill_over_nested_runtime_copy(tmp_path, monkeypatch):
    import tools.skills_tool as skills_tool

    skills_root = tmp_path / "skills"
    canonical = skills_root / "software-development" / "galeharness-compound-workflow"
    _write_skill(canonical, "galeharness-compound-workflow", "canonical")
    nested = (
        canonical
        / ".pmo"
        / "hermes-subagent-runs"
        / "run-1"
        / "worktree"
        / "skills"
        / "galeharness-compound-workflow"
    )
    _write_skill(nested, "galeharness-compound-workflow", "polluted")

    monkeypatch.setattr(skills_tool, "SKILLS_DIR", skills_root)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [])
    monkeypatch.setattr(skills_tool, "_get_disabled_skill_names", lambda: set())

    listed = skills_tool._find_all_skills()
    viewed = json.loads(
        skills_tool.skill_view("galeharness-compound-workflow", preprocess=False)
    )

    assert [skill["name"] for skill in listed] == ["galeharness-compound-workflow"]
    assert listed[0]["description"] == "canonical"
    assert viewed["success"] is True
    assert Path(viewed["skill_dir"]) == canonical
    assert viewed["description"] == "canonical"
