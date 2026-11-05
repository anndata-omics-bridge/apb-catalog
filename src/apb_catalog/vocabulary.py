"""Each catalogue set's vocabulary: its kinds, and the qualifiers that refine a kind."""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, model_validator

UNKNOWN = "unknown"
"""The kind or qualifier value recording that a reviewer could not establish the fact; every set
defines it as a kind and every qualifier as a value."""

VENDOR = "v"
"""The prefix that asks a level's own column, never a set: ``v:q_value``."""

PREFIX_PATTERN = r"[a-z][a-z0-9_]*"
"""What a set's prefix may be."""


class FrozenModel(BaseModel):
    """An immutable catalogue record that rejects undeclared fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Qualifier(FrozenModel):
    """One dimension of a set's meanings and the meanings of its admitted values, ``unknown``
    among them."""

    definition: str
    values: dict[str, str]

    @model_validator(mode="after")
    def _defines_unknown(self) -> Qualifier:
        if UNKNOWN not in self.values:
            raise ValueError(f"a qualifier defines the value {UNKNOWN!r}")
        return self


class SetVocabulary(FrozenModel):
    """What one set's entries mean: its kinds, and the qualifiers that refine a kind.

    An entry has one kind and a value for every qualifier; ``unknown`` is among the kinds and
    among every qualifier's values. ``prefix`` asks the set alone, as ``c:q_value``.
    """

    prefix: str
    definition: str
    kind_definition: str
    kinds: dict[str, str]
    qualifiers: dict[str, Qualifier]

    @model_validator(mode="after")
    def _kinds_apart(self) -> SetVocabulary:
        if re.fullmatch(PREFIX_PATTERN, self.prefix) is None:
            raise ValueError(f"the prefix {self.prefix!r} does not match {PREFIX_PATTERN}")
        if self.prefix == VENDOR:
            raise ValueError(f"the prefix {VENDOR!r} is reserved for the vendor's own column")
        if UNKNOWN not in self.kinds:
            raise ValueError(f"a set defines the kind {UNKNOWN!r}")
        if "kind" in self.qualifiers:
            raise ValueError("a set's kinds are no qualifier; they are its kinds")
        return self

    def check_description(self, kind: str, qualifiers: Mapping[str, str], /) -> None:
        """Require an admitted kind and every qualifier, each with an admitted value."""
        self.check_kind(kind)
        if set(qualifiers) != set(self.qualifiers):
            raise ValueError(
                f"qualifiers must be exactly {sorted(self.qualifiers)}, got {sorted(qualifiers)}"
            )
        for name, value in qualifiers.items():
            self._check_value(name, value)

    def check_predicate(
        self, kind: str | None, qualifiers: Mapping[str, tuple[str, ...]], /
    ) -> None:
        """Allow an admitted kind or none, and any subset of qualifiers, each accepting admitted
        values."""
        if kind is not None:
            self.check_kind(kind)
        for name, accepted in qualifiers.items():
            if not accepted:
                raise ValueError(f"qualifier {name!r} accepts no value")
            for value in accepted:
                self._check_value(name, value)

    def check_kind(self, kind: str, /) -> None:
        """Require one of the set's kinds."""
        if kind not in self.kinds:
            raise ValueError(
                f"the set does not admit the kind {kind!r}; kinds: {sorted(self.kinds)}"
            )

    def _check_value(self, name: str, value: str) -> None:
        qualifier = self.qualifiers.get(name)
        if qualifier is None:
            raise ValueError(f"unknown qualifier {name!r}; declared: {sorted(self.qualifiers)}")
        if value not in qualifier.values:
            raise ValueError(
                f"qualifier {name!r} does not admit {value!r}; admitted: {sorted(qualifier.values)}"
            )
