from __future__ import annotations

import pytest

from pi_ai import Tool
from pi_ai.constrained_sampling import (
    GrammarToolInputJsonBuffer,
    append_grammar_tool_input_json_delta,
    create_grammar_tool_input_properties,
    resolve_grammar_constrained_sampling,
    resolve_json_schema_strict_sampling,
)


def test_tool_accepts_camel_case_constrained_sampling():
    tool = Tool.model_validate(
        {
            "name": "answer",
            "description": "Return an answer",
            "parameters": {"type": "object", "properties": {}, "required": []},
            "constrainedSampling": {"type": "json_schema", "strict": "prefer"},
        }
    )

    assert tool.constrained_sampling is not None
    assert tool.model_dump(by_alias=True)["constrainedSampling"]["strict"] == "prefer"


def test_preferred_strict_sampling_falls_back_when_unsupported():
    tool = Tool(
        name="answer",
        description="Return an answer",
        parameters={"type": "object", "properties": {}, "required": []},
        constrained_sampling={"type": "json_schema", "strict": "prefer"},
    )

    assert resolve_json_schema_strict_sampling(tool, supports_strict_mode=False) is None


def test_grammar_requires_exactly_one_required_string_property():
    tool = Tool(
        name="bad",
        description="Bad grammar tool",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a", "b"],
        },
        constrained_sampling={
            "type": "grammar",
            "variants": {"openai_regex": ".+"},
        },
    )

    with pytest.raises(ValueError, match="exactly one required string property"):
        resolve_grammar_constrained_sampling(tool, supports_openai_grammar_tools=True)


def test_create_grammar_tool_input_properties_ignores_unsupported_provider():
    tool = Tool(
        name="sql",
        description="Generate SQL",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        constrained_sampling={
            "type": "grammar",
            "variants": {"openai_regex": "SELECT .*"},
        },
    )

    assert create_grammar_tool_input_properties([tool], False) == {}


def test_grammar_tool_input_delta_forms_valid_incremental_json():
    buffer = GrammarToolInputJsonBuffer()

    first = append_grammar_tool_input_json_delta(buffer, "query", 'SELECT "a', close=False)
    second = append_grammar_tool_input_json_delta(buffer, "query", 'SELECT "a"', close=True)

    assert first == '{"query":"SELECT \\"a'
    assert second == '\\""}'


# ============================================================
# v0.85.1: strict JSON Schema 转换
# ============================================================


def _strict_tool(parameters, strict="prefer"):
    return Tool(
        name="t",
        description="test",
        parameters=parameters,
        constrained_sampling={"type": "json_schema", "strict": strict},
    )


def test_make_strict_json_schema_marks_all_properties_required():
    """可选属性包成 anyOf+null，required 收拢为全部属性，additionalProperties 关闭。"""
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "integer"},
        },
        "required": ["a"],
    }

    from pi_ai.constrained_sampling import make_strict_json_schema

    result = make_strict_json_schema(schema)

    assert result["required"] == ["a", "b"]
    assert result["additionalProperties"] is False
    assert result["properties"]["a"] == {"type": "string"}
    assert result["properties"]["b"] == {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    # 原 schema 不被修改
    assert schema["required"] == ["a"]


def test_make_strict_json_schema_allows_null_optional_property():
    """已允许 null 的可选属性不重复包裹。"""
    from pi_ai.constrained_sampling import make_strict_json_schema

    result = make_strict_json_schema(
        {
            "type": "object",
            "properties": {"a": {"type": ["string", "null"]}},
        }
    )

    assert result["properties"]["a"] == {"type": ["string", "null"]}


def test_make_strict_json_schema_rejects_unsupported_constructs():
    from pi_ai.constrained_sampling import (
        UnsupportedStrictJsonSchemaError,
        make_strict_json_schema,
    )

    for bad in (
        {"type": "object", "$ref": "#/x"},  # $ref
        {"type": "object", "oneOf": []},  # oneOf
        {"type": "object", "properties": {"a": {"allOf": []}}},  # 嵌套 allOf
        {"type": "array", "items": [{"type": "string"}]},  # 元组 items
        {"type": "object", "properties": None},  # properties 非映射
        {"type": "string"},  # 根非 object
    ):
        with pytest.raises(UnsupportedStrictJsonSchemaError):
            make_strict_json_schema(bad)


def test_make_strict_json_schema_rejects_object_anyof_variant():
    """anyOf 变体里不允许对象/数组型 schema。"""
    from pi_ai.constrained_sampling import (
        UnsupportedStrictJsonSchemaError,
        make_strict_json_schema,
    )

    with pytest.raises(UnsupportedStrictJsonSchemaError):
        make_strict_json_schema(
            {
                "type": "object",
                "properties": {
                    "a": {"anyOf": [{"type": "object", "properties": {}}, {"type": "string"}]},
                },
            }
        )


def test_strict_sampling_falls_back_when_schema_not_strictable():
    """strict=prefer 且 schema 无法 strict 化：回退为普通工具（返回 None）。"""
    tool = _strict_tool({"type": "object", "properties": {"a": {"$ref": "#/x"}}})

    assert resolve_json_schema_strict_sampling(tool, True) is None


def test_strict_sampling_require_errors_when_schema_not_strictable():
    """strict=require 且 schema 无法 strict 化：报错。"""
    tool = _strict_tool({"type": "object", "properties": {"a": {"oneOf": []}}}, strict="require")

    with pytest.raises(ValueError, match="requires JSON-schema constrained sampling"):
        resolve_json_schema_strict_sampling(tool, True)


def test_strict_sampling_supported_schema_still_strict():
    tool = _strict_tool(
        {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    )

    assert resolve_json_schema_strict_sampling(tool, True) is True
