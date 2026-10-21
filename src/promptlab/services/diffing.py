"""Comparison of two prompt versions."""

from __future__ import annotations

import difflib
from typing import Any

from promptlab.models import PromptVersion
from promptlab.schemas.prompts import DiffOut, ModelSettingsDiff, VariablesDiff


def template_diff(old: PromptVersion, new: PromptVersion) -> str:
    """Return a unified diff of the two templates (empty when they are identical)."""
    lines = difflib.unified_diff(
        old.template.splitlines(),
        new.template.splitlines(),
        fromfile=f"v{old.version}",
        tofile=f"v{new.version}",
        lineterm="",
    )
    return "\n".join(lines)


def settings_diff(old: dict[str, Any], new: dict[str, Any]) -> ModelSettingsDiff:
    return ModelSettingsDiff(
        added={k: v for k, v in new.items() if k not in old},
        removed={k: v for k, v in old.items() if k not in new},
        changed={k: {"from": old[k], "to": v} for k, v in new.items() if k in old and old[k] != v},
    )


def diff_versions(prompt_name: str, old: PromptVersion, new: PromptVersion) -> DiffOut:
    old_vars, new_vars = set(old.variables), set(new.variables)
    return DiffOut(
        prompt=prompt_name,
        from_version=old.version,
        to_version=new.version,
        template_diff=template_diff(old, new),
        variables=VariablesDiff(
            added=sorted(new_vars - old_vars), removed=sorted(old_vars - new_vars)
        ),
        model_settings=settings_diff(old.model_settings, new.model_settings),
    )
