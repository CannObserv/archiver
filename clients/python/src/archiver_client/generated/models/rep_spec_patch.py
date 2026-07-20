from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.rep_spec_patch_document_type_0 import RepSpecPatchDocumentType0


T = TypeVar("T", bound="RepSpecPatch")


@_attrs_define
class RepSpecPatch:
    """Request body for PATCH /rep-specs/{rep_spec_id}.

    Both fields are optional; omitted fields are left untouched. ``provider`` is
    absent by design — it is frozen for the life of the RepSpec, and supplying a
    ``document`` whose ``provider`` differs from the stored one is a 422.

    ``document`` is a whole-document *replacement*, not a merge patch: merge
    semantics cannot express key removal, which would make ``object_options``
    entries unremovable under the envelope's ``additionalProperties: false``.

        Attributes:
            document (None | RepSpecPatchDocumentType0 | Unset): Replacement RepSpec envelope document. Accepted only while
                the RepSpec is a draft (zero assignment rows, active or deactivated); otherwise 409. Validated exactly as on
                create.
            name (None | str | Unset): New operator-friendly label. Editable regardless of assignment state.
    """

    document: None | RepSpecPatchDocumentType0 | Unset = UNSET
    name: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.rep_spec_patch_document_type_0 import RepSpecPatchDocumentType0

        document: dict[str, Any] | None | Unset
        if isinstance(self.document, Unset):
            document = UNSET
        elif isinstance(self.document, RepSpecPatchDocumentType0):
            document = self.document.to_dict()
        else:
            document = self.document

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if document is not UNSET:
            field_dict["document"] = document
        if name is not UNSET:
            field_dict["name"] = name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.rep_spec_patch_document_type_0 import RepSpecPatchDocumentType0

        d = dict(src_dict)

        def _parse_document(data: object) -> None | RepSpecPatchDocumentType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                document_type_0 = RepSpecPatchDocumentType0.from_dict(data)

                return document_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RepSpecPatchDocumentType0 | Unset, data)

        document = _parse_document(d.pop("document", UNSET))

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        rep_spec_patch = cls(
            document=document,
            name=name,
        )

        return rep_spec_patch
