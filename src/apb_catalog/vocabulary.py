"""Each catalogue set's vocabulary: the qualifiers its entries are described by."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, model_validator

UNKNOWN = "unknown"
"""The qualifier value recording that a reviewer could not establish the fact; every qualifier
defines it."""


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
    """What one set's entries mean, with every qualifier they must be described by.

    Every set has a ``kind`` qualifier.
    """

    definition: str
    qualifiers: dict[str, Qualifier]

    @model_validator(mode="after")
    def _has_kind(self) -> SetVocabulary:
        if "kind" not in self.qualifiers:
            raise ValueError("a set vocabulary declares the qualifier 'kind'")
        return self

    def check_description(self, qualifiers: Mapping[str, str], /) -> None:
        """Require every qualifier, each with an admitted value."""
        if set(qualifiers) != set(self.qualifiers):
            raise ValueError(
                f"qualifiers must be exactly {sorted(self.qualifiers)}, got {sorted(qualifiers)}"
            )
        for name, value in qualifiers.items():
            self._check_value(name, value)

    def check_predicate(self, qualifiers: Mapping[str, tuple[str, ...]], /) -> None:
        """Allow any subset of qualifiers, each accepting admitted values."""
        for name, accepted in qualifiers.items():
            if not accepted:
                raise ValueError(f"qualifier {name!r} accepts no value")
            for value in accepted:
                self._check_value(name, value)

    def _check_value(self, name: str, value: str) -> None:
        qualifier = self.qualifiers.get(name)
        if qualifier is None:
            raise ValueError(f"unknown qualifier {name!r}; declared: {sorted(self.qualifiers)}")
        if value not in qualifier.values:
            raise ValueError(
                f"qualifier {name!r} does not admit {value!r}; admitted: {sorted(qualifier.values)}"
            )
