"""Tests for the structured skill creation request contract."""

import json

from tools.structured_skill_create import (
    REQUEST_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    RESULT_STATUS_VALUES,
    SKILL_CREATE_REQUEST_SCHEMA_V1,
    SKILL_CREATE_RESULT_SCHEMA_V1,
    VALIDATION_ERROR_CODES,
    planned_skill_files,
    request_schema_v1,
    render_skill_md,
    result_schema_v1,
    structured_skill_create_result,
    validate_skill_create_request,
)


def _valid_request(**overrides):
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "name": "structured-skill",
        "description": "Creates a deterministic skill from structured input.",
        "instructions": "Use the provided steps to complete the task.",
    }
    request.update(overrides)
    return request


class TestRequestSchemaV1:
    def test_schema_version_and_required_fields_are_inspectable(self):
        schema = SKILL_CREATE_REQUEST_SCHEMA_V1

        assert REQUEST_SCHEMA_VERSION == "hermes.skill_create_request.v1"
        assert schema["$id"] == REQUEST_SCHEMA_VERSION
        assert schema["properties"]["schema_version"]["const"] == REQUEST_SCHEMA_VERSION
        assert schema["required"] == ["schema_version", "name", "description", "instructions"]

    def test_schema_exposes_stable_error_codes_and_support_file_dirs(self):
        schema = request_schema_v1()

        assert schema["x-validation-error-codes"] == list(VALIDATION_ERROR_CODES)
        assert schema["x-allowed-support-file-directories"] == [
            "assets",
            "references",
            "scripts",
            "templates",
        ]

    def test_request_schema_copy_is_defensive(self):
        schema = request_schema_v1()
        schema["required"].append("mutated")

        assert "mutated" not in SKILL_CREATE_REQUEST_SCHEMA_V1["required"]


class TestResultSchemaV1:
    def test_result_schema_version_required_fields_and_statuses_are_inspectable(self):
        schema = SKILL_CREATE_RESULT_SCHEMA_V1

        assert RESULT_SCHEMA_VERSION == "hermes.skill_create_result.v1"
        assert schema["$id"] == RESULT_SCHEMA_VERSION
        assert schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
        assert schema["required"] == [
            "schema_version",
            "status",
            "skill_name",
            "path",
            "files_written",
            "validation",
            "warnings",
            "next_actions",
        ]
        assert schema["properties"]["status"]["enum"] == list(RESULT_STATUS_VALUES)
        assert schema["properties"]["validation"]["properties"]["errors"]["items"]["properties"]["code"][
            "enum"
        ] == list(VALIDATION_ERROR_CODES)

    def test_result_schema_copy_is_defensive(self):
        schema = result_schema_v1()
        schema["required"].append("mutated")

        assert "mutated" not in SKILL_CREATE_RESULT_SCHEMA_V1["required"]


class TestValidateSkillCreateRequest:
    def test_valid_minimal_request(self):
        validation = validate_skill_create_request(_valid_request())

        assert validation == {"valid": True, "errors": []}

    def test_valid_request_with_support_files(self):
        validation = validate_skill_create_request(
            _valid_request(
                support_files=[
                    {"path": "references/guide.md", "content": "# Guide"},
                    {"path": "templates/template.md", "content": "Hello"},
                    {"path": "scripts/helper.py", "content": "print('ok')"},
                    {"path": "assets/sample.txt", "content": "sample"},
                ]
            )
        )

        assert validation == {"valid": True, "errors": []}

    def test_unknown_schema_version_returns_machine_readable_error(self):
        validation = validate_skill_create_request(_valid_request(schema_version="v0"))

        assert validation["valid"] is False
        assert validation["errors"][0]["code"] == "INVALID_SCHEMA_VERSION"
        assert validation["errors"][0]["field"] == "schema_version"

    def test_missing_required_field_returns_field_level_error(self):
        request = _valid_request()
        del request["instructions"]

        validation = validate_skill_create_request(request)

        assert validation["valid"] is False
        assert {
            "code": "MISSING_REQUIRED_FIELD",
            "field": "instructions",
            "message": "instructions is required.",
        } in validation["errors"]

    def test_invalid_skill_name_uses_stable_error_code(self):
        validation = validate_skill_create_request(_valid_request(name="Invalid Name"))

        assert validation["valid"] is False
        assert validation["errors"][0]["code"] == "INVALID_SKILL_NAME"
        assert validation["errors"][0]["field"] == "name"

    def test_category_must_be_single_safe_segment(self):
        validation = validate_skill_create_request(_valid_request(category="../escape"))

        assert validation["valid"] is False
        assert validation["errors"][0]["code"] == "INVALID_CATEGORY"
        assert validation["errors"][0]["field"] == "category"

    def test_unsafe_support_file_path_is_rejected(self):
        validation = validate_skill_create_request(
            _valid_request(support_files=[{"path": "../escape.txt", "content": "no"}])
        )

        assert validation["valid"] is False
        assert validation["errors"][0]["code"] == "UNSAFE_FILE_PATH"
        assert validation["errors"][0]["field"] == "support_files[0].path"

    def test_non_object_request_is_rejected(self):
        validation = validate_skill_create_request(["not", "an", "object"])

        assert validation == {
            "valid": False,
            "errors": [
                {
                    "code": "INVALID_FIELD_TYPE",
                    "field": "$",
                    "message": "Request must be a JSON object.",
                }
            ],
        }

    def test_unknown_top_level_field_returns_machine_readable_error(self):
        validation = validate_skill_create_request(_valid_request(extra=True))

        assert validation["valid"] is False
        assert {
            "code": "UNKNOWN_FIELD",
            "field": "extra",
            "message": f"extra is not supported by {REQUEST_SCHEMA_VERSION}.",
        } in validation["errors"]

    def test_malformed_metadata_and_source_context_are_rejected(self):
        validation = validate_skill_create_request(
            _valid_request(
                metadata={"nested": {"not": "allowed"}},
                source_context=["ok", 123],
            )
        )

        assert validation["valid"] is False
        assert {
            "code": "INVALID_FIELD_TYPE",
            "field": "metadata.nested",
            "message": "metadata values must be strings, numbers, booleans, or null.",
        } in validation["errors"]
        assert {
            "code": "INVALID_FIELD_TYPE",
            "field": "source_context[1]",
            "message": "source_context entries must be strings.",
        } in validation["errors"]

    def test_invalid_overwrite_policy_returns_enum_error(self):
        validation = validate_skill_create_request(_valid_request(overwrite_policy="replace"))

        assert validation["valid"] is False
        assert {
            "code": "INVALID_ENUM_VALUE",
            "field": "overwrite_policy",
            "message": "overwrite_policy must be 'reject_existing'.",
        } in validation["errors"]

    def test_duplicate_support_file_path_is_rejected(self):
        validation = validate_skill_create_request(
            _valid_request(
                support_files=[
                    {"path": "references/guide.md", "content": "one"},
                    {"path": "references/guide.md", "content": "two"},
                ]
            )
        )

        assert validation["valid"] is False
        assert {
            "code": "DUPLICATE_FILE_PATH",
            "field": "support_files[1].path",
            "message": "support file path 'references/guide.md' is duplicated.",
        } in validation["errors"]

    def test_support_file_unknown_field_is_rejected(self):
        validation = validate_skill_create_request(
            _valid_request(
                support_files=[
                    {"path": "references/guide.md", "content": "ok", "mode": "extra"}
                ]
            )
        )

        assert validation["valid"] is False
        assert {
            "code": "UNKNOWN_FIELD",
            "field": "support_files[0].mode",
            "message": "support_files entries do not support mode.",
        } in validation["errors"]

    def test_non_string_scalar_fields_return_field_level_errors(self):
        validation = validate_skill_create_request(
            _valid_request(
                name=123,
                description=["not", "text"],
                instructions=False,
                support_files="references/guide.md",
            )
        )

        assert validation["valid"] is False
        assert {
            "code": "INVALID_FIELD_TYPE",
            "field": "name",
            "message": "name must be a string.",
        } in validation["errors"]
        assert {
            "code": "INVALID_FIELD_TYPE",
            "field": "description",
            "message": "description must be a string.",
        } in validation["errors"]
        assert {
            "code": "INVALID_FIELD_TYPE",
            "field": "instructions",
            "message": "instructions must be a string.",
        } in validation["errors"]
        assert {
            "code": "INVALID_FIELD_TYPE",
            "field": "support_files",
            "message": "support_files must be a list.",
        } in validation["errors"]

    def test_support_file_missing_content_is_rejected(self):
        validation = validate_skill_create_request(
            _valid_request(support_files=[{"path": "references/guide.md"}])
        )

        assert validation["valid"] is False
        assert {
            "code": "INVALID_FIELD_TYPE",
            "field": "support_files[0].content",
            "message": "support file content must be a string.",
        } in validation["errors"]


class TestStructuredSkillCreateResult:
    def test_valid_request_returns_versioned_result_envelope(self):
        result = structured_skill_create_result(_valid_request(), skills_root="/tmp/hermes-skills")

        assert result["schema_version"] == RESULT_SCHEMA_VERSION
        assert result["status"] == "success"
        assert result["skill_name"] == "structured-skill"
        assert result["path"] == "/tmp/hermes-skills/structured-skill"
        assert result["files_written"] == []
        assert result["validation"] == {"valid": True, "errors": []}
        assert result["warnings"] == [
            "Structured request validated and deterministic layout planned; pass write=True with skills_root to write files."
        ]
        assert result["next_actions"] == [
            "Call structured_skill_create_result(..., write=True, skills_root=<isolated or target skills root>)."
        ]

    def test_valid_category_request_returns_nested_result_path(self):
        result = structured_skill_create_result(
            _valid_request(category="writing"),
            skills_root="/tmp/hermes-skills/",
        )

        assert result["path"] == "/tmp/hermes-skills/writing/structured-skill"

    def test_invalid_request_returns_versioned_validation_error_envelope(self):
        result = structured_skill_create_result(_valid_request(schema_version="v0"))

        assert result["schema_version"] == RESULT_SCHEMA_VERSION
        assert result["status"] == "validation_error"
        assert result["skill_name"] == "structured-skill"
        assert result["path"] is None
        assert result["files_written"] == []
        assert result["validation"]["valid"] is False
        assert result["validation"]["errors"][0]["code"] == "INVALID_SCHEMA_VERSION"
        assert result["warnings"] == []
        assert result["next_actions"] == [
            "Correct the machine-readable validation errors and retry the structured skill create request."
        ]

    def test_write_true_without_skills_root_returns_write_error_envelope(self):
        result = structured_skill_create_result(_valid_request(), write=True)

        assert result == {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "write_error",
            "skill_name": "structured-skill",
            "path": None,
            "files_written": [],
            "validation": {"valid": True, "errors": []},
            "warnings": [],
            "next_actions": ["Provide skills_root before requesting structured skill writes."],
        }


class TestDeterministicSkillCreateFlow:
    def test_render_skill_md_has_stable_frontmatter_and_body(self):
        skill_md = render_skill_md(
            _valid_request(
                metadata={"zeta": True, "alpha": "first"},
                intent="Use for structured skill creation.",
            )
        )

        assert skill_md == """---
name: structured-skill
description: Creates a deterministic skill from structured input.
version: 1.0.0
metadata:
  alpha: first
  zeta: true
---

# structured-skill

Use the provided steps to complete the task.

## Intent

Use for structured skill creation.
"""

    def test_planned_skill_files_are_deterministic(self):
        files = planned_skill_files(
            _valid_request(
                category="coding",
                support_files=[
                    {"path": "references/guide.md", "content": "# Guide"},
                    {"path": "scripts/helper.py", "content": "print('ok')"},
                ],
            )
        )

        assert files == [
            "coding/structured-skill/SKILL.md",
            "coding/structured-skill/references/guide.md",
            "coding/structured-skill/scripts/helper.py",
        ]

    def test_write_true_creates_valid_skill_md_and_support_files(self, tmp_path):
        result = structured_skill_create_result(
            _valid_request(
                category="coding",
                support_files=[
                    {"path": "references/guide.md", "content": "# Guide\n"},
                    {"path": "templates/template.md", "content": "Hello\n"},
                ],
            ),
            skills_root=tmp_path,
            write=True,
        )

        skill_dir = tmp_path / "coding" / "structured-skill"
        assert result["status"] == "success"
        assert result["path"] == str(skill_dir)
        assert result["files_written"] == [
            "coding/structured-skill/SKILL.md",
            "coding/structured-skill/references/guide.md",
            "coding/structured-skill/templates/template.md",
        ]
        assert result["warnings"] == []
        assert result["next_actions"] == []
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8").startswith(
            "---\nname: structured-skill\n"
        )
        assert (skill_dir / "references" / "guide.md").read_text(encoding="utf-8") == "# Guide\n"
        assert (skill_dir / "templates" / "template.md").read_text(encoding="utf-8") == "Hello\n"

    def test_written_skill_can_be_loaded_by_skill_view(self, tmp_path, monkeypatch):
        from tools import skills_tool

        structured_skill_create_result(
            _valid_request(
                category="coding",
                support_files=[{"path": "references/guide.md", "content": "# Guide\n"}],
            ),
            skills_root=tmp_path,
            write=True,
        )
        monkeypatch.setattr(skills_tool, "SKILLS_DIR", tmp_path)

        viewed = json.loads(skills_tool.skill_view("coding/structured-skill", preprocess=False))

        assert viewed["success"] is True
        assert viewed["name"] == "structured-skill"
        assert viewed["description"] == "Creates a deterministic skill from structured input."
        assert viewed["linked_files"]["references"] == ["references/guide.md"]

    def test_write_true_rejects_existing_skill_without_overwrite(self, tmp_path):
        request = _valid_request()

        first = structured_skill_create_result(request, skills_root=tmp_path, write=True)
        second = structured_skill_create_result(request, skills_root=tmp_path, write=True)

        assert first["status"] == "success"
        assert second["status"] == "validation_error"
        assert second["validation"]["errors"] == [
            {
                "code": "DUPLICATE_SKILL",
                "field": "name",
                "message": f"A skill named 'structured-skill' already exists at {tmp_path / 'structured-skill'}.",
            }
        ]

    def test_write_true_rejects_mixed_unsafe_paths_without_partial_skill_dir(self, tmp_path):
        request = _valid_request(
            support_files=[
                {"path": "references/guide.md", "content": "# Guide\n"},
                {"path": "references/../escape.md", "content": "bad\n"},
            ]
        )

        result = structured_skill_create_result(request, skills_root=tmp_path, write=True)

        assert result["status"] == "validation_error"
        assert result["files_written"] == []
        assert result["validation"]["errors"] == [
            {
                "code": "UNSAFE_FILE_PATH",
                "field": "support_files[1].path",
                "message": "Path traversal ('..') is not allowed.",
            }
        ]
        assert not (tmp_path / "structured-skill").exists()
