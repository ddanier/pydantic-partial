"""mypy plugin that teaches type checkers about ``model_as_partial()``.

``pydantic-partial`` builds the partial model dynamically at runtime, so mypy
otherwise still sees every field as required (see the discussion in
https://github.com/team23/pydantic-partial/issues/2). This plugin closes that
gap for the common assignment form::

    PartialFoo = Foo.model_as_partial()

``model_as_partial()`` used as ``Name = call(...)`` is routed by mypy through
``get_dynamic_class_hook`` (the same mechanism SQLAlchemy uses for
``Base = declarative_base()``). The plugin registers a real, static ``TypeInfo``
for ``PartialFoo`` at the assignment site (so mypy never has to resolve the
call's return value as a type), makes the relevant fields ``Optional``, and
synthesises a matching ``__init__``.

It is designed to run *alongside* Pydantic's own ``pydantic.mypy`` plugin, which
must be enabled too (this plugin reads the field metadata that ``pydantic.mypy``
populates)::

    [tool.mypy]
    plugins = ["pydantic.mypy", "pydantic_partial.mypy"]

Scope: ``model_as_partial()`` with no arguments (all fields become optional) and
calls that select fields by literal name such as ``model_as_partial("age")`` (only
those fields become optional; the rest keep their original requiredness).
``recursive=`` is not fully supported yet: the call still produces a flat partial
(top-level fields become optional), but nested models are not recursed into, so it is
stricter than the runtime behaviour rather than wrong. Field lists that cannot be
resolved statically (non-literal arguments, ``*args`` splats, or dotted/nested names
like ``"items.name"``) and non-assignment uses degrade gracefully to mypy's default
(the original model type). This is never a crash or a silently wrong type.
"""

from __future__ import annotations

from collections.abc import Callable

from mypy.nodes import (
    ARG_NAMED,
    ARG_NAMED_OPT,
    ARG_POS,
    MDEF,
    Argument,
    CallExpr,
    MemberExpr,
    PlaceholderNode,
    RefExpr,
    StrExpr,
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
# ``mymodels.User.model_as_partial`` (not the defining mixin). So we match on the
# method-name suffix and verify the receiver's MRO in the callback.
METHOD_SUFFIXES = (".model_as_partial", ".as_partial")


def _optional(typ: Type) -> Type:
    return UnionType.make_union([typ, NoneType()])


def _selected_fields(call: CallExpr) -> tuple[bool, set[str]] | None:
    """Work out which fields the call asks to make optional.

    Returns ``(True, set())`` for the no-argument form (all fields), ``(False, names)``
    for explicit literal field names, or ``None`` when the arguments cannot be resolved
    statically and the plugin should degrade to mypy's default. Keyword arguments
    (``recursive=``, ``partial_cls_name=``) are ignored for selection purposes.
    """
    names: set[str] = set()
    for arg, kind in zip(call.args, call.arg_kinds, strict=True):
        if kind in (ARG_NAMED, ARG_NAMED_OPT):
            continue
        if kind == ARG_POS and isinstance(arg, StrExpr) and "." not in arg.value:
            names.add(arg.value)
        else:
            # Non-literal positional arg, ``*args`` splat, or dotted/nested name:
            # we cannot know the field set statically.
            return None
    return (True, set()) if not names else (False, names)


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
        # Receiver name not resolved yet; try again next pass.
        if not api.final_iteration:
            api.defer()
        return
    if not isinstance(base_node, TypeInfo):
        return
    base_info = base_node

    # Readiness gate: pydantic.mypy populates its field metadata during semantic
    # analysis of the base model. If it has not run yet, the MRO/fields are not
    # ready, so defer rather than synthesise an empty/wrong class. An empty MRO also
    # falls through here (any() over [] is False), which correctly defers.
    if not any(PYDANTIC_METADATA_KEY in cls.metadata for cls in base_info.mro):
        if not api.final_iteration:
            api.defer()
        return

    # Only act on genuine PartialModelMixin models (guards against unrelated
    # user-defined ``model_as_partial``/``as_partial`` methods sharing the name).
    if not any(b.fullname == MIXIN_FULLNAME for b in base_info.mro):
        return

    selection = _selected_fields(ctx.call)
    if selection is None:
        # Field list cannot be resolved statically; leave mypy's default in place.
        return
    all_fields, selected = selection

    base_instance = fill_typevars(base_info)
    if not isinstance(base_instance, Instance):
        return

    # Build a fresh subclass TypeInfo each call. Because it starts empty, rebuilding
    # on every (possibly repeated / deferred) invocation is inherently idempotent;
    # nothing accumulates across passes.
    info = api.basic_new_typeinfo(ctx.name, base_instance, ctx.call.line)
    info.metaclass_type = base_info.metaclass_type

    # Collect fields (name -> has_default) from Pydantic's own metadata across the
    # MRO (the authoritative source, kept consistent with pydantic's own view).
    fields: dict[str, bool] = {}
    for cls in base_info.mro:
        metadata = cls.metadata.get(PYDANTIC_METADATA_KEY)
        if metadata:
            for name, data in metadata.get("fields", {}).items():
                if name not in fields:
                    fields[name] = bool(data.get("has_default", False))

    init_args: list[Argument] = []
    for name, has_default in fields.items():
        sym = base_info.get(name)
        node = sym.node if sym is not None else None
        if isinstance(node, PlaceholderNode):
            # Field type not analysed yet; defer.
            if not api.final_iteration:
                api.defer()
            return
        if not isinstance(node, Var) or node.type is None:
            continue

        # A required field becomes optional only if it was selected (or all fields
        # were). Fields that already have a default stay optional; other unselected
        # fields keep their original (required) type.
        if (all_fields or name in selected) and not has_default:
            typ = _optional(node.type)
            add_attribute_to_class(api, info.defn, name, typ)
            kind = ARG_NAMED_OPT
        else:
            typ = node.type
            kind = ARG_NAMED_OPT if has_default else ARG_NAMED

        var = Var(name, typ)
        var.info = info
        init_args.append(Argument(var, typ, None, kind))

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
