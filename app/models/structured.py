import json
from collections.abc import Iterable
from typing import Any


class StructuredOutputError(ValueError):
    pass


def _json_values(text: str) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    source = text or ""
    index = 0
    while index < len(source):
        character = source[index]
        if character not in "[{":
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(source, index)
        except json.JSONDecodeError:
            index += 1
            continue
        yield value
        index = end


def _unwrap(value: Any, expected_type: type, wrapper_keys: tuple[str, ...]):
    if isinstance(value, dict):
        for key in wrapper_keys:
            wrapped = value.get(key)
            if isinstance(wrapped, expected_type):
                return wrapped
    if isinstance(value, expected_type):
        return value
    return None


def _parse(text: str, expected_type: type, wrapper_keys: tuple[str, ...]):
    for value in _json_values(text):
        parsed = _unwrap(value, expected_type, wrapper_keys)
        if parsed is not None:
            return parsed
    shape = "object" if expected_type is dict else "array"
    raise StructuredOutputError(f"Model output did not contain a JSON {shape}")


def parse_json_object(text: str, wrapper_keys: tuple[str, ...] = ()) -> dict:
    return _parse(text, dict, wrapper_keys)


def parse_json_array(text: str, wrapper_keys: tuple[str, ...] = ()) -> list:
    return _parse(text, list, wrapper_keys)
