"""The self-contained resolution record stored under ``ParsedLevels.metadata["catalog"]``.

Readers implementing this contract need neither this package nor its catalogues: concept
definitions, entry meanings and every answer are embedded.
"""

from __future__ import annotations

from importlib import metadata, resources
from typing import Literal

from apb_catalog.resolver import ConceptRequest, LevelBinding, Resolution
from apb_catalog.source import CatalogueDescription, SourceEntry
from apb_catalog.vocabulary import Concept, FrozenModel

CONTRACT = "apb-catalog-resolution"
CONTRACT_VERSION = "0.3"
SCHEMA_FILE = f"{CONTRACT}-{CONTRACT_VERSION}.schema.json"


class Producer(FrozenModel):
    """The package and version that wrote a snapshot."""

    package: str
    version: str


def this_producer() -> Producer:
    """Return the installed ``apb-catalog`` as the producer."""
    return Producer(package="apb-catalog", version=metadata.version("apb-catalog"))


class ResolutionSnapshot(FrozenModel):
    """Level bindings, the retained entries they supply, and the answers to consumer requests."""

    contract: Literal["apb-catalog-resolution"] = CONTRACT
    contract_version: Literal["0.3"] = CONTRACT_VERSION
    producer: Producer
    catalogue: str
    description: CatalogueDescription
    vocabulary_version: str
    concepts: dict[str, Concept]
    levels: tuple[LevelBinding, ...]
    entries: tuple[SourceEntry, ...]
    resolutions: tuple[Resolution, ...]

    def resolution(self, request: ConceptRequest) -> Resolution:
        """Return the stored answer to one request."""
        for resolution in self.resolutions:
            if resolution.request == request:
                return resolution
        raise KeyError(f"the snapshot holds no answer to {request}")


def snapshot_json_schema() -> dict[str, object]:
    """Return the published JSON Schema of the snapshot contract."""
    return ResolutionSnapshot.model_json_schema()


def packaged_json_schema() -> str:
    """Return the JSON Schema file shipped with this package."""
    return resources.files("apb_catalog").joinpath("data", SCHEMA_FILE).read_text("utf-8")
