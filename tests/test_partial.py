from collections.abc import Iterable
from typing import Any, Union, get_args

import pydantic
import pytest
from pydantic import ConfigDict

from pydantic_partial import PartialModelMixin


def _field_is_required(
    model: type[pydantic.BaseModel] | pydantic.BaseModel,
    field_name: str,
) -> bool:
    """Check if a field is required on a pydantic V2 model."""
    return model.model_fields[field_name].is_required()

def _get_subtype(
    model: type[pydantic.BaseModel] | pydantic.BaseModel,
    field_name: str,
) -> pydantic.BaseModel:
    try:
        return get_args(get_args(model.model_fields[field_name].annotation)[0])[0]
    except IndexError:
        return get_args(model.model_fields[field_name].annotation)[0]

def _get_alias(
    model: type[pydantic.BaseModel] | pydantic.BaseModel,
    field_name: str,
) -> str:
    return model.model_fields[field_name].alias

def _get_title(
    model: type[pydantic.BaseModel] | pydantic.BaseModel,
    field_name: str,
) -> str:
    return model.model_fields[field_name].title

def _get_extra(
    model: type[pydantic.BaseModel] | pydantic.BaseModel,
    field_name: str,
) -> dict[str, Any]:
    return model.model_fields[field_name].json_schema_extra


class Something(PartialModelMixin, pydantic.BaseModel):
    name: str = pydantic.Field(
        ..., alias="test_name", title="TEST Name",
        json_schema_extra={"something_else": True},
    )
    age: int
    already_optional: None = None

    model_config = ConfigDict(populate_by_name=True)


class SomethingList(PartialModelMixin, pydantic.BaseModel):
    items: list[Something]


def test_setup_is_sane():
    assert _field_is_required(Something, "name") is True
    assert _field_is_required(Something, "age") is True
    assert _field_is_required(SomethingList, "items") is True


def test_partial_will_make_all_fields_optional():
    SomethingPartial = Something.model_as_partial()

    assert _field_is_required(SomethingPartial,"name") is False
    assert _field_is_required(SomethingPartial,"age")  is False
    SomethingPartial()


def test_partial_will_keep_original_field_options():
    SomethingPartial = Something.model_as_partial()

    assert _get_alias(SomethingPartial,"name") == "test_name"
    assert _get_title(SomethingPartial,"name") == "TEST Name"
    assert _get_extra(SomethingPartial,"name")["something_else"] is True


def test_partial_allows_to_only_change_certain_fields():
    SomethingNamePartial = Something.model_as_partial("name")

    assert _field_is_required(SomethingNamePartial,"name") is False
    assert _field_is_required(SomethingNamePartial,"age") is True

    SomethingNamePartial(age=1)
    with pytest.raises(pydantic.ValidationError):
        SomethingNamePartial(name="test")

    SomethingAgePartial = Something.model_as_partial("age")

    assert _field_is_required(SomethingAgePartial,"name") is True
    assert _field_is_required(SomethingAgePartial,"age") is False
    SomethingAgePartial(name="test")
    with pytest.raises(pydantic.ValidationError):
        SomethingAgePartial(age=1)

    SomethingPartial = Something.model_as_partial("name", "age")

    assert _field_is_required(SomethingPartial,"name") is False
    assert _field_is_required(SomethingPartial,"age") is False
    SomethingPartial()


def test_partial_allows_recursive_usage():
    SomethingListPartial = SomethingList.model_as_partial()

    assert _field_is_required(SomethingListPartial,"items") is False
    # Optional[List[...]]
    sub_type = _get_subtype(SomethingListPartial, "items")
    assert _field_is_required(sub_type,"name") is True
    assert _field_is_required(sub_type,"age") is True

    SomethingListRecursivePartial = SomethingList.model_as_partial(recursive=True)

    assert _field_is_required(SomethingListRecursivePartial,"items") is False
    # Optional[List[...]]
    sub_type = _get_subtype(SomethingListRecursivePartial,"items")
    assert _field_is_required(sub_type,"name") is False
    assert _field_is_required(sub_type,"age") is False


@pytest.mark.parametrize(
    ("partial_fields", "recursive", "items_required", "name_required", "age_required", "example_items"),
    [
        pytest.param(
            ("items.*",),
            False,
            True,
            False,
            False,
            [
                [],
            ],
            id="items.*",
        ),
        pytest.param(
            ("items",),
            False,
            False,
            True,
            True,
            [
                [],
                None,
            ],
            id="items",
        ),
        pytest.param(
            ("items.name",),
            False,
            True,
            False,
            True,
            [
                [],
                [{"age": 1}],
            ],
            id="items.name",
        ),
        pytest.param(
            (),
            True,
            False,
            False,
            False,
            [
                [],
                None,
                [{}],
            ],
            id="recursive",
        ),
        pytest.param(
            ("items.name",),
            True,
            True,
            False,
            True,
            [
                [],
                [{"age": 1}],
            ],
            id="items.name - recursive",
        ),
    ],
)
def test_partial_allows_explicit_recursive(
    partial_fields: Iterable[str],
    recursive: bool,
    items_required: bool,
    name_required: bool,
    age_required: bool,
    example_items: Iterable[None | list[Any]],
):
    SomethingListPartial = SomethingList.model_as_partial(*partial_fields,recursive=recursive)

    assert _field_is_required(SomethingListPartial,"items") is items_required
    sub_type = _get_subtype(SomethingListPartial,"items")  # List[...]
    assert _field_is_required(sub_type,"name") is name_required
    assert _field_is_required(sub_type,"age") is age_required
    for example in example_items:
        SomethingListPartial(items=example)


def test_no_change_to_optional_fields():
    SomethingPartial = Something.model_as_partial("already_optional")

    assert SomethingPartial is Something


def test_as_partial_works_as_expected():
    with pytest.warns(DeprecationWarning, match=".*is deprecated.*"):
        assert Something.model_as_partial() is Something.as_partial()


def test_partial_class_name_can_be_overridden():
    SomethingPartial = Something.model_as_partial("name")
    assert SomethingPartial.__name__ == "SomethingPartial"

    partial_cls_name = "SomethingWithOptionalName"
    SomethingWithOptionalName = Something.model_as_partial("name", partial_cls_name=partial_cls_name)
    assert SomethingWithOptionalName.__name__ == partial_cls_name
