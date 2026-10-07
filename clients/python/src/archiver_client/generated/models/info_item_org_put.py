from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="InfoItemOrgPut")


@_attrs_define
class InfoItemOrgPut:
    """Request body for PUT /info-items/{id}/org (archiver#304).

    ``pm_org_id`` is required, ``null`` included: unlinking is said, never
    implied by an omitted field.

        Attributes:
            pm_org_id (None | str): The Power Map org to link, fetched from Power Map now; null unlinks. A merged id links
                the org it was merged into.
            allow_destination_change (bool | Unset): Store the link even though it changes the path an active assignment
                renders. Without it, such a link is refused with 409, exactly as PUT /rep-fields refuses a moving bag. Default:
                False.
    """

    pm_org_id: None | str
    allow_destination_change: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        pm_org_id: None | str
        pm_org_id = self.pm_org_id

        allow_destination_change = self.allow_destination_change

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "pm_org_id": pm_org_id,
            }
        )
        if allow_destination_change is not UNSET:
            field_dict["allow_destination_change"] = allow_destination_change

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_pm_org_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        pm_org_id = _parse_pm_org_id(d.pop("pm_org_id"))

        allow_destination_change = d.pop("allow_destination_change", UNSET)

        info_item_org_put = cls(
            pm_org_id=pm_org_id,
            allow_destination_change=allow_destination_change,
        )

        return info_item_org_put
