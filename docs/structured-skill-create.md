# Structured Skill Creation

Hermes agents should use the structured skill creation path when saving a new
workflow as a skill. The structured path takes a small versioned request object,
validates names and file paths in code, renders a deterministic `SKILL.md`, and
returns a machine-readable result envelope.

Use this path instead of asking the model to write a complete `SKILL.md` when
the agent already knows the goal, instructions, and optional support files.

## Request Contract

The v1 request schema is exported by `tools.structured_skill_create`:

```python
from tools.structured_skill_create import (
    REQUEST_SCHEMA_VERSION,
    request_schema_v1,
)

schema = request_schema_v1()
assert REQUEST_SCHEMA_VERSION == "hermes.skill_create_request.v1"
```

Minimal request:

```json
{
  "schema_version": "hermes.skill_create_request.v1",
  "name": "release-checklist",
  "description": "Run the standard release verification checklist.",
  "instructions": "Inspect the release notes, run the focused tests, and record the verification commands."
}
```

Optional fields:

| Field | Use |
| --- | --- |
| `intent` | Extra context about when the skill should be used. |
| `category` | Single safe directory segment under the skills root. |
| `metadata` | Flat scalar metadata values for generated frontmatter. |
| `support_files` | Files under `references/`, `templates/`, `scripts/`, or `assets/`. |
| `source_context` | Source notes for the caller; entries must be strings. |
| `overwrite_policy` | Currently only `reject_existing`. |

Support files must stay inside allowed skill subdirectories:

```json
{
  "path": "references/checklist.md",
  "content": "# Release checklist\n\n- Run tests\n- Verify artifacts\n"
}
```

Do not put credentials, private user data, or platform identities into
`instructions`, `metadata`, or support files. If source material includes
sensitive values, write placeholders and return a blocker or warning in the
calling workflow.

## Agent Call Pattern

Agent code can validate, dry-run, or write through the shared library:

```python
from pathlib import Path

from tools.structured_skill_create import structured_skill_create_result

request = {
    "schema_version": "hermes.skill_create_request.v1",
    "name": "release-checklist",
    "description": "Run the standard release verification checklist.",
    "instructions": "Inspect release notes, run focused tests, and record evidence.",
    "support_files": [
        {
            "path": "references/checklist.md",
            "content": "# Checklist\n\n- Tests\n- Artifacts\n- Smoke\n",
        }
    ],
}

result = structured_skill_create_result(
    request,
    skills_root=Path("/tmp/hermes-skills-smoke"),
    write=True,
)
```

Callers should parse only the returned result fields, not natural-language
stdout or stderr.

## Result Contract

The v1 result schema is exported by `tools.structured_skill_create`:

```python
from tools.structured_skill_create import (
    RESULT_SCHEMA_VERSION,
    result_schema_v1,
)

schema = result_schema_v1()
assert RESULT_SCHEMA_VERSION == "hermes.skill_create_result.v1"
```

Success result shape:

```json
{
  "schema_version": "hermes.skill_create_result.v1",
  "status": "success",
  "skill_name": "release-checklist",
  "path": "/tmp/hermes-skills-smoke/release-checklist",
  "files_written": [
    "release-checklist/SKILL.md",
    "release-checklist/references/checklist.md"
  ],
  "validation": {
    "valid": true,
    "errors": []
  },
  "warnings": [],
  "next_actions": []
}
```

Validation error shape:

```json
{
  "schema_version": "hermes.skill_create_result.v1",
  "status": "validation_error",
  "skill_name": "bad skill",
  "path": null,
  "files_written": [],
  "validation": {
    "valid": false,
    "errors": [
      {
        "code": "INVALID_SKILL_NAME",
        "field": "name",
        "message": "Skill name must use lowercase letters, numbers, hyphens, underscores, or dots."
      }
    ]
  },
  "warnings": [],
  "next_actions": [
    "Correct the machine-readable validation errors and retry the structured skill create request."
  ]
}
```

Known result statuses are `success`, `validation_error`, and `write_error`.
Known validation error codes are exposed in the request/result schemas under
`x-validation-error-codes`.

## Isolated Smoke

For tests, black-box acceptance, or active-runtime verification, write to a
temporary skills root first:

```python
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmp:
    result = structured_skill_create_result(
        request,
        skills_root=Path(tmp),
        write=True,
    )
    assert result["status"] == "success"
    assert result["files_written"]
```

Only write to the production Hermes skills root after validation and review.
The structured path is designed so failed validation returns
`files_written: []`, which lets agents reject unsafe names, path traversal,
malformed support files, and duplicate skills without polluting the target root.
