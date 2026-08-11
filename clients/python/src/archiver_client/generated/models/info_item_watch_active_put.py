from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="InfoItemWatchActivePut")


@_attrs_define
class InfoItemWatchActivePut:
    """Request body for PUT /info-items/{id}/watch-active.

    ``active`` is required: NULL on the column means "the registry has no
    opinion yet", which is reachable only by never having written, never by an
    operator asserting it.

        Attributes:
            active (bool): True schedules the item; False is registered-but-paused (keep the item, stop scheduling).
                Distinct from removal, which is a deletion.
    """

    active: bool

    def to_dict(self) -> dict[str, Any]:
        active = self.active

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "active": active,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        active = d.pop("active")

        info_item_watch_active_put = cls(
            active=active,
        )

        return info_item_watch_active_put
