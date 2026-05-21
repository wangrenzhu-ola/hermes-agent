# Redacted Beauty Handoff Example

This directory is a public-safe, synthetic example for `gimg-beauty-screenshot-designer-edit`.

It demonstrates the package shape expected by the skill:

- `manifest.json` binds 3 screenshots to structure metadata.
- `images/*.svg` are synthetic placeholder screenshots, not real user/model/product assets.
- `designer-edit-brief.md` tells a designer what to change and what to keep locked.

Validate it from the repository root:

```bash
python3 skills/creative/gimg-beauty-screenshot-designer-edit/scripts/validate_handoff.py   skills/creative/gimg-beauty-screenshot-designer-edit/examples/redacted-beauty-handoff/manifest.json
```
