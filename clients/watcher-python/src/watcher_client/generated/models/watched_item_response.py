from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.watch_health_status import WatchHealthStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.watched_item_response_default_schedule_config_type_0 import (
        WatchedItemResponseDefaultScheduleConfigType0,
    )
    from ..models.watched_item_response_source_specs_item import WatchedItemResponseSourceSpecsItem


T = TypeVar("T", bound="WatchedItemResponse")


@_attrs_define
class WatchedItemResponse:
    """Single WatchedItem record.

    ``archiver_info_item_id`` and ``archiver_info_source_id`` are always
    present — every WatchedItem is linked to an Archiver InfoItem (#251).

        Attributes:
            id (str):
            archiver_info_item_id (str):
            name (str):
            description (None | str):
            is_active (bool):
            archived_at (datetime.datetime | None):
            last_reviewed_at (datetime.datetime | None):
            last_checked_at (datetime.datetime | None):
            last_changed_at (datetime.datetime | None):
            health_status (WatchHealthStatus): Health state of a WatchedItem, updated after each check cycle.
            default_schedule_config (None | WatchedItemResponseDefaultScheduleConfigType0):
            content_media_type (None | str):
            default_tags (list[str] | None):
            effective_url (str):
            source_specs (list[WatchedItemResponseSourceSpecsItem]):
            archiver_info_source_id (str):
            created_at (datetime.datetime):
            updated_at (datetime.datetime):
            media_type_essence (None | str): The resolved extractor-dispatch essence — the same value the pipeline
                dispatches on (`resolve_dispatch_essence`): the observed/overridden
                ``content_media_type`` essence, with a URL-extension tiebreaker for
                mislabeled (octet-stream/text-plain/absent) headers. Computed, not stored
                (#168), so it always reflects the actual dispatch decision.
            domain_name (None | str | Unset):
            domain_suspended (bool | Unset):  Default: False.
    """

    id: str
    archiver_info_item_id: str
    name: str
    description: None | str
    is_active: bool
    archived_at: datetime.datetime | None
    last_reviewed_at: datetime.datetime | None
    last_checked_at: datetime.datetime | None
    last_changed_at: datetime.datetime | None
    health_status: WatchHealthStatus
    default_schedule_config: None | WatchedItemResponseDefaultScheduleConfigType0
    content_media_type: None | str
    default_tags: list[str] | None
    effective_url: str
    source_specs: list[WatchedItemResponseSourceSpecsItem]
    archiver_info_source_id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    media_type_essence: None | str
    domain_name: None | str | Unset = UNSET
    domain_suspended: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.watched_item_response_default_schedule_config_type_0 import (
            WatchedItemResponseDefaultScheduleConfigType0,
        )

        id = self.id

        archiver_info_item_id = self.archiver_info_item_id

        name = self.name

        description: None | str
        description = self.description

        is_active = self.is_active

        archived_at: None | str
        if isinstance(self.archived_at, datetime.datetime):
            archived_at = self.archived_at.isoformat()
        else:
            archived_at = self.archived_at

        last_reviewed_at: None | str
        if isinstance(self.last_reviewed_at, datetime.datetime):
            last_reviewed_at = self.last_reviewed_at.isoformat()
        else:
            last_reviewed_at = self.last_reviewed_at

        last_checked_at: None | str
        if isinstance(self.last_checked_at, datetime.datetime):
            last_checked_at = self.last_checked_at.isoformat()
        else:
            last_checked_at = self.last_checked_at

        last_changed_at: None | str
        if isinstance(self.last_changed_at, datetime.datetime):
            last_changed_at = self.last_changed_at.isoformat()
        else:
            last_changed_at = self.last_changed_at

        health_status = self.health_status.value

        default_schedule_config: dict[str, Any] | None
        if isinstance(self.default_schedule_config, WatchedItemResponseDefaultScheduleConfigType0):
            default_schedule_config = self.default_schedule_config.to_dict()
        else:
            default_schedule_config = self.default_schedule_config

        content_media_type: None | str
        content_media_type = self.content_media_type

        default_tags: list[str] | None
        if isinstance(self.default_tags, list):
            default_tags = self.default_tags

        else:
            default_tags = self.default_tags

        effective_url = self.effective_url

        source_specs = []
        for source_specs_item_data in self.source_specs:
            source_specs_item = source_specs_item_data.to_dict()
            source_specs.append(source_specs_item)

        archiver_info_source_id = self.archiver_info_source_id

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        media_type_essence: None | str
        media_type_essence = self.media_type_essence

        domain_name: None | str | Unset
        if isinstance(self.domain_name, Unset):
            domain_name = UNSET
        else:
            domain_name = self.domain_name

        domain_suspended = self.domain_suspended

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "archiver_info_item_id": archiver_info_item_id,
                "name": name,
                "description": description,
                "is_active": is_active,
                "archived_at": archived_at,
                "last_reviewed_at": last_reviewed_at,
                "last_checked_at": last_checked_at,
                "last_changed_at": last_changed_at,
                "health_status": health_status,
                "default_schedule_config": default_schedule_config,
                "content_media_type": content_media_type,
                "default_tags": default_tags,
                "effective_url": effective_url,
                "source_specs": source_specs,
                "archiver_info_source_id": archiver_info_source_id,
                "created_at": created_at,
                "updated_at": updated_at,
                "media_type_essence": media_type_essence,
            }
        )
        if domain_name is not UNSET:
            field_dict["domain_name"] = domain_name
        if domain_suspended is not UNSET:
            field_dict["domain_suspended"] = domain_suspended

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.watched_item_response_default_schedule_config_type_0 import (
            WatchedItemResponseDefaultScheduleConfigType0,
        )
        from ..models.watched_item_response_source_specs_item import (
            WatchedItemResponseSourceSpecsItem,
        )

        d = dict(src_dict)
        id = d.pop("id")

        archiver_info_item_id = d.pop("archiver_info_item_id")

        name = d.pop("name")

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        is_active = d.pop("is_active")

        def _parse_archived_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                archived_at_type_0 = datetime.datetime.fromisoformat(data)

                return archived_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        archived_at = _parse_archived_at(d.pop("archived_at"))

        def _parse_last_reviewed_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_reviewed_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_reviewed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_reviewed_at = _parse_last_reviewed_at(d.pop("last_reviewed_at"))

        def _parse_last_checked_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_checked_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_checked_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_checked_at = _parse_last_checked_at(d.pop("last_checked_at"))

        def _parse_last_changed_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_changed_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_changed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_changed_at = _parse_last_changed_at(d.pop("last_changed_at"))

        health_status = WatchHealthStatus(d.pop("health_status"))

        def _parse_default_schedule_config(
            data: object,
        ) -> None | WatchedItemResponseDefaultScheduleConfigType0:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                default_schedule_config_type_0 = (
                    WatchedItemResponseDefaultScheduleConfigType0.from_dict(data)
                )

                return default_schedule_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | WatchedItemResponseDefaultScheduleConfigType0, data)

        default_schedule_config = _parse_default_schedule_config(d.pop("default_schedule_config"))

        def _parse_content_media_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        content_media_type = _parse_content_media_type(d.pop("content_media_type"))

        def _parse_default_tags(data: object) -> list[str] | None:
            if data is None:
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                default_tags_type_0 = cast(list[str], data)

                return default_tags_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None, data)

        default_tags = _parse_default_tags(d.pop("default_tags"))

        effective_url = d.pop("effective_url")

        source_specs = []
        _source_specs = d.pop("source_specs")
        for source_specs_item_data in _source_specs:
            source_specs_item = WatchedItemResponseSourceSpecsItem.from_dict(source_specs_item_data)

            source_specs.append(source_specs_item)

        archiver_info_source_id = d.pop("archiver_info_source_id")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        def _parse_media_type_essence(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        media_type_essence = _parse_media_type_essence(d.pop("media_type_essence"))

        def _parse_domain_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        domain_name = _parse_domain_name(d.pop("domain_name", UNSET))

        domain_suspended = d.pop("domain_suspended", UNSET)

        watched_item_response = cls(
            id=id,
            archiver_info_item_id=archiver_info_item_id,
            name=name,
            description=description,
            is_active=is_active,
            archived_at=archived_at,
            last_reviewed_at=last_reviewed_at,
            last_checked_at=last_checked_at,
            last_changed_at=last_changed_at,
            health_status=health_status,
            default_schedule_config=default_schedule_config,
            content_media_type=content_media_type,
            default_tags=default_tags,
            effective_url=effective_url,
            source_specs=source_specs,
            archiver_info_source_id=archiver_info_source_id,
            created_at=created_at,
            updated_at=updated_at,
            media_type_essence=media_type_essence,
            domain_name=domain_name,
            domain_suspended=domain_suspended,
        )

        watched_item_response.additional_properties = d
        return watched_item_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
