import pytest

from app.models.structured import (
    StructuredOutputError,
    parse_json_array,
    parse_json_object,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"tasks":[]}', {"tasks": []}),
        ('```json\n{"tasks":[]}\n```', {"tasks": []}),
        ('好的，结果如下：\n{"tasks":[]}\n以上。', {"tasks": []}),
        ('{"plan":{"tasks":[]}}', {"tasks": []}),
    ],
)
def test_parse_json_object_accepts_common_model_formats(text, expected):
    assert parse_json_object(text, wrapper_keys=("plan",)) == expected


@pytest.mark.parametrize(
    "text",
    [
        '[{"content":"Use SQLite"}]',
        '```json\n[{"content":"Use SQLite"}]\n```',
        '{"memories":[{"content":"Use SQLite"}]}',
        '{"items":[{"content":"Use SQLite"}]}',
    ],
)
def test_parse_json_array_accepts_memory_wrappers(text):
    assert parse_json_array(text, wrapper_keys=("memories", "items")) == [
        {"content": "Use SQLite"}
    ]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no json here",
        "{broken",
        '{"items":{}}',
        '{"unknown":[{"content":"must not be accepted"}]}',
    ],
)
def test_structured_parser_rejects_invalid_or_wrong_shaped_output(text):
    with pytest.raises(StructuredOutputError):
        parse_json_array(text, wrapper_keys=("items",))
