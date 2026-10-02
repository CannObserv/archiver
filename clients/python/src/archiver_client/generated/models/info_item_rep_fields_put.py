from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.info_item_rep_fields_put_rep_fields import InfoItemRepFieldsPutRepFields


T = TypeVar("T", bound="InfoItemRepFieldsPut")


@_attrs_define
class InfoItemRepFieldsPut:
    """Request body for PUT /info-items/{id}/rep-fields (archiver#302).

    Replaces the whole bag; this is not a merge. The bag must be v1-shaped and
    keep every active assignment able to render. A valid bag that changes where
    an active assignment renders is refused with 409 unless
    ``allow_destination_change`` is true: later occasions would land at the new
    path, beside everything already published at the old one.

        Attributes:
            rep_fields (InfoItemRepFieldsPutRepFields): The whole rep_fields bag (Rep Fields v1: namespace → key → scalar),
                validated against the item's active assignments before it is stored.
            allow_destination_change (bool | Unset): Store the bag even though it changes the path an active assignment
                renders. Without it, such a bag is refused with 409. Default: False.
    """

    rep_fields: InfoItemRepFieldsPutRepFields
    allow_destination_change: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        rep_fields = self.rep_fields.to_dict()

        allow_destination_change = self.allow_destination_change

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "rep_fields": rep_fields,
            }
        )
        if allow_destination_change is not UNSET:
            field_dict["allow_destination_change"] = allow_destination_change

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_item_rep_fields_put_rep_fields import InfoItemRepFieldsPutRepFields

        d = dict(src_dict)
        rep_fields = InfoItemRepFieldsPutRepFields.from_dict(d.pop("rep_fields"))

        allow_destination_change = d.pop("allow_destination_change", UNSET)

        info_item_rep_fields_put = cls(
            rep_fields=rep_fields,
            allow_destination_change=allow_destination_change,
        )

        return info_item_rep_fields_put
