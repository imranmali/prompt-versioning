"""Sandboxed Jinja2 prompt templates with strict variable handling."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from jinja2 import StrictUndefined, Template, TemplateSyntaxError, UndefinedError, meta
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment

from promptlab.errors import InvalidTemplateError, MissingVariablesError

_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


def _syntax_error(exc: TemplateSyntaxError) -> InvalidTemplateError:
    return InvalidTemplateError(
        f"Invalid template: {exc.message}", details={"line": exc.lineno, "error": exc.message}
    )


@lru_cache(maxsize=1024)
def _parse_variables(template: str) -> tuple[str, ...]:
    try:
        ast = _env.parse(template)
    except TemplateSyntaxError as exc:
        raise _syntax_error(exc) from exc
    return tuple(sorted(meta.find_undeclared_variables(ast)))


@lru_cache(maxsize=1024)
def _compile(template: str) -> Template:
    try:
        return _env.from_string(template)
    except TemplateSyntaxError as exc:
        raise _syntax_error(exc) from exc


def extract_variables(template: str) -> list[str]:
    """Return the sorted names of variables the template expects from the caller.

    Raises ``InvalidTemplateError`` when the template does not parse.
    """
    return list(_parse_variables(template))


def validate_template(template: str) -> list[str]:
    """Validate syntax and return the template's variables."""
    variables = extract_variables(template)
    _compile(template)
    return variables


def render(template: str, variables: Mapping[str, Any]) -> str:
    """Render ``template`` with ``variables`` in the sandbox.

    Raises ``MissingVariablesError`` (details ``{"missing": [...]}``) when variables are absent and
    ``InvalidTemplateError`` on syntax errors or sandbox violations.
    """
    missing = [name for name in extract_variables(template) if name not in variables]
    if missing:
        raise MissingVariablesError(
            f"Missing template variables: {', '.join(missing)}", details={"missing": missing}
        )
    compiled = _compile(template)
    try:
        return compiled.render(**variables)
    except SecurityError as exc:
        raise InvalidTemplateError(f"Unsafe template operation: {exc}") from exc
    except UndefinedError as exc:
        raise InvalidTemplateError(f"Template rendering failed: {exc.message}") from exc
    except (TypeError, ValueError, ArithmeticError, LookupError) as exc:
        raise InvalidTemplateError(f"Template rendering failed: {exc}") from exc
