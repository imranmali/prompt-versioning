from __future__ import annotations

import pytest

from promptlab.errors import InvalidTemplateError, MissingVariablesError
from promptlab.services.templating import extract_variables, render, validate_template


def test_extract_variables_sorted_unique() -> None:
    assert extract_variables("Hello {{ name }}, about {{ topic }} {{ name }}") == ["name", "topic"]


def test_extract_variables_ignores_loop_locals() -> None:
    template = "{% for item in items %}{{ item }}{% endfor %}{% set x = 1 %}{{ x }}"
    assert extract_variables(template) == ["items"]


def test_render() -> None:
    assert render("Hi {{ name }}!", {"name": "Ada"}) == "Hi Ada!"


def test_render_conditionals_and_filters() -> None:
    template = "{% if vip %}Dear {{ name | upper }}{% else %}Hi {{ name }}{% endif %}"
    assert render(template, {"vip": True, "name": "ada"}) == "Dear ADA"


def test_render_keeps_trailing_newline() -> None:
    assert render("line\n", {}) == "line\n"


def test_render_does_not_escape_html() -> None:
    assert render("{{ x }}", {"x": "<b>&</b>"}) == "<b>&</b>"


def test_missing_variables() -> None:
    with pytest.raises(MissingVariablesError) as exc_info:
        render("Hi {{ name }} from {{ city }} {{ zip }}", {"name": "Ada"})
    assert exc_info.value.details == {"missing": ["city", "zip"]}
    assert exc_info.value.code == "missing_variables"


def test_syntax_error() -> None:
    with pytest.raises(InvalidTemplateError) as exc_info:
        validate_template("Hello {{ name")
    assert exc_info.value.code == "invalid_template"
    assert exc_info.value.details["line"] == 1


def test_sandbox_blocks_unsafe_attributes() -> None:
    with pytest.raises(InvalidTemplateError):
        render("{{ name.__class__.__mro__ }}", {"name": "x"})


def test_undefined_nested_attribute() -> None:
    with pytest.raises(InvalidTemplateError):
        render("{{ user.missing }}", {"user": {}})


def test_runtime_error_in_template() -> None:
    with pytest.raises(InvalidTemplateError):
        render("{{ 1 / n }}", {"n": 0})
