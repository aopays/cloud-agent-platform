"""A deliberately small JSON-Schema subset for untrusted tool arguments."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class SchemaValidationError(ValueError):
    pass


def validate_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    _validate(arguments, schema, "arguments")


def _validate(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    type_matches: dict[str, Callable[[Any], bool]] = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }
    if expected in type_matches and not type_matches[expected](value):
        raise SchemaValidationError(f"{path} must be {expected}")

    if expected == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                raise SchemaValidationError(f"{path}.{name} is required")
        if schema.get("additionalProperties", True) is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise SchemaValidationError(f"{path} contains unknown fields: {sorted(unknown)}")
        for name, item in value.items():
            if name in properties:
                _validate(item, properties[name], f"{path}.{name}")

    if expected == "array":
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            raise SchemaValidationError(f"{path} must contain at least {minimum} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{index}]")

    if expected == "string":
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if minimum is not None and len(value) < minimum:
            raise SchemaValidationError(f"{path} is too short")
        if maximum is not None and len(value) > maximum:
            raise SchemaValidationError(f"{path} is too long")
        if "enum" in schema and value not in schema["enum"]:
            raise SchemaValidationError(f"{path} is not an allowed value")
