from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="InfoItemRepSpecPublicUrlPatch")


@_attrs_define
class InfoItemRepSpecPublicUrlPatch:
    """Request body for PATCH /info-items/{id}/rep-spec-assignments/{assignment_id}.

    Writes the provider-native public URL back to an assignment row (active or
    deactivated). Called by Replicator after a successful replication job.

        Attributes:
            public_url (str): Provider-native public URL of the replicated artefact.
    """

    public_url: str

    def to_dict(self) -> dict[str, Any]:
        public_url = self.public_url

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "public_url": public_url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        public_url = d.pop("public_url")

        info_item_rep_spec_public_url_patch = cls(
            public_url=public_url,
        )

        return info_item_rep_spec_public_url_patch
