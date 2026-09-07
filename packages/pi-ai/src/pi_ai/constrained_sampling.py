"""Provider-side constrained tool sampling.

Port of upstream ``api/constrained-sampling.ts`` introduced in pi 0.82.0.
v0.85.1 新增 strict JSON Schema 转换（``make_strict_json_schema``）。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from .types import Tool


class UnsupportedStrictJsonSchemaError(ValueError):
    """schema 不满足 provider constrained sampling 要求的 strict 子集。"""


#: strict 转换不支持的 schema 键。对应上游 ``UNSUPPORTED_STRICT_SCHEMA_KEYS``。
_UNSUPPORTED_STRICT_SCHEMA_KEYS = (
    "$ref",
    "$defs",
    "definitions",
    "allOf",
    "oneOf",
    "patternProperties",
    "dependentSchemas",
    "dependencies",
    "unevaluatedProperties",
    "propertyNames",
    "contains",
    "prefixItems",
    "not",
    "if",
    "then",
    "else",
)


def _is_schema_object(value: Any) -> bool:
    return isinstance(value, dict)


def _is_structured_schema(schema: Any) -> bool:
    """对象/数组型 schema（不能出现在 anyOf 变体里）。"""
    if not _is_schema_object(schema):
        return False
    types = schema.get("type")
    types = [types] if isinstance(types, str) else types if isinstance(types, list) else []
    return (
        "object" in types
        or "array" in types
        or schema.get("properties") is not None
        or schema.get("items") is not None
    )


def _schema_allows_null(schema: Any) -> bool:
    if not _is_schema_object(schema):
        return False
    types = schema.get("type")
    if types == "null" or (isinstance(types, list) and "null" in types):
        return True
    if schema.get("const") is None and "const" in schema:
        return True
    enum = schema.get("enum")
    if isinstance(enum, list) and None in enum:
        return True
    any_of = schema.get("anyOf")
    return isinstance(any_of, list) and any(_schema_allows_null(v) for v in any_of)


def _make_json_schema_node_strict(schema: Any) -> None:
    """原地递归收紧一个 schema 节点为 strict 子集。

    - 可选属性包成 ``anyOf: [原schema, {"type": "null"}]``，required 收拢为全部属性，
      ``additionalProperties: false``。
    - 不支持的键（``$ref``/``allOf``/元组 ``items`` 等）抛
      ``UnsupportedStrictJsonSchemaError``。
    """
    if not _is_schema_object(schema):
        raise UnsupportedStrictJsonSchemaError("boolean schemas are unsupported")
    for key in _UNSUPPORTED_STRICT_SCHEMA_KEYS:
        if schema.get(key) is not None:
            raise UnsupportedStrictJsonSchemaError(f"{key} schemas are unsupported")

    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list) or len(any_of) == 0:
            raise UnsupportedStrictJsonSchemaError("anyOf must contain at least one schema")
        for variant in any_of:
            if _is_structured_schema(variant):
                raise UnsupportedStrictJsonSchemaError("object and array unions are unsupported")
            _make_json_schema_node_strict(variant)

    items = schema.get("items")
    if items is not None:
        if isinstance(items, list):
            raise UnsupportedStrictJsonSchemaError("tuple schemas are unsupported")
        _make_json_schema_node_strict(items)

    is_object_schema = schema.get("type") == "object"
    if "properties" in schema and schema.get("properties") is not None and not is_object_schema:
        raise UnsupportedStrictJsonSchemaError("properties require type object")
    if not is_object_schema:
        return
    additional = schema.get("additionalProperties")
    if additional is not None and additional is not False:
        raise UnsupportedStrictJsonSchemaError(
            "schema-valued or true additionalProperties is unsupported"
        )
    if "properties" in schema and not _is_schema_object(schema.get("properties")):
        raise UnsupportedStrictJsonSchemaError("object properties must be a schema map")
    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list) or not all(isinstance(k, str) for k in required)
    ):
        raise UnsupportedStrictJsonSchemaError("object required must be a string array")

    properties = schema.get("properties")
    properties = properties if properties is not None else {}
    property_names = list(properties.keys())
    required_set = set(required) if isinstance(required, list) else set()
    if not required_set <= set(property_names):
        raise UnsupportedStrictJsonSchemaError("required contains an unknown property")
    for key, prop in properties.items():
        _make_json_schema_node_strict(prop)
        if key not in required_set and not _schema_allows_null(prop):
            properties[key] = {"anyOf": [prop, {"type": "null"}]}
    schema["required"] = property_names
    schema["additionalProperties"] = False


def make_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """把工具 schema 转换为 provider constrained sampling 要求的 strict 子集。"""
    cloned = copy.deepcopy(schema)
    if not _is_schema_object(cloned):
        raise UnsupportedStrictJsonSchemaError("root schema must have type object")
    _make_json_schema_node_strict(cloned)
    if cloned.get("type") != "object":
        raise UnsupportedStrictJsonSchemaError("root schema must have type object")
    return cloned


def get_json_schema_tool_parameters(tool: Tool, strict: bool | None) -> dict[str, Any]:
    """strict 为真时返回 strict 化的参数 schema，否则原样返回。"""
    parameters = tool.to_json_schema() if hasattr(tool, "to_json_schema") else tool.parameters
    if strict is True:
        return make_strict_json_schema(parameters)
    return parameters


@dataclass(frozen=True)
class GrammarConstrainedSampling:
    format: str
    definition: str
    input_property: str


@dataclass
class GrammarToolInputJsonBuffer:
    input: str = ""
    started: bool = False
    closed: bool = False


def append_grammar_tool_input_json_delta(
    buffer: GrammarToolInputJsonBuffer,
    input_property: str,
    next_input: str,
    *,
    close: bool,
) -> str | None:
    if buffer.closed:
        if close and next_input == buffer.input:
            return None
        raise ValueError(
            f'grammar tool input for property "{input_property}" changed after it was closed'
        )
    if not next_input.startswith(buffer.input):
        raise ValueError(
            f'grammar tool input for property "{input_property}" changed non-monotonically'
        )
    input_delta = next_input[len(buffer.input) :]
    if not close and not input_delta:
        return None
    delta = ""
    if not buffer.started:
        delta += f"{json.dumps(input_property)}:"
        delta = "{" + delta + '"'
        buffer.started = True
    delta += json.dumps(input_delta)[1:-1]
    buffer.input = next_input
    if close:
        delta += '"}'
        buffer.closed = True
    return delta


def _infer_grammar_input_property(tool: Tool) -> str:
    schema = tool.parameters
    if schema.get("type") != "object":
        raise ValueError("grammar constrained sampling requires an object parameter schema")
    required = schema.get("required")
    if not isinstance(required, list) or len(required) != 1 or not isinstance(required[0], str):
        raise ValueError(
            "grammar constrained sampling requires exactly one required string property"
        )
    input_property = required[0]
    properties = schema.get("properties")
    if not isinstance(properties, dict) or input_property not in properties:
        raise ValueError(
            f"grammar constrained sampling requires a properties entry for {input_property}"
        )
    property_schema = properties[input_property]
    if not isinstance(property_schema, dict) or property_schema.get("type") != "string":
        raise ValueError(
            f"grammar constrained sampling property {input_property} must have type string"
        )
    return input_property


def resolve_json_schema_strict_sampling(tool: Tool, supports_strict_mode: bool) -> bool | None:
    config = tool.constrained_sampling
    if not isinstance(config, dict) or config.get("type") != "json_schema":
        return None
    if supports_strict_mode:
        # v0.85.1：先验证 schema 能否 strict 化；不支持时退回普通工具，
        # 除非调用方声明 strict="require"（此时报错）。
        parameters = tool.to_json_schema() if hasattr(tool, "to_json_schema") else tool.parameters
        try:
            make_strict_json_schema(parameters)
            return True
        except UnsupportedStrictJsonSchemaError as exc:
            if config.get("strict") != "require":
                return None
            raise ValueError(
                f'Tool "{tool.name}" requires JSON-schema constrained sampling, but {exc}.'
            ) from exc
    if config.get("strict") == "require":
        raise ValueError(
            f'Tool "{tool.name}" requires JSON-schema constrained sampling, '
            "but strict tools are unsupported."
        )
    return None


def resolve_grammar_constrained_sampling(
    tool: Tool, supports_openai_grammar_tools: bool
) -> GrammarConstrainedSampling | None:
    config = tool.constrained_sampling
    if not isinstance(config, dict) or config.get("type") != "grammar":
        return None
    if not supports_openai_grammar_tools:
        return None

    variants = config.get("variants")
    variants = variants if isinstance(variants, dict) else {}
    lark = variants.get("openai_lark")
    regex = variants.get("openai_regex")
    has_lark = isinstance(lark, str) and bool(lark.strip())
    has_regex = isinstance(regex, str) and bool(regex.strip())
    if not has_lark and not has_regex:
        raise ValueError(
            f'Tool "{tool.name}" cannot use grammar constrained sampling: '
            "no supported grammar variant was provided."
        )
    try:
        input_property = _infer_grammar_input_property(tool)
    except ValueError as exc:
        raise ValueError(
            f'Tool "{tool.name}" cannot use grammar constrained sampling: {exc}.'
        ) from exc
    definition = lark if has_lark else regex
    assert isinstance(definition, str)
    return GrammarConstrainedSampling(
        format="lark" if has_lark else "regex",
        definition=definition,
        input_property=input_property,
    )


def create_grammar_tool_input_properties(
    tools: list[Tool] | None, supports_openai_grammar_tools: bool
) -> dict[str, str]:
    properties: dict[str, str] = {}
    for tool in tools or []:
        grammar = resolve_grammar_constrained_sampling(tool, supports_openai_grammar_tools)
        if grammar is not None:
            properties[tool.name] = grammar.input_property
    return properties


def get_grammar_tool_input(tool_name: str, arguments: dict[str, Any], input_property: str) -> str:
    value = arguments.get(input_property)
    if not isinstance(value, str):
        raise ValueError(
            f'Grammar tool call "{tool_name}" requires argument "{input_property}" to be a string.'
        )
    return value


__all__ = [
    "GrammarConstrainedSampling",
    "GrammarToolInputJsonBuffer",
    "UnsupportedStrictJsonSchemaError",
    "append_grammar_tool_input_json_delta",
    "create_grammar_tool_input_properties",
    "get_grammar_tool_input",
    "get_json_schema_tool_parameters",
    "make_strict_json_schema",
    "resolve_grammar_constrained_sampling",
    "resolve_json_schema_strict_sampling",
]
