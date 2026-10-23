import copy
from typing import Any

from app.composition import validate_composition
from tests.helpers import COMPOSITION


def _paths(data: Any) -> list[str]:
    return [e.path for e in validate_composition(data)]


def test_valid_composition_has_no_errors() -> None:
    assert validate_composition(COMPOSITION) == []


def test_blank_label_reports_field_path() -> None:
    data = copy.deepcopy(COMPOSITION)
    data["groups"][0]["items"][0]["label"] = "   "
    assert _paths(data) == ["groups[0].items[0].label"]


def test_non_positive_quantity_is_rejected() -> None:
    data = copy.deepcopy(COMPOSITION)
    data["groups"][0]["items"][0]["quantity"] = {"value": 0, "unit": "개"}
    assert _paths(data) == ["groups[0].items[0].quantity"]


def test_unknown_field_is_rejected() -> None:
    data = copy.deepcopy(COMPOSITION)
    data["groups"][0]["items"][0]["lable"] = "오타"
    assert _paths(data) == ["groups[0].items[0]"]


def test_children_deeper_than_two_levels_are_rejected() -> None:
    data = copy.deepcopy(COMPOSITION)
    child = data["groups"][0]["items"][1]["children"][0]
    child["children"] = [{"id": "too_deep", "label": "x", "order": 10}]
    assert _paths(data) == ["groups[0].items[1].children[0]"]


def test_unsupported_schema_version() -> None:
    assert _paths({"schemaVersion": 2, "groups": []}) == ["schemaVersion"]


def test_duplicate_item_id_including_children_is_rejected() -> None:
    data = copy.deepcopy(COMPOSITION)
    data["groups"][0]["items"][1]["children"][0]["id"] = "coffin"
    assert _paths(data) == ["groups[0].items[1].children[0].id"]


def test_duplicate_group_id_is_rejected() -> None:
    data = copy.deepcopy(COMPOSITION)
    second = copy.deepcopy(data["groups"][0])
    second["items"] = []
    data["groups"].append(second)
    assert _paths(data) == ["groups[1].id"]
