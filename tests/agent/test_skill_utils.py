"""Tests for agent/skill_utils.py — extract_skill_conditions metadata handling."""

from agent.skill_utils import (
    extract_skill_conditions,
    normalize_skill_description,
    parse_frontmatter,
)


def test_metadata_as_dict_with_hermes():
    """Normal case: metadata is a dict containing hermes keys."""
    frontmatter = {
        "metadata": {
            "hermes": {
                "fallback_for_toolsets": ["toolset_a"],
                "requires_toolsets": ["toolset_b"],
                "fallback_for_tools": ["tool_x"],
                "requires_tools": ["tool_y"],
            }
        }
    }
    result = extract_skill_conditions(frontmatter)
    assert result["fallback_for_toolsets"] == ["toolset_a"]
    assert result["requires_toolsets"] == ["toolset_b"]
    assert result["fallback_for_tools"] == ["tool_x"]
    assert result["requires_tools"] == ["tool_y"]


def test_metadata_as_string_does_not_crash():
    """Bug case: metadata is a non-dict truthy value (e.g. a YAML string)."""
    frontmatter = {"metadata": "some text"}
    result = extract_skill_conditions(frontmatter)
    assert result == {
        "fallback_for_toolsets": [],
        "requires_toolsets": [],
        "fallback_for_tools": [],
        "requires_tools": [],
    }


def test_metadata_as_none():
    """metadata key is present but set to null/None."""
    frontmatter = {"metadata": None}
    result = extract_skill_conditions(frontmatter)
    assert result == {
        "fallback_for_toolsets": [],
        "requires_toolsets": [],
        "fallback_for_tools": [],
        "requires_tools": [],
    }


def test_metadata_missing_entirely():
    """metadata key is absent from frontmatter."""
    frontmatter = {"name": "my-skill", "description": "Does stuff."}
    result = extract_skill_conditions(frontmatter)
    assert result == {
        "fallback_for_toolsets": [],
        "requires_toolsets": [],
        "fallback_for_tools": [],
        "requires_tools": [],
    }


def test_parse_frontmatter_folded_description_normalizes_to_text():
    content = """\
---
name: folded-skill
description: >-
  Detects fixed font sizes,
  clipped labels, and Dynamic Type suppression.
---

# Folded Skill
"""
    frontmatter, _ = parse_frontmatter(content)
    assert (
        normalize_skill_description(frontmatter)
        == "Detects fixed font sizes, clipped labels, and Dynamic Type suppression."
    )


def test_parse_frontmatter_literal_description_normalizes_to_text():
    content = """\
---
name: literal-skill
description: |
  First line.
  Second line.
---

# Literal Skill
"""
    frontmatter, _ = parse_frontmatter(content)
    assert normalize_skill_description(frontmatter) == "First line.\nSecond line."


def test_parse_frontmatter_quoted_description_still_supported():
    content = """\
---
name: quoted-skill
description: "A quoted one-line description."
---

# Quoted Skill
"""
    frontmatter, _ = parse_frontmatter(content)
    assert normalize_skill_description(frontmatter) == "A quoted one-line description."
