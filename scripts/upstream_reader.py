"""Read upstream board files without executing them (U56 Phase 0, plan decision D-7).

The Amaranth and LiteX board definitions are Python files.  Executing one to read its data
would run a third party's code with the user's privileges, so this module never does: it
parses each file with :func:`ast.parse` and *interprets* the small subset of Python that
board files use.  Upstream functions and classes become values this interpreter walks; they
are never compiled.  The interpreter calls into real Python only for:

* the objects in the namespace a parser hands it -- its own mocks (``Resource``, ``Pins``,
  the vendor platform classes, ...) -- and the methods of instances they create;
* classes and functions it builds itself from upstream definitions, whose bodies it
  interprets in turn (:class:`InterpretedFunction`);
* a fixed allowlist of side-effect-free builtins (:data:`_SAFE_BUILTINS`); and
* an allowlist of ``str`` / ``list`` / ``dict`` / ``tuple`` / ``set`` methods.

Anything else -- a dunder attribute other than ``__init__``, an ``import`` that survived the
parsers' line blanking, ``str.format`` with an attribute or index field (which reads
attributes without a call), any other native callable, or a construct this module does not
implement -- raises :class:`UnsupportedConstructError`, naming the file, line and construct.
Upstream ``try``/``except`` cannot catch that refusal.  Step and size budgets stop runaway
loops and allocations.  Ordinary Python errors (a ``NameError`` for an undefined name, a
``TypeError`` from a mock) are raised as Python would raise them, so a file fails exactly
where ``exec`` used to fail.

Self-contained: no ``fpga_sim`` dependency, no third-party imports.
"""

from __future__ import annotations

import ast
import operator
import string
import types
from collections.abc import Callable, Iterable, Iterator
from typing import Any, cast

#: A value computed by upstream code: dynamically typed by nature, so the interpreter's own
#: signatures say so by name rather than with a bare ``Any``.
UpstreamValue = Any

#: Interpreter steps (statements + expressions) one file may take.
MAX_STEPS = 2_000_000
#: Longest list, tuple, string or range the interpreter will build.
MAX_SIZE = 1_000_000
#: Largest exponent or shift count accepted, so ``10 ** 10 ** 10`` cannot stall a sync.
MAX_EXPONENT = 100_000


class UnsupportedConstructError(Exception):
    """A construct the reader refuses to evaluate: reported, never executed."""

    def __init__(self, filename: str, lineno: int, what: str) -> None:
        """Record where the construct is and what it is."""
        super().__init__(f"{filename}:{lineno}: {what}")
        self.filename = filename
        self.lineno = lineno
        self.what = what


class ModuleStub:
    """An inert stand-in for a module an upstream file names, e.g. ``unittest``.

    Only the attributes given here exist; the reader may read them and nothing else.
    """

    def __init__(self, name: str, **attrs: object) -> None:
        """Create the stub with exactly *attrs*."""
        self._name = name
        self._attrs = dict(attrs)

    def get(self, attr: str) -> object:
        """Return one stub attribute, or raise ``AttributeError`` as a module would."""
        try:
            return self._attrs[attr]
        except KeyError:
            raise AttributeError(
                f"module {self._name!r} has no attribute {attr!r}", name=attr
            ) from None

    def classes(self) -> list[type]:
        """Every class among the stub's attributes."""
        return [v for v in self._attrs.values() if isinstance(v, type)]


_NO_DEFAULT = object()


# ── Control flow (never visible to upstream code) ──────────────────────────────


class _ControlFlow(BaseException):
    """Base of the interpreter's own control-flow signals; upstream handlers never match it."""


class _Return(_ControlFlow):
    def __init__(self, value: object) -> None:
        self.value = value


class _Break(_ControlFlow):
    pass


class _Continue(_ControlFlow):
    pass


# ── Allowlists ─────────────────────────────────────────────────────────────────

_ALLOWED_EXCEPTIONS: tuple[type[BaseException], ...] = (
    Exception,
    ArithmeticError,
    AssertionError,
    AttributeError,
    ImportError,
    IndexError,
    KeyError,
    LookupError,
    ModuleNotFoundError,
    NameError,
    NotImplementedError,
    RuntimeError,
    TypeError,
    ValueError,
    ZeroDivisionError,
)

_METHOD_ALLOWLIST: dict[type, frozenset[str]] = {
    str: frozenset(
        "capitalize center count endswith find format index isalnum isalpha isdigit islower "
        "isupper join ljust lower lstrip partition replace rfind rindex rjust rpartition rsplit "
        "rstrip split splitlines startswith strip swapcase title upper zfill".split()
    ),
    list: frozenset("append copy count extend index insert pop remove reverse sort".split()),
    dict: frozenset("copy get items keys pop setdefault update values".split()),
    tuple: frozenset("count index".split()),
    set: frozenset(
        "add copy difference discard intersection issubset issuperset pop remove union "
        "update".split()
    ),
    frozenset: frozenset("copy difference intersection issubset issuperset union".split()),
    int: frozenset("bit_length to_bytes".split()),
    float: frozenset("is_integer".split()),
    range: frozenset("count index start step stop".split()),
}


def _checked_size(value: object) -> object:
    if isinstance(value, (str, bytes, list, tuple, range, dict, set, frozenset)):
        if len(value) > MAX_SIZE:
            raise _SizeError(f"a {type(value).__name__} of {len(value)} items")
    return value


class _SizeError(Exception):
    """Raised by the size guard; converted to :class:`UnsupportedConstructError` with a location."""


def _safe_range(*args: int) -> range:
    r = range(*args)
    _checked_size(r)
    return r


def _safe_pow(base: UpstreamValue, exp: UpstreamValue, mod: UpstreamValue = None) -> UpstreamValue:
    if isinstance(exp, int) and abs(exp) > MAX_EXPONENT:
        raise _SizeError(f"an exponent of {exp}")
    return pow(base, exp, mod)


def _no_print(*args: object, **kwargs: object) -> None:
    return None


_SAFE_BUILTINS: dict[str, object] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "callable": callable,
    "chr": chr,
    "classmethod": classmethod,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": _safe_pow,
    "print": _no_print,
    "property": property,
    "range": _safe_range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "staticmethod": staticmethod,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
    "NotImplemented": NotImplemented,
    "Ellipsis": Ellipsis,
    **{exc.__name__: exc for exc in _ALLOWED_EXCEPTIONS},
}
_SAFE_CALLABLE_IDS = frozenset(id(v) for v in _SAFE_BUILTINS.values() if callable(v))

_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _safe_pow,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.BitAnd: operator.and_,
}
_INPLACE: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.iadd,
    ast.Sub: operator.isub,
    ast.Mult: operator.imul,
    ast.Div: operator.itruediv,
    ast.FloorDiv: operator.ifloordiv,
    ast.Mod: operator.imod,
    ast.Pow: _safe_pow,
    ast.LShift: operator.ilshift,
    ast.RShift: operator.irshift,
    ast.BitOr: operator.ior,
    ast.BitXor: operator.ixor,
    ast.BitAnd: operator.iand,
}
_CMPOPS: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_UNARYOPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
    ast.Invert: operator.invert,
}


# ── Scopes and interpreted functions ───────────────────────────────────────────


class _Scope:
    """One name scope: a module, a class body, a function call or a comprehension."""

    def __init__(
        self,
        kind: str,
        names: dict[str, Any],
        parent: _Scope | None,
        function: InterpretedFunction | None = None,
        self_arg: object = None,
    ) -> None:
        self.kind = kind
        self.names = names
        self.parent = parent
        self.function = function
        self.self_arg = self_arg

    def lookup_chain(self) -> Iterator[_Scope]:
        """Yield the scopes a name lookup visits, innermost first (class scopes skipped)."""
        scope: _Scope | None = self
        first = True
        while scope is not None:
            # A class body is visible only to statements directly inside it, never to the
            # functions or comprehensions nested in it (Python's scoping rule).
            if first or scope.kind != "class":
                yield scope
            first = False
            scope = scope.parent

    def enclosing_function(self) -> _Scope | None:
        scope: _Scope | None = self
        while scope is not None:
            if scope.kind == "function":
                return scope
            scope = scope.parent
        return None


class InterpretedFunction:
    """An upstream ``def`` or ``lambda``: its body is interpreted, never compiled.

    It is a descriptor like a Python function, so a class built from upstream code binds it
    as a method, and native code (a mock, ``sorted(key=...)``, ``type.__call__`` running an
    ``__init__``) may call it -- the call runs the interpreter.
    """

    def __init__(
        self,
        reader: _Reader,
        name: str,
        args: ast.arguments,
        body: list[ast.stmt] | ast.expr,
        defaults: list[object],
        kw_defaults: list[object | None],
        closure: _Scope,
        lineno: int,
    ) -> None:
        """Capture a definition; *defaults* were evaluated when the ``def`` ran."""
        self.reader = reader
        self.name = name
        self.args = args
        self.body = body
        self.defaults = defaults
        self.kw_defaults = kw_defaults
        self.closure = closure
        self.lineno = lineno
        self.owner: type | None = None

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Run the function body in the interpreter."""
        return self.reader.call_function(self, args, kwargs)

    def parameter_defaults(self) -> dict[str, object]:
        """Return every parameter that has a default, with the value the ``def`` gave it.

        This is ``inspect.signature``'s answer for a function that is never compiled:
        the LiteX sync records a constructor's version parameters from it (U56 §4.1).
        """
        spec = self.args
        positional = [a.arg for a in (*spec.posonlyargs, *spec.args)]
        with_default = positional[len(positional) - len(self.defaults) :]
        defaults: dict[str, object] = dict(zip(with_default, self.defaults, strict=True))
        for arg, default in zip(spec.kwonlyargs, self.kw_defaults, strict=True):
            if default is not _NO_DEFAULT:
                defaults[arg.arg] = default
        return defaults

    def __get__(self, instance: object, owner: type | None = None) -> object:
        """Bind to *instance* as a Python function would."""
        if instance is None:
            return self
        return _BoundInterpreted(self, instance)

    def __repr__(self) -> str:
        """Name the upstream function."""
        return f"<upstream function {self.name}>"


class _TrustedNative:
    """A native ``__init__`` reached through one of our classes (``Base.__init__(self, ...)``)."""

    def __init__(self, function: Callable[..., object]) -> None:
        self.function = function

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self.function(*args, **kwargs)


class _BoundInterpreted:
    """An :class:`InterpretedFunction` bound to an instance (a method call target)."""

    def __init__(self, function: InterpretedFunction, instance: object) -> None:
        self.function = function
        self.instance = instance

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self.function.reader.call_function(self.function, (self.instance, *args), kwargs)


# ── The interpreter ────────────────────────────────────────────────────────────


class _Reader:
    """Interpret one upstream module into *namespace* (see the module docstring)."""

    def __init__(self, filename: str, namespace: dict[str, Any]) -> None:
        self.filename = filename
        self.globals = namespace
        self.steps = 0
        self.lineno = 0
        own_classes: list[type] = []
        own_callables: list[object] = []
        for value in namespace.values():
            if isinstance(value, ModuleStub):
                own_classes.extend(value.classes())
            elif isinstance(value, type):
                own_classes.append(value)
            elif callable(value):
                own_callables.append(value)
        self.own_classes: tuple[type, ...] = tuple(own_classes)
        self.own_callable_ids = {id(c) for c in own_callables} | {id(c) for c in own_classes}
        self.built_classes: list[type] = []

    # ── errors and budgets ──────────────────────────────────────────────────

    def refuse(self, node: ast.AST | None, what: str) -> UnsupportedConstructError:
        lineno = getattr(node, "lineno", self.lineno) if node is not None else self.lineno
        return UnsupportedConstructError(self.filename, lineno, what)

    def tick(self, node: ast.AST) -> None:
        self.steps += 1
        self.lineno = getattr(node, "lineno", self.lineno)
        if self.steps > MAX_STEPS:
            raise self.refuse(node, f"step budget exceeded ({MAX_STEPS} steps)")

    # ── trust checks ────────────────────────────────────────────────────────

    def is_own_object(self, obj: object) -> bool:
        """Return True for our mocks, classes built from upstream code, and their instances."""
        allowed = (*self.own_classes, *self.built_classes)
        if isinstance(obj, type):
            return issubclass(obj, allowed) if allowed else False
        return isinstance(obj, allowed) if allowed else False

    def check_callable(self, func: object, node: ast.AST) -> None:
        """Refuse a native call unless *func* is ours, interpreted, or allowlisted."""
        if isinstance(func, (InterpretedFunction, _BoundInterpreted, _TrustedNative)):
            return
        if id(func) in _SAFE_CALLABLE_IDS or id(func) in self.own_callable_ids:
            return
        if isinstance(func, type) and (self.is_own_object(func) or func in _ALLOWED_EXCEPTIONS):
            return
        if isinstance(func, types.MethodType):
            target = func.__self__
            if self.is_own_object(target):
                return
        if isinstance(func, types.BuiltinMethodType):
            target = func.__self__
            allowed = _METHOD_ALLOWLIST.get(type(target))
            if allowed is not None and func.__name__ in allowed:
                return
        if isinstance(func, _CheckedFormat):
            return
        raise self.refuse(node, f"call to {type(func).__name__} {getattr(func, '__name__', '')!r}")

    def get_attr(self, obj: object, attr: str, node: ast.AST) -> object:
        """Read ``obj.attr`` under the reader's rules (module docstring)."""
        if attr.startswith("__") and attr.endswith("__"):
            if attr == "__init__" and (isinstance(obj, super) or self.is_own_object(obj)):
                value = getattr(obj, attr)
                if isinstance(value, (InterpretedFunction, _BoundInterpreted)):
                    return value
                if isinstance(value, types.MethodType) and self.is_own_object(value.__self__):
                    return value
                return _TrustedNative(value)
            raise self.refuse(node, f"attribute {attr!r}")
        if attr == "mro":
            raise self.refuse(node, "attribute 'mro'")
        if isinstance(obj, ModuleStub):
            return obj.get(attr)
        if isinstance(obj, super) or self.is_own_object(obj):
            return getattr(obj, attr)
        allowed = _METHOD_ALLOWLIST.get(type(obj))
        if allowed is not None:
            if attr not in allowed:
                raise self.refuse(node, f"attribute {attr!r} of {type(obj).__name__}")
            value = getattr(obj, attr)
            if isinstance(obj, str) and attr == "format":
                return _CheckedFormat(obj, self, node)
            return value
        if isinstance(obj, BaseException) and attr == "args":
            return obj.args
        if obj is None:
            raise AttributeError(f"'NoneType' object has no attribute {attr!r}", name=attr)
        raise self.refuse(node, f"attribute {attr!r} of {type(obj).__name__}")

    def set_attr(self, obj: object, attr: str, value: object, node: ast.AST) -> None:
        if attr.startswith("__") and attr.endswith("__"):
            raise self.refuse(node, f"assignment to attribute {attr!r}")
        if not self.is_own_object(obj):
            raise self.refuse(node, f"assignment to an attribute of {type(obj).__name__}")
        setattr(obj, attr, value)

    # ── module entry ────────────────────────────────────────────────────────

    def run(self, tree: ast.Module) -> None:
        scope = _Scope("module", self.globals, None)
        self.exec_block(tree.body, scope)

    # ── statements ──────────────────────────────────────────────────────────

    def exec_block(self, body: list[ast.stmt], scope: _Scope) -> None:
        for stmt in body:
            self.exec_stmt(stmt, scope)

    def exec_stmt(self, node: ast.stmt, scope: _Scope) -> None:
        self.tick(node)
        if isinstance(node, ast.Expr):
            self.eval(node.value, scope)
        elif isinstance(node, ast.Assign):
            value = self.eval(node.value, scope)
            for target in node.targets:
                self.assign(target, value, scope)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.assign(node.target, self.eval(node.value, scope), scope)
        elif isinstance(node, ast.AugAssign):
            self.aug_assign(node, scope)
        elif isinstance(node, ast.If):
            branch = node.body if self.eval(node.test, scope) else node.orelse
            self.exec_block(branch, scope)
        elif isinstance(node, ast.For):
            self.exec_for(node, scope)
        elif isinstance(node, ast.While):
            self.exec_while(node, scope)
        elif isinstance(node, ast.Pass):
            pass
        elif isinstance(node, ast.Break):
            raise _Break
        elif isinstance(node, ast.Continue):
            raise _Continue
        elif isinstance(node, ast.Return):
            if scope.enclosing_function() is None:
                raise self.refuse(node, "'return' outside a function")
            raise _Return(None if node.value is None else self.eval(node.value, scope))
        elif isinstance(node, ast.FunctionDef):
            self.define_function(node, scope)
        elif isinstance(node, ast.ClassDef):
            self.define_class(node, scope)
        elif isinstance(node, ast.Raise):
            self.exec_raise(node, scope)
        elif isinstance(node, ast.Try):
            self.exec_try(node, scope)
        elif isinstance(node, ast.Assert):
            if not self.eval(node.test, scope):
                message = () if node.msg is None else (self.eval(node.msg, scope),)
                raise AssertionError(*message)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    raise self.refuse(node, "'del' of anything but a name")
                self.delete_name(target, scope)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            raise self.refuse(node, "an import statement")
        else:
            raise self.refuse(node, f"a {type(node).__name__} statement")

    def exec_for(self, node: ast.For, scope: _Scope) -> None:
        iterable = self.iterate(self.eval(node.iter, scope), node)
        broke = False
        for item in iterable:
            self.tick(node)
            self.assign(node.target, item, scope)
            try:
                self.exec_block(node.body, scope)
            except _Break:
                broke = True
                break
            except _Continue:
                continue
        if not broke:
            self.exec_block(node.orelse, scope)

    def exec_while(self, node: ast.While, scope: _Scope) -> None:
        broke = False
        while self.eval(node.test, scope):
            self.tick(node)
            try:
                self.exec_block(node.body, scope)
            except _Break:
                broke = True
                break
            except _Continue:
                continue
        if not broke:
            self.exec_block(node.orelse, scope)

    def exec_raise(self, node: ast.Raise, scope: _Scope) -> None:
        if node.exc is None:
            raise self.refuse(node, "a bare 'raise'")
        exc = self.eval(node.exc, scope)
        if isinstance(exc, type) and issubclass(exc, BaseException):
            if exc not in _ALLOWED_EXCEPTIONS:
                raise self.refuse(node, f"raising {exc.__name__}")
            exc = exc()
        if not isinstance(exc, _ALLOWED_EXCEPTIONS) or type(exc) not in _ALLOWED_EXCEPTIONS:
            raise self.refuse(node, f"raising {type(exc).__name__}")
        raise exc

    def exec_try(self, node: ast.Try, scope: _Scope) -> None:
        try:
            try:
                self.exec_block(node.body, scope)
            except Exception as exc:
                if isinstance(exc, (UnsupportedConstructError, _SizeError)):
                    raise
                for handler in node.handlers:
                    if self.handler_matches(handler, exc, scope):
                        if handler.name:
                            scope.names[handler.name] = exc
                        self.exec_block(handler.body, scope)
                        break
                else:
                    raise
            else:
                self.exec_block(node.orelse, scope)
        finally:
            self.exec_block(node.finalbody, scope)

    def handler_matches(self, handler: ast.ExceptHandler, exc: Exception, scope: _Scope) -> bool:
        if handler.type is None:
            return True
        kinds = self.eval(handler.type, scope)
        if not isinstance(kinds, tuple):
            kinds = (kinds,)
        for kind in kinds:
            if not (isinstance(kind, type) and kind in _ALLOWED_EXCEPTIONS):
                raise self.refuse(handler, f"an 'except' naming {kind!r}")
        return isinstance(exc, kinds)

    # ── assignment ──────────────────────────────────────────────────────────

    def assign(self, target: ast.expr, value: object, scope: _Scope) -> None:
        if isinstance(target, ast.Name):
            scope.names[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            self.assign_unpack(target, value, scope)
        elif isinstance(target, ast.Attribute):
            self.set_attr(self.eval(target.value, scope), target.attr, value, target)
        elif isinstance(target, ast.Subscript):
            container = self.eval(target.value, scope)
            key = self.eval(target.slice, scope)
            if not (isinstance(container, (list, dict)) or self.is_own_object(container)):
                raise self.refuse(target, f"item assignment on {type(container).__name__}")
            container[key] = value
        elif isinstance(target, ast.Starred):
            raise self.refuse(target, "a starred assignment target outside unpacking")
        else:
            raise self.refuse(target, f"assignment to a {type(target).__name__}")

    def assign_unpack(self, target: ast.Tuple | ast.List, value: object, scope: _Scope) -> None:
        items = list(self.iterate(value, target))
        starred = [i for i, elt in enumerate(target.elts) if isinstance(elt, ast.Starred)]
        if not starred:
            if len(items) != len(target.elts):
                raise ValueError(
                    f"cannot unpack {len(items)} values into {len(target.elts)} targets"
                )
            for elt, item in zip(target.elts, items, strict=True):
                self.assign(elt, item, scope)
            return
        star = starred[0]
        after = len(target.elts) - star - 1
        if len(items) < star + after:
            raise ValueError("not enough values to unpack")
        for elt, item in zip(target.elts[:star], items[:star], strict=True):
            self.assign(elt, item, scope)
        star_node = target.elts[star]
        assert isinstance(star_node, ast.Starred)
        self.assign(star_node.value, items[star : len(items) - after], scope)
        for elt, item in zip(target.elts[star + 1 :], items[len(items) - after :], strict=True):
            self.assign(elt, item, scope)

    def aug_assign(self, node: ast.AugAssign, scope: _Scope) -> None:
        op = _INPLACE.get(type(node.op))
        if op is None:
            raise self.refuse(node, f"the operator {type(node.op).__name__}")
        right = self.eval(node.value, scope)
        target = node.target
        if isinstance(target, ast.Name):
            current = self.lookup(target, scope)
            scope.names[target.id] = self.binop(op, current, right, node)
        elif isinstance(target, ast.Attribute):
            obj = self.eval(target.value, scope)
            current = self.get_attr(obj, target.attr, target)
            self.set_attr(obj, target.attr, self.binop(op, current, right, node), target)
        elif isinstance(target, ast.Subscript):
            container = self.eval(target.value, scope)
            key = self.eval(target.slice, scope)
            if not (isinstance(container, (list, dict)) or self.is_own_object(container)):
                raise self.refuse(target, f"item assignment on {type(container).__name__}")
            container[key] = self.binop(op, container[key], right, node)
        else:
            raise self.refuse(node, f"augmented assignment to a {type(target).__name__}")

    def delete_name(self, target: ast.Name, scope: _Scope) -> None:
        if target.id in scope.names:
            del scope.names[target.id]
        else:
            raise NameError(f"name {target.id!r} is not defined", name=target.id)

    # ── definitions ─────────────────────────────────────────────────────────

    def make_function(
        self, name: str, node: ast.FunctionDef | ast.Lambda, scope: _Scope
    ) -> InterpretedFunction:
        args = node.args
        defaults = [self.eval(d, scope) for d in args.defaults]
        kw_defaults = [_NO_DEFAULT if d is None else self.eval(d, scope) for d in args.kw_defaults]
        # A function nested in a class body closes over the class's *enclosing* scope.
        closure = scope
        while closure.kind == "class" and closure.parent is not None:
            closure = closure.parent
        body: list[ast.stmt] | ast.expr = node.body
        return InterpretedFunction(
            self, name, args, body, defaults, kw_defaults, closure, node.lineno
        )

    def define_function(self, node: ast.FunctionDef, scope: _Scope) -> None:
        decorators = [self.eval(d, scope) for d in node.decorator_list]
        value: object = self.make_function(node.name, node, scope)
        for decorator in reversed(decorators):
            self.check_callable(decorator, node)
            value = decorator(value)
        scope.names[node.name] = value

    def define_class(self, node: ast.ClassDef, scope: _Scope) -> None:
        if node.keywords:
            raise self.refuse(node, "class keywords (metaclass=...)")
        bases = tuple(self.eval(b, scope) for b in node.bases)
        for base in bases:
            if not (isinstance(base, type) and self.is_own_object(base)):
                raise self.refuse(node, f"a class base that is not ours: {base!r}")
        decorators = [self.eval(d, scope) for d in node.decorator_list]
        body = _Scope("class", {}, scope)
        self.exec_block(node.body, body)
        attrs: dict[str, object] = {}
        for key, value in body.names.items():
            if key.startswith("__") and key.endswith("__") and key != "__init__":
                continue  # never install upstream dunders: Python would call them natively
            attrs[key] = value
        attrs["__module__"] = "upstream"
        attrs["__qualname__"] = node.name
        cls = type(node.name, bases, attrs)
        self.built_classes.append(cls)
        for value in attrs.values():
            function = value.__func__ if isinstance(value, (classmethod, staticmethod)) else value
            if isinstance(function, InterpretedFunction):
                function.owner = cls
        result: object = cls
        for decorator in reversed(decorators):
            self.check_callable(decorator, node)
            result = decorator(result)
        scope.names[node.name] = result

    # ── calls ───────────────────────────────────────────────────────────────

    def call_function(
        self, function: InterpretedFunction, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> object:
        names = self.bind(function, args, kwargs)
        self_arg = args[0] if args else None
        scope = _Scope("function", names, function.closure, function, self_arg)
        body = function.body
        if isinstance(body, ast.expr):
            return self.eval(body, scope)
        try:
            self.exec_block(body, scope)
        except _Return as ret:
            return ret.value
        return None

    def bind(
        self, function: InterpretedFunction, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> dict[str, object]:
        spec = function.args
        positional = [a.arg for a in (*spec.posonlyargs, *spec.args)]
        keyword_ok = {a.arg for a in spec.args} | {a.arg for a in spec.kwonlyargs}
        names: dict[str, object] = {}
        for name, value in zip(positional, args, strict=False):
            names[name] = value
        extra = args[len(positional) :]
        if spec.vararg is not None:
            names[spec.vararg.arg] = tuple(extra)
        elif extra:
            raise TypeError(
                f"{function.name}() takes {len(positional)} positional arguments "
                f"but {len(args)} were given"
            )
        extra_kwargs: dict[str, object] = {}
        for key, value in kwargs.items():
            if key in keyword_ok:
                if key in names:
                    raise TypeError(f"{function.name}() got multiple values for argument {key!r}")
                names[key] = value
            elif spec.kwarg is not None:
                extra_kwargs[key] = value
            else:
                raise TypeError(f"{function.name}() got an unexpected keyword argument {key!r}")
        first_default = len(positional) - len(function.defaults)
        for index, name in enumerate(positional):
            if name not in names:
                if index >= first_default:
                    names[name] = function.defaults[index - first_default]
                else:
                    raise TypeError(f"{function.name}() missing required argument {name!r}")
        for arg, default in zip(spec.kwonlyargs, function.kw_defaults, strict=True):
            if arg.arg not in names:
                if default is _NO_DEFAULT:
                    raise TypeError(f"{function.name}() missing keyword argument {arg.arg!r}")
                names[arg.arg] = default
        if spec.kwarg is not None:
            names[spec.kwarg.arg] = extra_kwargs
        return names

    def eval_call(self, node: ast.Call, scope: _Scope) -> object:
        if isinstance(node.func, ast.Name) and node.func.id == "super" and not node.args:
            return self.eval_super(node, scope)
        func = self.eval(node.func, scope)
        args: list[object] = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                args.extend(self.iterate(self.eval(arg.value, scope), arg))
            else:
                args.append(self.eval(arg, scope))
        kwargs: dict[str, object] = {}
        for keyword in node.keywords:
            value = self.eval(keyword.value, scope)
            if keyword.arg is None:
                if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
                    raise self.refuse(node, "'**' of something other than a str-keyed dict")
                kwargs.update(value)
            else:
                kwargs[keyword.arg] = value
        self.check_callable(func, node)
        try:
            result = func(*args, **kwargs)
        except _SizeError as exc:
            raise self.refuse(node, f"size budget exceeded: {exc}") from None
        return self.sized(result, node)

    def eval_super(self, node: ast.Call, scope: _Scope) -> object:
        frame = scope.enclosing_function()
        if frame is None or frame.function is None or frame.function.owner is None:
            raise self.refuse(node, "super() outside a method")
        return super(frame.function.owner, frame.self_arg)

    # ── expressions ─────────────────────────────────────────────────────────

    def lookup(self, node: ast.Name, scope: _Scope) -> object:
        name = node.id
        for frame in scope.lookup_chain():
            if name in frame.names:
                return frame.names[name]
        if name in self.globals:
            return self.globals[name]
        if name in _SAFE_BUILTINS:
            return _SAFE_BUILTINS[name]
        raise NameError(f"name {name!r} is not defined", name=name)

    def eval(self, node: ast.expr, scope: _Scope) -> UpstreamValue:
        self.tick(node)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self.lookup(node, scope)
        if isinstance(node, ast.Attribute):
            return self.get_attr(self.eval(node.value, scope), node.attr, node)
        if isinstance(node, ast.Call):
            return self.eval_call(node, scope)
        if isinstance(node, ast.BinOp):
            op = _BINOPS.get(type(node.op))
            if op is None:
                raise self.refuse(node, f"the operator {type(node.op).__name__}")
            left = self.eval(node.left, scope)
            right = self.eval(node.right, scope)
            return self.binop(op, left, right, node)
        if isinstance(node, ast.UnaryOp):
            return _UNARYOPS[type(node.op)](self.eval(node.operand, scope))
        if isinstance(node, ast.BoolOp):
            return self.eval_boolop(node, scope)
        if isinstance(node, ast.Compare):
            return self.eval_compare(node, scope)
        if isinstance(node, ast.IfExp):
            return self.eval(node.body if self.eval(node.test, scope) else node.orelse, scope)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            items = self.eval_elements(node.elts, scope)
            if isinstance(node, ast.List):
                return items
            return tuple(items) if isinstance(node, ast.Tuple) else set(items)
        if isinstance(node, ast.Dict):
            return self.eval_dict(node, scope)
        if isinstance(node, ast.Subscript):
            container = self.eval(node.value, scope)
            key = self.eval(node.slice, scope)
            if not (
                isinstance(container, (str, bytes, list, tuple, dict, range))
                or self.is_own_object(container)
            ):
                raise self.refuse(node, f"subscript of {type(container).__name__}")
            return container[key]
        if isinstance(node, ast.Slice):
            return slice(
                None if node.lower is None else self.eval(node.lower, scope),
                None if node.upper is None else self.eval(node.upper, scope),
                None if node.step is None else self.eval(node.step, scope),
            )
        if isinstance(node, ast.JoinedStr):
            return self.eval_fstring(node, scope)
        if isinstance(node, ast.FormattedValue):
            return self.eval_formatted(node, scope)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            return self.eval_comprehension(node, scope)
        if isinstance(node, ast.Lambda):
            return self.make_function("<lambda>", node, scope)
        if isinstance(node, ast.NamedExpr):
            value = self.eval(node.value, scope)
            target_scope = scope
            while target_scope.kind == "comprehension" and target_scope.parent is not None:
                target_scope = target_scope.parent
            target_scope.names[node.target.id] = value
            return value
        raise self.refuse(node, f"a {type(node).__name__} expression")

    def binop(
        self,
        op: Callable[[Any, Any], Any],
        left: UpstreamValue,
        right: UpstreamValue,
        node: ast.AST,
    ) -> UpstreamValue:
        if op in (operator.mul, operator.imul):
            for seq, count in ((left, right), (right, left)):
                if isinstance(seq, (str, bytes, list, tuple)) and isinstance(count, int):
                    if len(seq) * max(count, 0) > MAX_SIZE:
                        raise self.refuse(node, "size budget exceeded: a repeated sequence")
        if (
            op in (operator.lshift, operator.ilshift)
            and isinstance(right, int)
            and right > MAX_EXPONENT
        ):
            raise self.refuse(node, f"a shift of {right}")
        try:
            return self.sized(op(left, right), node)
        except _SizeError as exc:
            raise self.refuse(node, f"size budget exceeded: {exc}") from None

    def sized(self, value: UpstreamValue, node: ast.AST) -> UpstreamValue:
        try:
            return _checked_size(value)
        except _SizeError as exc:
            raise self.refuse(node, f"size budget exceeded: {exc}") from None

    def eval_boolop(self, node: ast.BoolOp, scope: _Scope) -> UpstreamValue:
        is_and = isinstance(node.op, ast.And)
        value: Any = None
        for operand in node.values:
            value = self.eval(operand, scope)
            if is_and and not value:
                return value
            if not is_and and value:
                return value
        return value

    def eval_compare(self, node: ast.Compare, scope: _Scope) -> bool:
        left = self.eval(node.left, scope)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = self.eval(comparator, scope)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True

    def eval_elements(self, elts: list[ast.expr], scope: _Scope) -> list[Any]:
        items: list[Any] = []
        for elt in elts:
            if isinstance(elt, ast.Starred):
                items.extend(self.iterate(self.eval(elt.value, scope), elt))
            else:
                items.append(self.eval(elt, scope))
        self.sized(items, elts[0] if elts else ast.Pass())
        return items

    def eval_dict(self, node: ast.Dict, scope: _Scope) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                merged = self.eval(value, scope)
                if not isinstance(merged, dict):
                    raise self.refuse(node, "'**' of something other than a dict")
                result.update(merged)
            else:
                result[self.eval(key, scope)] = self.eval(value, scope)
        return result

    def eval_fstring(self, node: ast.JoinedStr, scope: _Scope) -> str:
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                parts.append(str(self.eval(value, scope)))
        return str(self.sized("".join(parts), node))

    def eval_formatted(self, node: ast.FormattedValue, scope: _Scope) -> str:
        value = self.eval(node.value, scope)
        if node.conversion == ord("r"):
            value = repr(value)
        elif node.conversion == ord("s"):
            value = str(value)
        elif node.conversion == ord("a"):
            value = ascii(value)
        spec = "" if node.format_spec is None else self.eval(node.format_spec, scope)
        return format(value, spec)

    def eval_comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp, scope: _Scope
    ) -> UpstreamValue:
        # The first iterable is evaluated in the enclosing scope; the rest, the conditions and
        # the element in the comprehension's own scope, which cannot see a class body.
        inner = _Scope("comprehension", {}, scope if scope.kind != "class" else scope.parent)
        results: list[Any] = []
        pairs: list[tuple[Any, Any]] = []

        def walk(index: int) -> None:
            generator = node.generators[index]
            source_scope = scope if index == 0 else inner
            for item in self.iterate(self.eval(generator.iter, source_scope), generator.iter):
                self.tick(generator.iter)
                self.assign(generator.target, item, inner)
                if all(self.eval(cond, inner) for cond in generator.ifs):
                    if index + 1 < len(node.generators):
                        walk(index + 1)
                    elif isinstance(node, ast.DictComp):
                        pairs.append((self.eval(node.key, inner), self.eval(node.value, inner)))
                    else:
                        results.append(self.eval(node.elt, inner))
                if len(results) + len(pairs) > MAX_SIZE:
                    raise self.refuse(node, "size budget exceeded: a comprehension")

        for generator in node.generators:
            if generator.is_async:
                raise self.refuse(node, "an async comprehension")
        walk(0)
        if isinstance(node, ast.DictComp):
            return dict(pairs)
        if isinstance(node, ast.SetComp):
            return set(results)
        return results  # a generator expression is evaluated eagerly; board files only consume it

    def iterate(self, value: object, node: ast.AST) -> Iterable[Any]:
        # Builtin iterables are safe to drive natively: upstream code cannot build a native
        # generator (nothing it writes is compiled), so these are lists, ranges, dict views and
        # the iterators of allowlisted builtins (map/filter/zip/enumerate/reversed/iter).
        if type(value).__module__ == "builtins" and isinstance(value, Iterable):
            return value
        if self.is_own_object(value):
            return cast(Iterable[Any], value)
        raise self.refuse(node, f"iteration over {type(value).__name__}")


class _CheckedFormat:
    """``str.format`` that refuses attribute and index fields (``{0.__class__}``, ``{0[k]}``)."""

    def __init__(self, template: str, reader: _Reader, node: ast.AST) -> None:
        self.template = template
        self.reader = reader
        self.node = node

    def __call__(self, *args: object, **kwargs: object) -> str:
        self.check(self.template)
        return self.template.format(*args, **kwargs)

    def check(self, template: str) -> None:
        for _literal, field, spec, _conversion in string.Formatter().parse(template):
            if field is not None and ("." in field or "[" in field):
                raise self.reader.refuse(self.node, f"a format field {field!r}")
            if spec:
                self.check(spec)


def read_module(source: str, filename: str, namespace: dict[str, Any]) -> dict[str, Any]:
    """Interpret *source* into *namespace* without executing it, and return the namespace.

    *namespace* is the parser's mock vocabulary; definitions from the file are added to it
    in the order the file makes them, as ``exec`` would.  Raises ``SyntaxError`` for a file
    that does not parse, :class:`UnsupportedConstructError` for one that needs anything outside
    the reader's rules, and whatever Python error the file's own code would raise (a
    ``NameError``, a ``TypeError`` from a mock, ...).
    """
    tree = ast.parse(source, filename)
    _Reader(filename, namespace).run(tree)
    return namespace
