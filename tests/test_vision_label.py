from __future__ import annotations

from rover.client import parse_json_object


def test_parse_json_object_plain():
    assert parse_json_object('{"summary":"ok","labels":["desk"]}') == {"summary": "ok", "labels": ["desk"]}


def test_parse_json_object_fenced():
    assert parse_json_object('```json\n{"summary":"ok"}\n```') == {"summary": "ok"}


def test_parse_json_object_with_surrounding_text():
    assert parse_json_object('Here is JSON: {"clear_path": true, "confidence": 0.7}') == {"clear_path": True, "confidence": 0.7}
