# Copyright (c) 2020 Nekokatt
# Copyright (c) 2021-present davfsa
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Implementation of parts of Python's [`enum`][] protocol to be more performant."""

from __future__ import annotations

__all__: typing.Sequence[str] = ("Enum", "Flag", "deprecated")

import functools
import operator
import sys
import types
import typing

from hikari.internal import typing_extensions

if typing.TYPE_CHECKING:
    from typing_extensions import Self

_T = typing.TypeVar("_T")
_MAX_CACHED_MEMBERS: typing.Final[int] = 1 << 12


class _DeprecatedAlias(typing.Generic[_T]):
    __slots__ = ("_alias", "_name", "_removal_version")

    def __init__(self, name: str, alias: str, removal_version: str) -> None:
        self._name = name
        self._alias = alias
        self._removal_version = removal_version

        # Import kept in-line due to circular import issues
        from hikari.internal import deprecation

        deprecation.check_if_past_removal(self._name, removal_version=removal_version)

    def __get__(self, instance: _T | None, owner_enum: _T) -> _T:
        # Import kept in-line due to circular import issues
        from hikari.internal import deprecation

        deprecation.warn_deprecated(
            self._name, removal_version=self._removal_version, additional_info=f"Use '{self._alias}' instead."
        )

        return owner_enum[self._alias]


class deprecated:  # noqa: N801 - Class should use CapWords
    """Used to denote that an enum member is a deprecated alias of another."""

    __slots__ = ("removal_version", "value")

    def __init__(self, value: object, /, *, removal_version: str) -> None:
        self.value = value
        self.removal_version = removal_version


class _EnumNamespace(dict[str, _T]):
    __slots__: typing.Sequence[str] = ("base", "names_to_values", "values_to_names")

    def __init__(self, base: type[typing.Any]) -> None:
        super().__init__()
        self.base = base
        self.names_to_values: dict[str, _T] = {}
        self.values_to_names: dict[_T, str] = {}
        self["__doc__"] = "An enumeration."

    def __getitem__(self, name: str) -> _T | object:
        try:
            return super().__getitem__(name)
        except KeyError:
            try:
                return self.names_to_values[name]
            except KeyError:
                raise KeyError(name) from None

    def __setitem__(self, name: str, value: _T) -> None:
        if name in {"", "mro"}:
            msg = f"Invalid enum member name: {name!r}"
            raise TypeError(msg)

        if isinstance(value, deprecated):
            real_value = value.value

            if (alias := self.values_to_names.get(real_value)) is None:
                msg = "[`deprecated`][] must be used on an existing value"
                raise ValueError(msg)

            member = _DeprecatedAlias(name, alias, value.removal_version)
            super().__setitem__(name, member)

            # Unpack for down below
            value = real_value

        elif name.startswith("_"):
            # Dunder/sunder, so skip.
            super().__setitem__(name, value)
            return

        elif hasattr(value, "__get__") or hasattr(value, "__set__") or hasattr(value, "__del__"):
            super().__setitem__(name, value)
            return

        elif not isinstance(value, self.base):
            msg = f"Expected member {name} to be of type {self.base.__name__} but was {type(value).__name__}"
            raise TypeError(msg)

        name = sys.intern(name)

        if issubclass(self.base, str):
            value = sys.intern(value)
        else:
            try:
                # This will fail if unhashable.
                hash(value)
            except TypeError:
                msg = f"Cannot have unhashable values in this enum type ({name}: {value!r})"
                raise TypeError(msg) from None

        if name in self.names_to_values:
            msg = f"Cannot define {name!r} name multiple times"
            raise TypeError(msg)

        self.names_to_values[name] = value
        self.values_to_names.setdefault(value, name)


# We refer to these from the metaclasses, but obviously this won't work
# until these classes are created, and since they use the metaclasses as
# a base metaclass, we have to give these values for _EnumMeta to not
# flake out when initializing them.
_Enum = NotImplemented


class _EnumMeta(type):
    def __call__(cls, value: object) -> Enum:
        """Cast a value to the enum, returning the raw value that was passed if value not found."""
        return cls._value_to_member_map_.get(value, value)

    def __getitem__(cls, name: str) -> Enum:
        if (member := getattr(cls, name, None)) is not None:
            return member

        raise KeyError(name)

    def __contains__(cls, item: object) -> bool:
        return item in cls._value_to_member_map_

    def __iter__(cls) -> typing.Iterator[Enum]:
        yield from cls._name_to_member_map_.values()

    def __new__(
        mcls: type[Self],
        cls_name: str,
        bases: tuple[type[typing.Any], ...],
        namespace: dict[str, typing.Any] | _EnumNamespace,
    ) -> Self:
        global _Enum

        if _Enum is NotImplemented:
            # noinspection PyRedundantParentheses
            return (_Enum := super().__new__(mcls, cls_name, bases, namespace))

        assert isinstance(namespace, _EnumNamespace)

        base, enum_type = bases

        new_namespace = {
            "__objtype__": base,
            "__enumtype__": enum_type,
            "_name_to_member_map_": (name_to_member := {}),
            "_value_to_member_map_": (value_to_member := {}),
            "_member_names_": (member_names := []),
            # Required to be immutable by enum API itself.
            "__members__": types.MappingProxyType(namespace.names_to_values),
            **{
                name: value
                for name, value in Enum.__dict__.items()
                if name not in {"__class__", "__module__", "__doc__"}
            },
        }

        # We don't want to override the __str__ behaviour inherited from str for string based enums.
        if issubclass(base, str):
            new_namespace.pop("__str__", None)

        # We update the name space to ensure new fields override inherited attributes and methods.
        new_namespace.update(namespace)

        cls = super().__new__(mcls, cls_name, bases, new_namespace)

        for name, value in namespace.names_to_values.items():
            if isinstance(new_namespace.get(name), _DeprecatedAlias):
                continue

            # Patching the member init call is around 100ns faster per call than
            # using the default type.__call__ which would make us do the lookup
            # in cls.__new__. Reason for this is that python will also always
            # invoke cls.__init__ if we do this, so we end up with two function
            # calls.
            member = cls.__new__(cls, value)
            member._name_ = name
            member._value_ = value
            setattr(cls, name, member)

            name_to_member[name] = member
            value_to_member[value] = member
            member_names.append(name)

        return cls

    @classmethod
    def __prepare__(cls, name: str, bases: tuple[type[typing.Any], ...] = ()) -> dict[str, typing.Any] | _EnumNamespace:
        if _Enum is NotImplemented:
            if name != "Enum":
                msg = "First instance of _EnumMeta must be Enum"
                raise TypeError(msg)
            return _EnumNamespace(object)

        try:
            # Fails if Enum is not defined. We check this in `__new__` properly.
            base, enum_type = bases

            if isinstance(base, _EnumMeta):
                msg = "First base to an enum must be the type to combine with, not _EnumMeta"
                raise TypeError(msg)

            return _EnumNamespace(base)
        except ValueError:
            msg = "Expected exactly two base classes for an enum"
            raise TypeError(msg) from None

    def __repr__(cls) -> str:
        return f"<enum {cls.__name__}>"

    __str__ = __repr__


class Enum(metaclass=_EnumMeta):
    """Clone of Python's [`enum.Enum`][] implementation.

    This is designed to be faster and more efficient than Python's
    implementation, while retaining the majority of the external interface
    that Python's [`enum.Enum`][] provides.

    An [`hikari.internal.enums.Enum`][] is a simple class containing a discrete set
    of constant values that can be used in place of this type. This acts as a
    type-safe way of representing a set number of "things".

    !!! warning
        Some semantics such as subtype checking and instance checking may
        differ. It is recommended to compare these values using the
        `==` operator rather than the `is` operator for safety reasons.

    Special Members on the class
    ----------------------------
    * `__enumtype__` :
        Always `Enum`.
    * `__members__` :
        An immutable [`typing.Mapping`][] that maps each member name to the member
        value.
    * `__objtype__` :
        Always the first type that the enum is derived from. For example:

    ```py
    >>> class UserType(str, Enum):
    ...     USER = "user"
    ...     PARTIAL = "partial"
    ...     MEMBER = "member"
    >>> print(UserType.__objtype__)
    <class 'str'>
    ```

    Operators on the class
    ----------------------
    * `EnumType["FOO"]` :
        Return the member that has the name `FOO`, raising a [`KeyError`][]
        if it is not present.
    * `EnumType.FOO` :
        Return the member that has the name `FOO`, raising a
        [`AttributeError`][] if it is not present.
    * `EnumType(x)` :
        Attempt to cast `x` to the enum type by finding an existing member that
        has the same __value__. If this fails, you should expect a
        [`ValueError`][] to be raised.

    Operators on each enum member
    -----------------------------
    * `e1 == e2` : [`bool`][]
        Compare equality.
    * `e1 != e2` : [`bool`][]
        Compare inequality.
    * `repr(e)` : [`str`][]
        Get the machine readable representation of the enum member `e`.
    * `str(e)` : [`str`][]
        Get the [`str`][] name of the enum member `e`.

    Special properties on each enum member
    --------------------------------------
    * `name` : [`str`][]
        The name of the member.
    * `value` :
        The value of the member. The type depends on the implementation type
        of the enum you are using.

    All other methods and operators on enum members are inherited from the
    member's __value__. For example, an enum extending [`int`][] would
    be able to be used as an [`int`][] type outside these overridden definitions.
    """

    _name_to_member_map_: typing.ClassVar[typing.Mapping[str, Enum]]
    _value_to_member_map_: typing.ClassVar[typing.Mapping[int, Enum]]
    _member_names_: typing.ClassVar[typing.Sequence[str]]
    __members__: typing.ClassVar[typing.Mapping[str, Enum]]
    __objtype__: typing.ClassVar[type[typing.Any]]
    __enumtype__: typing.ClassVar[type[Enum]]
    _name_: str
    _value_: typing.Any

    @property
    def name(self) -> str:
        """Return the name of the enum member as a [`str`][]."""
        return self._name_

    @property
    def value(self) -> object:
        """Return the value of the enum member."""
        return self._value_

    @typing_extensions.override
    def __repr__(self) -> str:
        return f"<{type(self).__name__}.{self._name_}: {self._value_!r}>"

    @typing_extensions.override
    def __str__(self) -> str:
        return self._name_


_Flag = NotImplemented


def _name_resolver(members: dict[int, _Flag], value: int) -> typing.Generator[str, typing.Any, None]:
    bit = 1
    has_yielded = False
    remaining = value
    while bit <= value:
        # Use ._value_ to prevent overhead of making new members each time.
        # Also let's my testing logic for the cache size be more accurate.
        member = members.get(bit)
        if member and member._value_ & remaining == member._value_:
            remaining ^= member._value_
            yield member.name
            has_yielded = True
        bit <<= 1

    if not has_yielded:
        yield f"UNKNOWN 0x{value:x}"
    elif remaining:
        yield hex(remaining)


class _FlagMeta(type):
    def __call__(cls, value: int = 0) -> Flag:
        """Cast a value to the flag enum, returning the raw value that was passed if values not found."""
        # We want to handle value invariantly to avoid issues brought in by different behaviours from sub-classed ints
        # and floats. This also ensures that .__int__ only returns an invariant int.
        value = int(value)
        try:
            return cls._value_to_member_map_[value]
        except KeyError:
            # We only need this ability here usually, so overloading operators
            # is an overkill and would add more overhead.

            if value < 0:
                # Convert to a positive value instead.
                return cls.__everything__ - ~value

            temp_members = cls._temp_members_
            # For huge enums, don't ever cache anything. We could consume masses of memory otherwise
            # (for example: Permissions)
            try:
                # Try to get a cached value.
                return temp_members[value]
            except KeyError:
                # If we can't find the value, just return what got casted in by generating a pseudomember
                # and caching it. We can't use weakref because int is not weak referenceable, annoyingly.
                pseudomember = cls.__new__(cls, value)
                pseudomember._name_ = None
                pseudomember._value_ = value
                temp_members[value] = pseudomember
                if len(temp_members) > _MAX_CACHED_MEMBERS:
                    temp_members.popitem()

                return pseudomember

    def __getitem__(cls, name: str) -> Flag:
        if (member := getattr(cls, name, None)) is not None:
            return member

        raise KeyError(name)

    def __iter__(cls) -> typing.Iterator[typing.Any]:
        yield from cls._name_to_member_map_.values()

    @classmethod
    def __prepare__(cls, name: str, bases: tuple[type[typing.Any], ...] = ()) -> dict[str, typing.Any] | _EnumNamespace:
        if _Flag is NotImplemented:
            if name != "Flag":
                msg = "First instance of _FlagMeta must be Flag"
                raise TypeError(msg)
            return _EnumNamespace(object)

        # Fails if Flag is not defined.
        if len(bases) == 1 and bases[0] == Flag:
            return _EnumNamespace(int)
        msg = "Cannot define another Flag base type"
        raise TypeError(msg)

    @staticmethod
    def __new__(
        mcls: type[Flag],
        cls_name: str,
        bases: tuple[type[typing.Any], ...],
        namespace: dict[str, typing.Any] | _EnumNamespace,
    ) -> Flag:
        global _Flag

        if _Flag is NotImplemented:
            # noinspection PyRedundantParentheses
            return (_Flag := super().__new__(mcls, cls_name, bases, namespace))

        assert isinstance(namespace, _EnumNamespace)
        new_namespace = {
            "__objtype__": int,
            "__enumtype__": _Flag,
            "_name_to_member_map_": (name_to_member := {}),
            "_value_to_member_map_": (value_to_member := {}),
            "_powers_of_2_to_member_map_": (powers_of_2_map := {}),
            # We can't weakref, as we inherit from int. Turns out that is significantly
            # slower anyway, so it isn't important for now. We just manually limit
            # the cache size.
            # This also randomly ends up with a 0 value in it at the start
            # during the next for loop. I cannot work out for the life of me
            # why this happens.
            "_temp_members_": {},
            "_member_names_": (member_names := []),
            # Required to be immutable by enum API itself.
            "__members__": types.MappingProxyType(namespace.names_to_values),
            # This copies over all methods, including operator overloads. This
            # has the effect of making pdoc aware of any methods or properties
            # we defined on Flag.
            **{
                name: value
                for name, value in Flag.__dict__.items()
                if name not in {"__class__", "__module__", "__doc__"}
            },
        }
        # We update the namespace to ensure new fields override inherited attributes and methods.
        new_namespace.update(namespace)

        cls = super().__new__(mcls, cls_name, (int, *bases), new_namespace)

        for name, value in namespace.names_to_values.items():
            if isinstance(new_namespace.get(name), _DeprecatedAlias):
                continue

            # Patching the member init call is around 100ns faster per call than
            # using the default type.__call__ which would make us do the lookup
            # in cls.__new__. Reason for this is that python will also always
            # invoke cls.__init__ if we do this, so we end up with two function
            # calls.
            member = cls.__new__(cls, value)
            member._name_ = name
            member._value_ = value
            setattr(cls, name, member)

            name_to_member[name] = member
            value_to_member[value] = member
            member_names.append(name)

            if not (value & value - 1):
                powers_of_2_map[value] = member

        all_bits = functools.reduce(operator.or_, value_to_member.keys())
        all_bits_member = cls.__new__(cls, all_bits)
        all_bits_member._name_ = None
        all_bits_member._value_ = all_bits
        cls.__everything__ = all_bits_member

        return cls

    def __repr__(cls) -> str:
        return f"<enum {cls.__name__}>"

    __str__ = __repr__


class Flag(metaclass=_FlagMeta):
    """Clone of Python's [`enum.Flag`][] implementation.

    This is designed to be faster and more efficient than Python's
    implementation, while retaining the majority of the external interface
    that Python's [`enum.Flag`][] provides.

    In simple terms, a flag is a set of wrapped constant [`int`][]
    values that can be combined in any combination to make a special value.
    This is a more efficient way of combining things like permissions together
    into a single integral value, and works by setting the individual `1` and `0`
    on the binary representation of the integer.

    This implementation has extra features, in that it will actively behave
    like a [`set`][] as well.

    !!! warning
        It is important to keep in mind that some semantics such as subtype
        checking and instance checking may differ. It is recommended to compare
        these values using the `==` operator rather than the `is` operator for
        safety reasons.

        Especially where pseudo-members created from combinations are cached,
        results of using of `is` may not be deterministic. This is a side
        effect of some internal performance improvements.

        Failing to observe this __will__ result in unexpected behaviour
        occurring in your application!

        Also important to note is that despite wrapping [`int`][] values,
        conceptually this does not behave as if it were a subclass of [`int`][].

    Special Members on the class
    ----------------------------
    * `__enumtype__` :
        Always [`Flag`][].
    * `__everything__` :
        A special member with all documented bits set.
    * `__members__` :
        An immutable [`typing.Mapping`][] that maps each member name to the member
        value.
    * `__objtype__` :
        Always [`int`][].

    Operators on the class
    ----------------------
    * `FlagType["FOO"]` :
        Return the member that has the name `FOO`, raising a [`KeyError`][]
        if it is not present.
    * `FlagType.FOO` :
        Return the member that has the name `FOO`, raising a
        [`AttributeError`][] if it is not present.
    * `FlagType(x)` :
        Attempt to cast `x` to the enum type by finding an existing member that
        has the same __value__. If this fails, then a special __composite__
        instance of the type is made. The name of this type is a combination of
        all members that combine to make the bitwise value.

    Operators on each flag member
    -----------------------------
    * `e1 & e2` :
        Bitwise `AND` operation. Will return a member that contains all flags
        that are common between both operands on the values. This also works with
        one of the operands being an [`int`][]eger. You may instead use
        the `intersection` method.
    * `e1 | e2` :
        Bitwise `OR` operation. Will return a member that contains all flags
        that appear on at least one of the operands. This also works with
        one of the operands being an [`int`][]eger. You may instead use
        the `union` method.
    * `e1 ^ e2` :
        Bitwise `XOR` operation. Will return a member that contains all flags
        that only appear on at least one and at most one of the operands.
        This also works with one of the operands being an [`int`][].
        You may instead use the `symmetric_difference` method.
    * `~e` :
        Return the inverse of this value. This is equivalent to disabling all
        flags that are set on this value and enabling all flags that are
        not set on this value. Note that this will behave slightly differently
        to inverting a pure int value. You may instead use the `invert` method.
    * `e1 - e2` :
        Bitwise set difference operation. Returns all flags set on `e1` that are
        not set on `e2` as well. You may instead use the `difference`
        method.
    * `bool(e)` : [`bool`][]
        Return [`True`][] if `e` has a non-zero value, otherwise
        [`False`][].
    * `E.A in e`: [`bool`][]
        [`True`][] if `E.A` is in `e`. This is functionally equivalent
        to `E.A & e == E.A`.
    * `iter(e)` :
        Explode the value into a iterator of each __documented__ flag that can
        be combined to make up the value `e`. Returns an iterator across all
        well-defined flags that make up this value. This will only include the
        flags explicitly defined on this `Flag` type and that are individual
        powers of two (this means if converted to twos-compliment binary,
        exactly one bit must be a `1`). In simple terms, this means that you
        should not expect combination flags to be returned.
    * `e1 == e2` : [`bool`][]
        Compare equality.
    * `e1 != e2` : [`bool`][]
        Compare inequality.
    * `e1 < e2` : [`bool`][]
        Compare by ordering.
    * `int(e)` : [`int`][]
        Get the integer value of this flag
    * `repr(e)` : [`str`][]
        Get the machine readable representation of the flag member `e`.
    * `str(e)` : [`str`][]
        Get the [`str`][] name of the flag member `e`.

    Special properties on each flag member
    --------------------------------------
    * `e.name` : [`str`][]
        The name of the member. For composite members, this will be generated.
    * `e.value` : [`int`][]
        The value of the member.

    Special members on each flag member
    -----------------------------------
    * `e.all(E.A, E.B, E.C, ...)` : [`bool`][]
        Returns [`True`][] if __all__ of `E.A`, `E.B`, `E.C`, et cetera
        make up the value of `e`.
    * `e.any(E.A, E.B, E.C, ...)` : [`bool`][]
        Returns [`True`][] if __any__ of `E.A`, `E.B`, `E.C`, et cetera
        make up the value of `e`.
    * `e.none(E.A, E.B, E.C, ...)` : [`bool`][]
        Returns [`True`][] if __none__ of `E.A`, `E.B`, `E.C`, et cetera
        make up the value of `e`.
    * `e.split()` : [`typing.Sequence`][]
        Explode the value into a sequence of each __documented__ flag that can
        be combined to make up the value `e`. Returns a sorted sequence of each
        power-of-two flag that makes up the value `e`. This is equivalent to
        `list(iter(e))`.

    All other methods and operators on `Flag` members are inherited from the
    member's __value__.

    !!! note
        Due to limitations around how this is re-implemented, this class is not
        considered a subclass of `Enum` at runtime, even if MyPy believes this
        is possible
    """

    _name_to_member_map_: typing.ClassVar[typing.Mapping[str, Flag]]
    _value_to_member_map_: typing.ClassVar[typing.Mapping[int, Flag]]
    _powers_of_2_to_member_map_: typing.ClassVar[typing.Mapping[int, Flag]]
    _temp_members_: typing.ClassVar[typing.Mapping[int, Flag]]
    _member_names_: typing.ClassVar[typing.Sequence[str]]
    __members__: typing.ClassVar[typing.Mapping[str, Flag]]
    __objtype__: typing.ClassVar[type[int]]
    __enumtype__: typing.ClassVar[type[Flag]]
    _name_: str | None
    _value_: int

    @property
    def name(self) -> str:
        """Return the name of the flag combination as a [`str`][]."""
        if self._name_ is None:
            self._name_ = "|".join(_name_resolver(self._value_to_member_map_, self._value_))
        return self._name_

    @property
    def value(self) -> int:
        """Return the [`int`][] value of the flag."""
        return self._value_

    def all(self, *flags: Self) -> bool:
        """Check if all of the given flags are part of this value.

        Returns
        -------
        bool
            [`True`][] if any of the given flags are part of this value.
            Otherwise, return [`False`][].
        """
        return all((flag & self) == flag for flag in flags)

    def any(self, *flags: Self) -> bool:
        """Check if any of the given flags are part of this value.

        Returns
        -------
        bool
            [`True`][] if any of the given flags are part of this value.
            Otherwise, return [`False`][].
        """
        return any((flag & self) == flag for flag in flags)

    def difference(self, other: Self | int) -> _T:
        """Perform a set difference with the other set.

        This will return all flags in this set that are not in the other value.

        Equivalent to using the subtraction `-` operator.
        """
        return self.__class__(self & ~int(other))

    def intersection(self, other: Self | int) -> _T:
        """Return a combination of flags that are set for both given values.

        Equivalent to using the "AND" `&` operator.
        """
        return self.__class__(self._value_ & int(other))

    def invert(self) -> Self:
        """Return a set of all flags not in the current set."""
        return self.__class__(self.__class__.__everything__._value_ & ~self._value_)

    def is_disjoint(self, other: Self | int) -> bool:
        """Return whether two sets have a intersection or not.

        If the two sets have an intersection, then this returns
        [`False`][]. If no common flag values exist between them, then
        this returns [`True`][].
        """
        return not (self & other)

    def is_subset(self, other: Self | int) -> bool:
        """Return whether another set contains this set or not.

        Equivalent to using the "in" operator.
        """
        return (self & other) == other

    def is_superset(self, other: Self | int) -> bool:
        """Return whether this set contains another set or not."""
        return (self & other) == self

    def none(self, *flags: Self) -> bool:
        """Check if none of the given flags are part of this value.

        !!! note
            This is essentially the opposite of [`hikari.internal.enums.Flag.any`][].

        Returns
        -------
        bool
            [`True`][] if none of the given flags are part of this value.
            Otherwise, return [`False`][].
        """
        return not self.any(*flags)

    def split(self) -> typing.Sequence[Self]:
        """Return a list of all defined atomic values for this flag.

        Any unrecognised bits will be omitted for brevity.

        The result will be a name-sorted [`typing.Sequence`][] of each member
        """
        return sorted(
            (member for member in self.__class__._powers_of_2_to_member_map_.values() if member.value & self),
            # Assumption: powers of 2 already have a cached value.
            key=lambda m: m._name_,
        )

    def symmetric_difference(self, other: _T | int) -> Self:
        """Return a set with the symmetric differences of two flag sets.

        Equivalent to using the "XOR" `^` operator.

        For `a ^ b`, this can be considered the same as `(a - b) | (b - a)`.
        """
        return self.__class__(self._value_ ^ int(other))

    def union(self, other: _T | int) -> Self:
        """Return a combination of all flags in this set and the other set.

        Equivalent to using the "OR" `~` operator.
        """
        return self.__class__(self._value_ | int(other))

    isdisjoint = is_disjoint
    issubset = is_subset
    issuperset = is_superset
    # Exists since Python's `set` type is inconsistent with naming, so this
    # will prevent tripping people up unnecessarily because we do not
    # name inconsistently.

    # This one isn't in Python's set, but the inconsistency is triggering my OCD
    # so this is being defined anyway.
    symmetricdifference = symmetric_difference

    def __bool__(self) -> bool:
        return bool(self._value_)

    def __int__(self) -> int:
        return self._value_

    def __iter__(self) -> typing.Iterator[Self]:
        return iter(self.split())

    def __len__(self) -> int:
        return len(self.split())

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}.{self.name}: {self.value!r}>"

    def __rsub__(self, other: int | _T) -> Self:
        # This logic has to be reversed to be correct, since order matters for
        # a subtraction operator. This also ensures `int - _T -> _T` is a valid
        # case for us.
        return self.__class__(other) - self

    @typing_extensions.override
    def __str__(self) -> str:
        return self.name

    __contains__ = is_subset
    __rand__ = __and__ = intersection
    __ror__ = __or__ = union
    __sub__ = difference
    __rxor__ = __xor__ = symmetric_difference
    __invert__ = invert
