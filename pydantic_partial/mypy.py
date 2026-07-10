"""mypy plugin that teaches type checkers about ``model_as_partial()``.

``pydantic-partial`` builds the partial model dynamically at runtime, so mypy
otherwise still sees every field as required (see the discussion in
https://github.com/team23/pydantic-partial/issues/2). This plugin closes that
gap for the common assignment form::

    PartialFoo = Foo.model_as_partial()

``model_as_partial()`` used as ``Name = call(...)`` is routed by mypy through
``get_dynamic_class_hook`` (the same mechanism SQLAlchemy uses for
``Base = declarative_base()``). The plugin registers a real, static ``TypeInfo``
for ``PartialFoo`` at the assignment site — so mypy never has to resolve the
call's return value as a type — gives each field an ``Optional[T]`` attribute,
and synthesises an all-optional ``__init__``.

It is designed to run *alongside* Pydantic's own ``pydantic.mypy`` plugin, which
must be enabled too (this plugin reads the field metadata that ``pydantic.mypy``
populates)::

    [tool.mypy]
    plugins = ["pydantic.mypy", "pydantic_partial.mypy"]

Scope: the no-argument ``model_as_partial()`` call (all fields optional).
Field-selecting calls such as ``model_as_partial("age")`` are not handled yet and
degrade gracefully to mypy's default (the original model type) — never a crash or
a silently wrong type.
"""

from __future__ import annotations

from collections.abc import Callable

from mypy.nodes import (
    ARG_NAMED_OPT,
    ARG_POS,
    MDEF,
    Argument,
    MemberExpr,
    PlaceholderNode,
    RefExpr,
    SymbolTableNode,
    TypeInfo,
    Var,
)
from mypy.plugin import DynamicClassDefContext, Plugin
from mypy.plugins.common import add_attribute_to_class, add_method_to_class
from mypy.types import Instance, NoneType, Type, UnionType
from mypy.typevars import fill_typevars

MIXIN_FULLNAME = "pydantic_partial.partial.PartialModelMixin"
PYDANTIC_METADATA_KEY = "pydantic-mypy-metadata"
# mypy reports the fullname of the *receiver subclass*, e.g.
# ``mymodels.User.model_as_partial`` — not the defining mixin. So we match on the
# method-name suffix and verify the receiver's MRO in the callback.
METHOD_SUFFIXES = (".model_as_partial", ".as_partial")


def _optional(typ: Type) -> Type:
    return UnionType.make_union([typ, NoneType()])


def _model_as_partial_callback(ctx: DynamicClassDefContext) -> None:
    api = ctx.api

    callee = ctx.call.callee
    if not isinstance(callee, MemberExpr):
        return
    base_expr = callee.expr
    if not isinstance(base_expr, RefExpr):
        return

    base_node = base_expr.node
    if base_node is None:
        # Receiver name not resolved yet — try again next pass.
        if not api.final_iteration:
            api.defer()
        return
    if not isinstance(base_node, TypeInfo):
        return
    base_info = base_node

    # Readiness gate: pydantic.mypy populates its field metadata during semantic
    # analysis of the base model. If it has not run yet, the MRO/fields are not
    # ready — defer rather than synthesise an empty/wrong class. An empty MRO also
    # falls through here (any() over [] is False), which correctly defers.
    if not any(PYDANTIC_METADATA_KEY in cls.metadata for cls in base_info.mro):
        if not api.final_iteration:
            api.defer()
        return

    # Only act on genuine PartialModelMixin models (guards against unrelated
    # user-defined ``model_as_partial``/``as_partial`` methods sharing the name).
    if not any(b.fullname == MIXIN_FULLNAME for b in base_info.mro):
        return

    # Only the no-field-argument form for now. Positional args select specific
    # fields (not handled yet); degrade gracefully to mypy's default type there.
    if any(kind == ARG_POS for kind in ctx.call.arg_kinds):
        return

    base_instance = fill_typevars(base_info)
    if not isinstance(base_instance, Instance):
        return

    # Build a fresh subclass TypeInfo each call. Because it starts empty, rebuilding
    # on every (possibly repeated / deferred) invocation is inherently idempotent —
    # nothing accumulates across passes.
    info = api.basic_new_typeinfo(ctx.name, base_instance, ctx.call.line)
    info.metaclass_type = base_info.metaclass_type

    # Collect field names from Pydantic's own metadata across the MRO (the
    # authoritative source — keeps our view of the model consistent with pydantic).
    field_names: list[str] = []
    for cls in base_info.mro:
        metadata = cls.metadata.get(PYDANTIC_METADATA_KEY)
        if metadata:
            for field_name in metadata.get("fields", {}):
                if field_name not in field_names:
                    field_names.append(field_name)

    init_args: list[Argument] = []
    for field_name in field_names:
        sym = base_info.get(field_name)
        node = sym.node if sym is not None else None
        if isinstance(node, PlaceholderNode):
            # Field type not analysed yet — defer.
            if not api.final_iteration:
                api.defer()
            return
        if not isinstance(node, Var) or node.type is None:
            continue
        opt_type = _optional(node.type)
        add_attribute_to_class(api, info.defn, field_name, opt_type)
        var = Var(field_name, opt_type)
        var.info = info
        init_args.append(Argument(var, opt_type, None, ARG_NAMED_OPT))

    add_method_to_class(api, info.defn, "__init__", args=init_args, return_type=NoneType())

    api.add_symbol_table_node(ctx.name, SymbolTableNode(MDEF, info))


class PydanticPartialPlugin(Plugin):
    def get_dynamic_class_hook(
        self,
        fullname: str,
    ) -> Callable[[DynamicClassDefContext], None] | None:
        if fullname.endswith(METHOD_SUFFIXES):
            return _model_as_partial_callback
        return None


def plugin(version: str) -> type[Plugin]:  # noqa: ARG001  # `version` is mypy's plugin entry-point contract
    return PydanticPartialPlugin
