"""Concept definitions and the qualifier values each concept admits."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import resources

from pydantic import BaseModel, ConfigDict, model_validator

UNKNOWN = "unknown"
"""The qualifier value recording that a reviewer could not establish the fact."""


class FrozenModel(BaseModel):
    """An immutable catalogue record that rejects undeclared fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Qualifier(FrozenModel):
    """One dimension of a concept and the meanings of its admitted values."""

    definition: str
    values: dict[str, str]

    @model_validator(mode="after")
    def _unknown_is_reserved(self) -> Qualifier:
        if UNKNOWN in self.values:
            raise ValueError(f"qualifier value {UNKNOWN!r} is reserved")
        return self


class Concept(FrozenModel):
    """One meaning a consumer can ask for, with every qualifier it must be described by."""

    definition: str
    qualifiers: dict[str, Qualifier]

    def check_description(self, qualifiers: Mapping[str, str], /) -> None:
        """Require every qualifier, each with an admitted value or ``unknown``."""
        if set(qualifiers) != set(self.qualifiers):
            raise ValueError(
                f"qualifiers must be exactly {sorted(self.qualifiers)}, got {sorted(qualifiers)}"
            )
        for name, value in qualifiers.items():
            self._check_value(name, value)

    def check_predicate(self, qualifiers: Mapping[str, tuple[str, ...]], /) -> None:
        """Allow any subset of qualifiers, each accepting admitted values or ``unknown``."""
        for name, accepted in qualifiers.items():
            if not accepted:
                raise ValueError(f"qualifier {name!r} accepts no value")
            for value in accepted:
                self._check_value(name, value)

    def _check_value(self, name: str, value: str) -> None:
        qualifier = self.qualifiers.get(name)
        if qualifier is None:
            raise ValueError(f"unknown qualifier {name!r}; declared: {sorted(self.qualifiers)}")
        if value != UNKNOWN and value not in qualifier.values:
            raise ValueError(
                f"qualifier {name!r} does not admit {value!r}; admitted: {sorted(qualifier.values)}"
            )


class Vocabulary(FrozenModel):
    """The versioned set of concepts catalogue entries and requests may name."""

    vocabulary_version: str
    concepts: dict[str, Concept]

    def concept(self, name: str, /) -> Concept:
        """Return one concept, naming the declared ones when it is absent."""
        concept = self.concepts.get(name)
        if concept is None:
            raise ValueError(f"unknown concept {name!r}; declared: {sorted(self.concepts)}")
        return concept


def packaged_vocabulary() -> Vocabulary:
    """Load the vocabulary shipped with this package."""
    text = resources.files("apb_catalog").joinpath("data", "vocabulary.json").read_text("utf-8")
    return Vocabulary.model_validate_json(text)
