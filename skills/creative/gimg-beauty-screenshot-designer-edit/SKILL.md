---
name: gimg-beauty-screenshot-designer-edit
description: "Use when preparing GIMG beauty App Store screenshots for designer/manual editing. Produces a structured handoff package with editable metadata, safety boundaries, return rules, and readback validation instead of handing over bare images."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [gimg, app-store, screenshots, designer-handoff, metadata, manual-edit]
    related_skills: [app-store-icon, app-store-launch-image]
---

# GIMG Beauty Screenshot Designer Manual-Edit Handoff

## Overview

This skill turns `/gimg` beauty App Store screenshot outputs into a designer-ready handoff package. The goal is not to give a designer a ZIP of JPG/PNG files; it is to give them each screenshot plus the structure that produced it: app metadata, locale and size, sequence number, title copy, background theme, model/person crop, phone-frame and product-shot region, decorations, review-safety limits, and generation evidence.

Use it when an internal or external designer will manually improve beauty screenshots and return changes that InfraBrain or an agent can read back into future `/gimg` rules, training samples, or review checklists.

## When to Use

- A `/gimg` beauty screenshot pack needs human polish, localization, or visual differentiation.
- A designer needs to know which layers are editable and which are locked.
- A sample pack must be published without private assets while preserving a schema and workflow.
- You need a readback loop: designer edits → metadata diff → acceptance checklist → training/sample update.

Do **not** use this skill to publish sensitive source images, account data, advertising data, review notes, or private template libraries into a public repo. Public examples must be synthetic or redacted.

## Handoff Package Contract

Create a directory with this shape:

```text
gimg-beauty-designer-handoff/
  manifest.json
  metadata.json
  images/
    01-before.svg|png|jpg
    02-before.svg|png|jpg
    03-before.svg|png|jpg
  source_assets/          # optional; only sanitized assets
  designer-edit-brief.md
  README.md
```

### Required `manifest.json` Fields

| Field | Meaning | Designer editable? | Source |
| --- | --- | --- | --- |
| `package_id` | Stable package id, e.g. app + date + locale | No | Agent/handoff creator |
| `app.name` | App display name | Needs PM approval | App metadata |
| `app.category` | App Store category/use case | No | App metadata |
| `locale` | App Store locale/region | No unless assigned | `/gimg` request |
| `target_size` | Export pixel size per screenshot | No | App Store target |
| `screenshots[]` | Ordered screenshot records | Partly | `metadata.json` |
| `safety.review_boundaries` | Review/safety constraints | No | PM/review SOP |
| `return_contract` | How to name and return edits | No | This skill |

### Screenshot Record Schema

Each `screenshots[]` entry must include:

- `id`: stable id such as `s01`.
- `sequence`: 1-based App Store screenshot order.
- `image_path`: path under `images/`.
- `title_copy`: headline/subtitle visible in the screenshot.
- `background`: theme, palette, gradient, texture, depth, and safe edit notes.
- `person`: model/avatar/beauty subject description, crop box, face/pose consistency notes, and allowed retouch scope.
- `device_frame`: phone frame type, position, product screenshot region, and locked interaction area.
- `decorations`: stickers, badges, sparkles, shadows, panels, or other ornaments.
- `editable_layers`: list of layer ids the designer may change.
- `locked_layers`: list of layer ids that must not be changed without PM/agent approval.
- `review_safety`: forbidden changes and App Store safety notes.
- `generation_evidence`: source prompt id, generation run id, source screenshot hash, model id if safe, and redaction status.
- `designer_notes`: freeform instructions for this exact screenshot.
- `return_expected`: output file naming and required `designer_change_log` fields.

Use `templates/manifest.example.json` as a minimal public example and `templates/metadata.schema.json` as the validation contract.

## Designer Editing Workflow

1. **Package** — Copy screenshots into `images/`, fill `manifest.json`, and include `designer-edit-brief.md`.
2. **Lock boundaries** — Mark product screenshot regions, face identity/age/safety, app claims, review-sensitive copy, and export sizes as locked.
3. **Expose editable intent** — For every editable layer, explain what a good edit should achieve: more premium, less similar, clearer hierarchy, region-localized tone, safer review posture, etc.
4. **Manual edit** — Designer edits only the allowed layers, exports final files using the return contract, and records changes in `designer_change_log`.
5. **Readback** — Agent/InfraBrain validates file names, schema, dimensions, change log, and safety checklist, then computes metadata diffs.
6. **Training/sample update** — Accepted edits become structured examples for future `/gimg` generation rules; rejected edits are stored as negative examples with reason codes.

## Editable vs Locked Checklist

| Area | Editable by default | Locked by default | Notes |
| --- | --- | --- | --- |
| Title copy | Wording polish if meaning unchanged | Regulated claims, price, ranking claims | Keep locale and PM intent. |
| Background | Color, depth, texture, layout balance | Unsafe imagery, competitor marks | Must preserve text contrast. |
| Person/model | Light retouch, crop refinement, lighting | Age ambiguity, sexualized/unsafe changes, identity source | Beauty style should stay fresh/clean, not adult. |
| Phone frame | Shadow, placement, scale within safe bounds | Product screenshot content, fake UI claims | Do not invent app features. |
| Decorations | Density, hierarchy, localized ornaments | Review-risk badges or fake awards | Reduce similarity across screenshots. |
| Export | File format if accepted | Pixel dimensions, sequence naming | Validate before return. |

## Return Contract

Designers return a folder with:

```text
returned/
  images/
    s01-after.png
    s02-after.png
    s03-after.png
  designer_change_log.json
  notes.md
```

`designer_change_log.json` entries:

```json
{
  "screenshot_id": "s01",
  "changed_layers": ["background", "title_copy"],
  "summary": "Increased contrast and reduced duplicate sparkle density.",
  "kept_locked_layers": ["device_frame.product_region", "review_safety.claims"],
  "risk_notes": [],
  "export_path": "images/s01-after.png"
}
```

## Agent Readback / Smoke

Run the validator before sending a package or after receiving edits:

```bash
python3 skills/creative/gimg-beauty-screenshot-designer-edit/scripts/validate_handoff.py   skills/creative/gimg-beauty-screenshot-designer-edit/examples/redacted-beauty-handoff/manifest.json
```

The validator checks required fields, image paths, editable/locked boundaries, generation evidence, return contract, and basic safety flags. It intentionally does not read private template libraries.

## Common Pitfalls

1. **Bare image handoff.** A designer cannot learn from `01.png` alone. Always include manifest + screenshot records.
2. **Public leakage.** Public examples must be synthetic/redacted. Never publish private model images, real user data, internal prompts with secrets, account ids, or App Store review notes.
3. **Unclear locked layers.** If product UI, claims, or face safety are not explicitly locked, manual edits will drift into review risk.
4. **No return log.** Without `designer_change_log.json`, InfraBrain cannot turn a good manual edit into a reusable rule or training sample.
5. **Dimension drift.** Designers often export from design tools at the wrong size; validate dimensions and sequence naming before acceptance.
6. **Context stuffing.** Do not send designers private long agent prompts or template libraries. Send compact metadata, example images, and the brief.

## Verification Checklist

- [ ] Package has `manifest.json`, `metadata.json` or equivalent screenshot records, `images/`, and `designer-edit-brief.md`.
- [ ] 3-5 screenshots are bound to structured metadata records.
- [ ] Every screenshot record has editable and locked layers.
- [ ] Review safety boundaries forbid adult/unsafe beauty styling, fake claims, private data, and product UI invention.
- [ ] Return contract names files and requires a designer change log.
- [ ] `validate_handoff.py <manifest>` passes.
- [ ] Public repo examples are redacted/synthetic and safe to share.
