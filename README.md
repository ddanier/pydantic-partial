# pydantic-partial

## Installation

Just use `pip install pydantic-partial` to install the library.

**Note:** `pydantic-partial` is compatible with `pydantic` version `2.x` on Python `3.10`, `3.11`, `3.12`
and `3.13`. This is also ensured running all tests on all those versions using `tox`.

## About

Create partial models from your normal pydantic models. Partial models will allow
some or all fields to be optional and thus not be required when creating the model
instance.

Partial models can be used to support PATCH HTTP requests where the user only wants
to update some fields of the model and normal validation for required fields is not
required. It may also be used to have partial response DTOs where you want to skip
certain fields, this can be useful in combination with `exclude_none`. It is - like
shown in these examples - intended to be used with API use cases, so when using
pydantic with for example FastAPI.

**Disclaimer:** This is still an early release of `pydantic-partial`. Things might
change in the future. PR welcome. ;-)

### Usage example

`pydantic-partial` provides a mixin to generate partial model classes. The mixin can
be used like this:

```python
import pydantic
from pydantic_partial import PartialModelMixin

# Something model, then can be used as a partial, too:
class Something(PartialModelMixin, pydantic.BaseModel):
    name: str
    age: int


# Create a full partial model
FullSomethingPartial = Something.model_as_partial()
FullSomethingPartial()  # Same as FullSomethingPartial(name=None, age=None)
```

### Without using the mixin

You also may create partial models without using the mixin:

```python
import pydantic
from pydantic_partial import create_partial_model

# Something model, without the mixin:
class Something(pydantic.BaseModel):
    name: str
    age: int


# Create a full partial model
FullSomethingPartial = create_partial_model(Something)
FullSomethingPartial()  # Same as FullSomethingPartial(name=None, age=None)
```

### Only changing some fields to being optional

`pydantic-partial` can be used to create partial models that only change some
of the fields to being optional. Just pass the list of fields to be optional to
the `as_partial()` or `create_partial_model()` function.

```python
import pydantic
from pydantic_partial import create_partial_model

class Something(pydantic.BaseModel):
    name: str
    age: int

# Create a partial model only for the name attribute
FullSomethingPartial = create_partial_model(Something, 'name')
FullSomethingPartial(age=40)  # Same as FullSomethingPartial(name=None, age=40)
# This would still raise an error: FullSomethingPartial(age=None, ...)
```

### Recursive partials

Partial models can be created changing the field of all nested models to being
optional, too.

```python
from typing import List

import pydantic
from pydantic_partial import PartialModelMixin, create_partial_model

class InnerSomething(PartialModelMixin, pydantic.BaseModel):
    name: str

class OuterSomething(pydantic.BaseModel):
    name: str
    things: List[InnerSomething]

# Create a full partial model
RecursiveOuterSomethingPartial = create_partial_model(OuterSomething, recursive=True)
RecursiveOuterSomethingPartial(things=[
    {},
])
```

**Note:** The inner model MUST extend the `PartialModelMixin` mixin. Otherwise
`pydantic-partial` will not be able to detect which fields may allow to being
converted to partial models.

**Also note:** My recommendation would be to always create such recursive
partials by creating partials for all the required models and then override
the fields on you outer partial model class. This is way more explicit.

## Known limitations

`pydantic-partial` cannot generate new class types that actually are supported by the
Python typing system rules. This means that the partial models will only be recognized
as the same as their original model classes - type checkers will not know about the partial
model changes and thus will think all those partial fields are still required.

This is due to the fact that Python itself has no concept of partials. `pydantic-partial`
could (in theory) provide plugins for `mypy` for example to "patch" this in, but this would
be a massive amount of work while being kind of a bad hack. The real solution would be to
have a partial type in Python itself, but this is not planned for the near future as far
as I know.

My recommendation is to use `pydantic-partial` only for API use cases where you do not
need to work with the partial aspects of the models - they are just the DTOs (data transfer
objects) you are using. If you need to use partial models in other cases you might get
errors by your type checker - if you use one. Please be aware of this.

**Note:** Not having a good solution in Python itself for this is the reason `pydantic` does
not support partial models in the first place. `pydantic-partial` is just a really good
workaround for this issue.  
See [issue 2](https://github.com/team23/pydantic-partial/issues/2) in this project and
[issue 1673](https://github.com/pydantic/pydantic/issues/1673#issuecomment-1557267229)
in the `pydantic` project for reference.

Having that all said: If anyone wants to get a working plugin for `mypy` or others ready,
I'm going to very much support this.

# Contributing

If you want to contribute to this project, feel free to just fork the project,
create a dev branch in your fork and then create a pull request (PR). If you
are unsure about whether your changes really suit the project please create an
issue first, to talk about this.
