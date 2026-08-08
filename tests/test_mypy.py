"""Tests for the mypy plugin (``pydantic_partial.mypy``).

Includes explicit regression tests for the two subtle behaviours the plugin
depends on:

* the receiver-fullname gotcha — mypy reports ``<module>.<Model>.model_as_partial``,
  so matching is by method-name suffix plus an MRO check, never a hardcoded fullname;
* ``__init__`` dominance — the plugin's precisely-typed optional ``__init__`` must
  win over the one ``pydantic.mypy`` would otherwise generate for the same class.
"""

MODEL = """
    import pydantic
    from pydantic_partial import PartialModelMixin

    class User(PartialModelMixin, pydantic.BaseModel):
        name: str
        age: int
"""

MODEL_WITH_DEFAULT = """
    import pydantic
    from pydantic_partial import PartialModelMixin

    class User(PartialModelMixin, pydantic.BaseModel):
        name: str
        count: int = 0
"""


def test_all_fields_become_optional(mypy):
    result = mypy.run(MODEL + """
    UserPartial = User.model_as_partial()
    u = UserPartial()                 # no args: valid only if all fields optional
    reveal_type(u.name)
    reveal_type(u.age)
    """)
    assert result.errors == []
    assert "str | None" in result.stdout
    assert "int | None" in result.stdout


def test_values_still_accepted(mypy):
    result = mypy.run(MODEL + """
    UserPartial = User.model_as_partial()
    UserPartial(name="x", age=1)      # supplying values must still type-check
    """)
    assert result.errors == []


def test_wrong_type_still_rejected(mypy):
    # Optional must mean ``T | None``, not ``Any`` — a wrong-typed value is an error.
    result = mypy.run(MODEL + """
    UserPartial = User.model_as_partial()
    UserPartial(name=123)             # int is not str | None
    """)
    assert any("arg-type" in e or "incompatible type" in e for e in result.errors), result.stdout


def test_init_dominates_pydantic_required_init(mypy):
    """With pydantic.mypy also active, ``UserPartial()`` must NOT demand name/age.

    pydantic.mypy generates a *required* ``__init__`` for models; if the plugin's
    optional ``__init__`` ever stops winning, this call raises "Missing named argument".
    """
    result = mypy.run(MODEL + """
    UserPartial = User.model_as_partial()
    UserPartial()
    """)
    assert not any("Missing named argument" in e for e in result.errors), result.stdout


def test_matches_regardless_of_receiver_module(mypy):
    """The model here has fullname ``case.User`` — matching must not be tied to the
    ``pydantic_partial.PartialModelMixin`` fullname."""
    result = mypy.run(MODEL + """
    Partial = User.model_as_partial()
    reveal_type(Partial().name)
    """)
    assert result.errors == []
    assert "str | None" in result.stdout


def test_ignores_unrelated_model_as_partial(mypy):
    """A class that merely *has* a ``model_as_partial`` method but is not a
    PartialModelMixin subclass must be left untouched by the plugin."""
    result = mypy.run("""
    class NotAPartialModel:
        @classmethod
        def model_as_partial(cls) -> type["NotAPartialModel"]:
            return cls

    X = NotAPartialModel.model_as_partial()
    reveal_type(X)
    """)
    assert "type[case.NotAPartialModel]" in result.stdout
    assert "-> case.X" not in result.stdout


def test_as_partial_alias_also_handled(mypy):
    """The deprecated ``as_partial`` alias is handled the same as ``model_as_partial``."""
    result = mypy.run(MODEL + """
    UserPartial = User.as_partial()
    UserPartial()
    reveal_type(UserPartial().name)
    """)
    assert not any("Missing named argument" in e for e in result.errors), result.stdout
    assert "str | None" in result.stdout


# --- field-selecting calls: model_as_partial("age") ------------------------


def test_single_field_selection_only_that_field_optional(mypy):
    result = mypy.run(MODEL + """
    Partial = User.model_as_partial("age")
    p = Partial(name="x")   # age optional, name still required
    reveal_type(p.age)      # int | None
    reveal_type(p.name)     # str, unchanged
    """)
    assert result.errors == []
    assert "int | None" in result.stdout
    assert "str | None" not in result.stdout  # name must not have been made optional


def test_unselected_field_stays_required(mypy):
    result = mypy.run(MODEL + """
    Partial = User.model_as_partial("age")
    Partial()   # name is still required, so this must error
    """)
    assert any("Missing named argument" in e and '"name"' in e for e in result.errors)
    assert not any("Missing named argument" in e and '"age"' in e for e in result.errors)


def test_multiple_field_selection(mypy):
    result = mypy.run(MODEL + """
    Partial = User.model_as_partial("name", "age")
    Partial()   # both selected, so both optional
    """)
    assert result.errors == []


def test_field_with_default_stays_optional_and_keeps_type(mypy):
    result = mypy.run(MODEL_WITH_DEFAULT + """
    Partial = User.model_as_partial("name")
    Partial()                     # name optional (selected), count optional (has default)
    reveal_type(Partial().name)   # str | None
    reveal_type(Partial().count)  # int, not wrapped in Optional
    """)
    assert result.errors == []
    assert "str | None" in result.stdout
    assert "int | None" not in result.stdout  # count keeps its plain type


def test_non_literal_field_arg_degrades_gracefully(mypy):
    result = mypy.run(MODEL + """
    field = "age"
    Partial = User.model_as_partial(field)   # non-literal: cannot be resolved statically
    reveal_type(Partial)
    """)
    # Falls back to mypy's default (the classmethod return type), not a synthesized partial,
    # and does not crash.
    assert result.errors == []
    assert "type[case.User]" in result.stdout
    assert "-> case.Partial" not in result.stdout


def test_synthetic_type_survives_incremental_cache(mypy):
    """The partial lives in a separate module that stays cached while the consumer
    is re-checked — exercising serialization of the plugin-generated type across
    the incremental cache boundary (not just a single ``--no-incremental`` run)."""
    models = MODEL + "    UserPartial = User.model_as_partial()\n"

    first = mypy.run("""
    from models import UserPartial
    u = UserPartial()
    reveal_type(u.name)
    """, incremental=True, extra_files={"models.py": models})
    assert first.errors == [], first.stdout
    assert "str | None" in first.stdout

    second = mypy.run("""
    from models import UserPartial
    u = UserPartial()
    reveal_type(u.age)
    u2 = UserPartial()
    """, incremental=True, extra_files={"models.py": models})
    assert second.errors == [], second.stdout
    assert "int | None" in second.stdout
