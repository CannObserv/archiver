from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.rep_spec_create_document import RepSpecCreateDocument


T = TypeVar("T", bound="RepSpecCreate")


@_attrs_define
class RepSpecCreate:
    """Request body for POST /rep-specs.

    ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
    accepting a client-supplied value would be ceremony. Bump the server
    default (and add a discriminator) once a v2 envelope ships.

        Attributes:
            document (RepSpecCreateDocument): RepSpec envelope document. Validated against rep_spec_schema/v1.json + the
                per-provider sub-schema at rep_spec_schema/providers/{provider}/v1.json.
            name (str): Operator-friendly label for this RepSpec. Not unique by design.
            provider (str): Provider key (e.g. 'gcs', 'gdrive', 'ia'). Validated via validate_rep_spec.
    """

    document: RepSpecCreateDocument
    name: str
    provider: str

    def to_dict(self) -> dict[str, Any]:
        document = self.document.to_dict()

        name = self.name

        provider = self.provider

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "document": document,
                "name": name,
                "provider": provider,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.rep_spec_create_document import RepSpecCreateDocument

        d = dict(src_dict)
        document = RepSpecCreateDocument.from_dict(d.pop("document"))

        name = d.pop("name")

        provider = d.pop("provider")

        rep_spec_create = cls(
            document=document,
            name=name,
            provider=provider,
        )

        return rep_spec_create
