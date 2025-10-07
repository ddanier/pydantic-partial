"""
A partial model will set certain (or all) fields to be optional with a default value of
`None`. This means you can construct a model copy with a partial representation of the details
you would normally provide.

Partial models can be used to for example only send a reduced version of your internal
models as response data to the client when you combine partial models with actively
replacing certain fields with `None` values and usage of `exclude_none` (or
`response_model_exclude_none`).

Usage example:
```python
# Something can be used as a partial, too
class Something(PartialModelMixin, pydantic.BaseModel):
    name: str
    age: int


# Create a full partial model
FullSomethingPartial = Something.as_partial()
FullSomethingPartial(name=None, age=None)
# You could also create a "partial Partial":
#AgeSomethingPartial = Something.as_partial("age")
```
"""

import functools
import warnings
from typing import Any, Optional, TypeVar, Union, cast, get_args, get_origin

from pydantic_partial.utils import copy_field_info

try:
    from types import UnionType
except ImportError:
    UnionType = Union

import pydantic

SelfT = TypeVar("SelfT", bound=pydantic.BaseModel)
ModelSelfT = TypeVar("ModelSelfT", bound="PartialModelMixin")


@functools.lru_cache(maxsize=None, typed=True)
def create_partial_model(
    base_cls: type[SelfT],
    *fields: str,
    recursive: bool = False,
    partial_cls_name: str | None = None,
) -> type[SelfT]:
    # Convert one type to being partial - if possible
    def _partial_annotation_arg(field_name_: str, field_annotation: type) -> type:
        if (
                isinstance(field_annotation, type)
                and issubclass(field_annotation, PartialModelMixin)
        ):
            field_prefix = f"{field_name_}."
            children_fields = [
                field.removeprefix(field_prefix)
                for field
                in fields_
                if field.startswith(field_prefix)
            ]
            if children_fields == ["*"]:
                children_fields = []
            return field_annotation.model_as_partial(*children_fields, recursive=recursive)
        else:
            return field_annotation

    # By default make all fields optional, but use passed fields when possible
    if fields:
        fields_ = list(fields)
    else:
        fields_ = list(base_cls.model_fields.keys())

    # Construct list of optional new field overrides
    optional_fields: dict[str, Any] = {}
    for field_name, field_info in base_cls.model_fields.items():
        field_annotation = field_info.annotation
        if field_annotation is None:  # pragma: no cover
            continue  # This is just to handle edge cases for pydantic 1.x - can be removed in pydantic 2.0

        # Do we have any fields starting with $FIELD_NAME + "."?
        sub_fields_requested = any(
            field.startswith(f"{field_name}.")
            for field
            in fields_
        )

        # Continue if this field needs not to be handled
        if field_name not in fields_ and not sub_fields_requested:
            continue

        # Change type for sub models, if requested
        if recursive or sub_fields_requested:
            field_annotation_origin = get_origin(field_annotation)
            if field_annotation_origin in (Union, UnionType, tuple, list, set, dict):
                if field_annotation_origin is UnionType:
                    field_annotation_origin = Union
                field_annotation = field_annotation_origin[  # type: ignore
                    tuple(  # type: ignore
                        _partial_annotation_arg(field_name, field_annotation_arg)
                        for field_annotation_arg
                        in get_args(field_annotation)
                    )
                ]
            else:
                field_annotation = _partial_annotation_arg(field_name, field_annotation)

        # Construct new field definition
        if field_name in fields_:
            if (  # if field is required, create Optional annotation
                field_info.is_required()
                or (
                    field_info.json_schema_extra is not None
                    and isinstance(field_info.json_schema_extra, dict)
                    and field_info.json_schema_extra.get("required", False)
                )
            ):
                optional_fields[field_name] = (
                    Optional[field_annotation],  # noqa: UP045
                    copy_field_info(
                        field_info,
                        default=None,  # Set default to None
                        default_factory=None,  # Remove default_factory if set
                    ),
                )
        elif recursive or sub_fields_requested:
            optional_fields[field_name] = (
                field_annotation,
                copy_field_info(field_info),
            )

    # Return original model class if nothing has changed
    if not optional_fields:
        return base_cls

    if partial_cls_name is None:
        partial_cls_name = f"{base_cls.__name__}Partial"

    # Generate new subclass model with those optional fields
    return pydantic.create_model(
        partial_cls_name,
        __base__=base_cls,
        **optional_fields,
    )


class PartialModelMixin(pydantic.BaseModel):
    """
    Partial model mixin. Will allow usage of `as_partial()` on the model class
    to create a partial version of the model class.
    """

    @classmethod
    def model_as_partial(
        cls: type[ModelSelfT],
        *fields: str,
        recursive: bool = False,
        partial_cls_name: str | None = None,
    ) -> type[ModelSelfT]:
        return cast(
            type[ModelSelfT],
            create_partial_model(cls, *fields, recursive=recursive, partial_cls_name=partial_cls_name),
        )

    @classmethod
    def as_partial(
        cls: type[ModelSelfT],
        *fields: str,
        recursive: bool = False,
        partial_cls_name: str | None = None,
    ) -> type[ModelSelfT]:
        warnings.warn(
            "as_partial(...) is deprecated, use model_as_partial(...) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls.model_as_partial(*fields, recursive=recursive, partial_cls_name=partial_cls_name)
