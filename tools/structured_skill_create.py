"""Structured contract for agent-driven skill creation.

This module owns the versioned request/result schemas for the structured skill
creation path. Later phases can build rendering, writes, and CLI wiring on top
of this contract without making callers parse free-form text.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from tools.skill_manager_tool import (
    ALLOWED_SUBDIRS,
    _atomic_write_text,
    _validate_category,
    _validate_file_path,
    _validate_frontmatter,
    _validate_name,
    _resolve_skill_target,
)


REQUEST_SCHEMA_VERSION = "hermes.skill_create_request.v1"
RESULT_SCHEMA_VERSION = "hermes.skill_create_result.v1"

RESULT_STATUS_VALUES = (
    "success",
    "validation_error",
    "write_error",
)

VALIDATION_ERROR_CODES = (
    "INVALID_SCHEMA_VERSION",
    "MISSING_REQUIRED_FIELD",
    "INVALID_FIELD_TYPE",
    "UNKNOWN_FIELD",
    "INVALID_ENUM_VALUE",
    "INVALID_SKILL_NAME",
    "INVALID_CATEGORY",
    "UNSAFE_FILE_PATH",
    "DUPLICATE_FILE_PATH",
    "FILE_PATH_CONFLICT",
    "DUPLICATE_SKILL",
    "INVALID_FRONTMATTER",
)

FRONTMATTER_FIELD_ORDER = (
    "name",
    "description",
    "version",
    "metadata",
)

SKILL_CREATE_REQUEST_SCHEMA_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": REQUEST_SCHEMA_VERSION,
    "title": "Hermes Structured Skill Create Request",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "name", "description", "instructions"],
    "properties": {
        "schema_version": {
            "type": "string",
            "const": REQUEST_SCHEMA_VERSION,
        },
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[a-z0-9][a-z0-9._-]*$",
        },
        "description": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "intent": {
            "type": "string",
        },
        "instructions": {
            "type": "string",
            "minLength": 1,
        },
        "category": {
            "type": "string",
            "pattern": "^[a-z0-9][a-z0-9._-]*$",
        },
        "metadata": {
            "type": "object",
            "additionalProperties": {
                "type": ["string", "number", "boolean", "null"],
            },
        },
        "support_files": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "content"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path under references/, templates/, scripts/, or assets/.",
                    },
                    "content": {
                        "type": "string",
                    },
                },
            },
        },
        "source_context": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "overwrite_policy": {
            "type": "string",
            "enum": ["reject_existing"],
        },
    },
    "x-validation-error-codes": list(VALIDATION_ERROR_CODES),
    "x-allowed-support-file-directories": sorted(ALLOWED_SUBDIRS),
}

SKILL_CREATE_RESULT_SCHEMA_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": RESULT_SCHEMA_VERSION,
    "title": "Hermes Structured Skill Create Result",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "status",
        "skill_name",
        "path",
        "files_written",
        "validation",
        "warnings",
        "next_actions",
    ],
    "properties": {
        "schema_version": {
            "type": "string",
            "const": RESULT_SCHEMA_VERSION,
        },
        "status": {
            "type": "string",
            "enum": list(RESULT_STATUS_VALUES),
        },
        "skill_name": {
            "type": ["string", "null"],
        },
        "path": {
            "type": ["string", "null"],
        },
        "files_written": {
            "type": "array",
            "items": {"type": "string"},
        },
        "validation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["valid", "errors"],
            "properties": {
                "valid": {"type": "boolean"},
                "errors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["code", "field", "message"],
                        "properties": {
                            "code": {
                                "type": "string",
                                "enum": list(VALIDATION_ERROR_CODES),
                            },
                            "field": {"type": "string"},
                            "message": {"type": "string"},
                        },
                    },
                },
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "next_actions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "x-validation-error-codes": list(VALIDATION_ERROR_CODES),
}


def request_schema_v1() -> dict[str, Any]:
    """Return a defensive copy of the v1 request schema."""
    return deepcopy(SKILL_CREATE_REQUEST_SCHEMA_V1)


def result_schema_v1() -> dict[str, Any]:
    """Return a defensive copy of the v1 result schema."""
    return deepcopy(SKILL_CREATE_RESULT_SCHEMA_V1)


def validate_skill_create_request(request: Any) -> dict[str, Any]:
    """Validate a structured skill create request.

    Returns a machine-readable validation object. This intentionally does not
    write files or render SKILL.md; it is the AC-001 input-contract slice.
    """
    errors: list[dict[str, str]] = []

    if not isinstance(request, dict):
        return {
            "valid": False,
            "errors": [
                {
                    "code": "INVALID_FIELD_TYPE",
                    "field": "$",
                    "message": "Request must be a JSON object.",
                }
            ],
        }

    allowed_fields = set(SKILL_CREATE_REQUEST_SCHEMA_V1["properties"])
    for field in sorted(set(request) - allowed_fields):
        errors.append(
            {
                "code": "UNKNOWN_FIELD",
                "field": field,
                "message": f"{field} is not supported by {REQUEST_SCHEMA_VERSION}.",
            }
        )

    schema_version = request.get("schema_version")
    if schema_version != REQUEST_SCHEMA_VERSION:
        errors.append(
            {
                "code": "INVALID_SCHEMA_VERSION",
                "field": "schema_version",
                "message": f"schema_version must be {REQUEST_SCHEMA_VERSION!r}.",
            }
        )

    for field in SKILL_CREATE_REQUEST_SCHEMA_V1["required"]:
        value = request.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(
                {
                    "code": "MISSING_REQUIRED_FIELD",
                    "field": field,
                    "message": f"{field} is required.",
                }
            )

    for field in ("name", "description", "intent", "instructions", "category", "overwrite_policy"):
        if field in request and request[field] is not None and not isinstance(request[field], str):
            errors.append(
                {
                    "code": "INVALID_FIELD_TYPE",
                    "field": field,
                    "message": f"{field} must be a string.",
                }
            )

    metadata = request.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            errors.append(
                {
                    "code": "INVALID_FIELD_TYPE",
                    "field": "metadata",
                    "message": "metadata must be an object.",
                }
            )
        else:
            for key, value in metadata.items():
                if not isinstance(key, str):
                    errors.append(
                        {
                            "code": "INVALID_FIELD_TYPE",
                            "field": "metadata",
                            "message": "metadata keys must be strings.",
                        }
                    )
                if not isinstance(value, (str, int, float, bool)) and value is not None:
                    errors.append(
                        {
                            "code": "INVALID_FIELD_TYPE",
                            "field": f"metadata.{key}",
                            "message": "metadata values must be strings, numbers, booleans, or null.",
                        }
                    )

    source_context = request.get("source_context")
    if source_context is not None:
        if not isinstance(source_context, list):
            errors.append(
                {
                    "code": "INVALID_FIELD_TYPE",
                    "field": "source_context",
                    "message": "source_context must be a list.",
                }
            )
        else:
            for index, item in enumerate(source_context):
                if not isinstance(item, str):
                    errors.append(
                        {
                            "code": "INVALID_FIELD_TYPE",
                            "field": f"source_context[{index}]",
                            "message": "source_context entries must be strings.",
                        }
                    )

    overwrite_policy = request.get("overwrite_policy")
    if overwrite_policy is not None and overwrite_policy != "reject_existing":
        errors.append(
            {
                "code": "INVALID_ENUM_VALUE",
                "field": "overwrite_policy",
                "message": "overwrite_policy must be 'reject_existing'.",
            }
        )

    name = request.get("name")
    if isinstance(name, str):
        name_error = _validate_name(name)
        if name_error:
            errors.append({"code": "INVALID_SKILL_NAME", "field": "name", "message": name_error})

    category = request.get("category")
    if isinstance(category, str):
        category_error = _validate_category(category)
        if category_error:
            errors.append({"code": "INVALID_CATEGORY", "field": "category", "message": category_error})

    support_files = request.get("support_files", [])
    if support_files is None:
        support_files = []
    if not isinstance(support_files, list):
        errors.append(
            {
                "code": "INVALID_FIELD_TYPE",
                "field": "support_files",
                "message": "support_files must be a list.",
            }
        )
    else:
        seen_paths: set[str] = set()
        seen_path_parts: dict[str, tuple[str, ...]] = {}
        for index, support_file in enumerate(support_files):
            if not isinstance(support_file, dict):
                errors.append(
                    {
                        "code": "INVALID_FIELD_TYPE",
                        "field": f"support_files[{index}]",
                        "message": "support_files entries must be objects.",
                    }
                )
                continue
            for field in sorted(set(support_file) - {"path", "content"}):
                errors.append(
                    {
                        "code": "UNKNOWN_FIELD",
                        "field": f"support_files[{index}].{field}",
                        "message": f"support_files entries do not support {field}.",
                    }
                )
            file_path = support_file.get("path")
            if not isinstance(file_path, str) or not file_path.strip():
                errors.append(
                    {
                        "code": "MISSING_REQUIRED_FIELD",
                        "field": f"support_files[{index}].path",
                        "message": "support file path is required.",
                    }
                )
            else:
                path_error = _validate_file_path(file_path)
                if path_error:
                    errors.append(
                        {
                            "code": "UNSAFE_FILE_PATH",
                            "field": f"support_files[{index}].path",
                            "message": path_error,
                        }
                    )
                elif file_path in seen_paths:
                    errors.append(
                        {
                            "code": "DUPLICATE_FILE_PATH",
                            "field": f"support_files[{index}].path",
                            "message": f"support file path {file_path!r} is duplicated.",
                        }
                    )
                else:
                    path_parts = PurePosixPath(file_path).parts
                    for existing_path, existing_parts in seen_path_parts.items():
                        if path_parts[: len(existing_parts)] == existing_parts:
                            errors.append(
                                {
                                    "code": "FILE_PATH_CONFLICT",
                                    "field": f"support_files[{index}].path",
                                    "message": (
                                        f"support file path {file_path!r} conflicts with "
                                        f"earlier file path {existing_path!r}."
                                    ),
                                }
                            )
                            break
                        if existing_parts[: len(path_parts)] == path_parts:
                            errors.append(
                                {
                                    "code": "FILE_PATH_CONFLICT",
                                    "field": f"support_files[{index}].path",
                                    "message": (
                                        f"support file path {file_path!r} conflicts with "
                                        f"earlier nested file path {existing_path!r}."
                                    ),
                                }
                            )
                            break
                    seen_paths.add(file_path)
                    seen_path_parts[file_path] = path_parts
            if not isinstance(support_file.get("content"), str):
                errors.append(
                    {
                        "code": "INVALID_FIELD_TYPE",
                        "field": f"support_files[{index}].content",
                        "message": "support file content must be a string.",
                    }
                )

    return {"valid": not errors, "errors": errors}


def _write_plan(
    skill_dir: Path,
    request: dict[str, Any],
    skill_md: str,
) -> tuple[list[tuple[Path, str, str]], str | None]:
    writes = [(skill_dir / "SKILL.md", "SKILL.md", skill_md)]
    for support_file in request.get("support_files") or []:
        target, error = _resolve_skill_target(skill_dir, support_file["path"])
        if error:
            return [], error
        writes.append((target, support_file["path"], support_file["content"]))
    return writes, None


def _normalized_category(request: dict[str, Any]) -> str | None:
    category = request.get("category")
    if isinstance(category, str) and category.strip():
        return category.strip()
    return None


def _skill_dir(skills_root: str | Path, request: dict[str, Any]) -> Path:
    root = Path(skills_root).expanduser()
    category = _normalized_category(request)
    if category:
        return root / category / request["name"]
    return root / request["name"]


def _skill_relative_path(request: dict[str, Any], file_path: str | None = None) -> str:
    category = _normalized_category(request)
    parts = [part for part in (category, request["name"], file_path) if part]
    return "/".join(parts)


def render_skill_md(request: dict[str, Any]) -> str:
    """Render a deterministic skill create request into SKILL.md content."""
    frontmatter: dict[str, Any] = {
        "name": request["name"].strip(),
        "description": request["description"].strip(),
        "version": "1.0.0",
    }
    metadata = request.get("metadata")
    if isinstance(metadata, dict) and metadata:
        frontmatter["metadata"] = {key: metadata[key] for key in sorted(metadata)}

    ordered_frontmatter = {
        key: frontmatter[key]
        for key in FRONTMATTER_FIELD_ORDER
        if key in frontmatter
    }
    yaml_text = yaml.safe_dump(
        ordered_frontmatter,
        allow_unicode=False,
        default_flow_style=False,
        sort_keys=False,
    ).strip()

    body_parts = [f"# {request['name'].strip()}", "", request["instructions"].strip()]
    intent = request.get("intent")
    if isinstance(intent, str) and intent.strip():
        body_parts.extend(["", "## Intent", "", intent.strip()])

    return "---\n" + yaml_text + "\n---\n\n" + "\n".join(body_parts).rstrip() + "\n"


def planned_skill_files(request: dict[str, Any]) -> list[str]:
    """Return the deterministic skill-relative file layout for a valid request."""
    files = [_skill_relative_path(request, "SKILL.md")]
    for support_file in request.get("support_files") or []:
        files.append(_skill_relative_path(request, support_file["path"]))
    return files


def structured_skill_create_result(
    request: Any,
    *,
    skills_root: str | Path | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """Return the v1 structured result envelope for a skill create request.

    This phase intentionally does not render or write files. It gives agent and
    CLI callers the stable output contract that later phases will fill with
    created file paths after deterministic rendering and staged writes land.
    """
    validation = validate_skill_create_request(request)
    skill_name = (
        request.get("name")
        if isinstance(request, dict) and isinstance(request.get("name"), str)
        else None
    )

    skill_path = None
    if validation["valid"] and skill_name and skills_root:
        skill_path = str(_skill_dir(skills_root, request))

    if validation["valid"]:
        skill_md = render_skill_md(request)
        frontmatter_error = _validate_frontmatter(skill_md)
        if frontmatter_error:
            validation = {
                "valid": False,
                "errors": [
                    {
                        "code": "INVALID_FRONTMATTER",
                        "field": "SKILL.md",
                        "message": frontmatter_error,
                    }
                ],
            }
            return {
                "schema_version": RESULT_SCHEMA_VERSION,
                "status": "validation_error",
                "skill_name": skill_name,
                "path": None,
                "files_written": [],
                "validation": validation,
                "warnings": [],
                "next_actions": [
                    "Correct the machine-readable validation errors and retry the structured skill create request."
                ],
            }

        files = planned_skill_files(request)
        warnings = []
        next_actions = []

        if write:
            if not skills_root:
                return {
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "status": "write_error",
                    "skill_name": skill_name,
                    "path": None,
                    "files_written": [],
                    "validation": validation,
                    "warnings": [],
                    "next_actions": ["Provide skills_root before requesting structured skill writes."],
                }
            skill_dir = _skill_dir(skills_root, request)
            if skill_dir.exists():
                return {
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "status": "validation_error",
                    "skill_name": skill_name,
                    "path": str(skill_dir),
                    "files_written": [],
                    "validation": {
                        "valid": False,
                        "errors": [
                            {
                                "code": "DUPLICATE_SKILL",
                                "field": "name",
                                "message": f"A skill named '{skill_name}' already exists at {skill_dir}.",
                            }
                        ],
                    },
                    "warnings": [],
                    "next_actions": [
                        "Choose a different skill name or remove the existing skill before retrying."
                    ],
                }
            writes, error = _write_plan(skill_dir, request, skill_md)
            if error:
                return {
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "status": "write_error",
                    "skill_name": skill_name,
                    "path": str(skill_dir),
                    "files_written": [],
                    "validation": validation,
                    "warnings": [],
                    "next_actions": [f"Resolve supporting file write error: {error}"],
                }
            for target, _relative_path, content in writes:
                _atomic_write_text(target, content)
        else:
            warnings = [
                "Structured request validated and deterministic layout planned; pass write=True with skills_root to write files."
            ]
            next_actions = [
                "Call structured_skill_create_result(..., write=True, skills_root=<isolated or target skills root>)."
            ]

        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "success",
            "skill_name": skill_name,
            "path": skill_path,
            "files_written": files if write else [],
            "validation": validation,
            "warnings": warnings,
            "next_actions": next_actions,
        }

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": "validation_error",
        "skill_name": skill_name,
        "path": None,
        "files_written": [],
        "validation": validation,
        "warnings": [],
        "next_actions": [
            "Correct the machine-readable validation errors and retry the structured skill create request."
        ],
    }
