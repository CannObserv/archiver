from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.watched_item_patch_default_schedule_config_type_0 import (
        WatchedItemPatchDefaultScheduleConfigType0,
    )
    from ..models.watched_item_patch_source_specs_type_0_item import (
        WatchedItemPatchSourceSpecsType0Item,
    )


T = TypeVar("T", bound="WatchedItemPatch")


@_attrs_define
class WatchedItemPatch:
    """Partial update to a WatchedItem. All fields optional.

    ``effective_url`` is set directly without re-probing — Archiver is the
    authoritative source for URL succession.

        Attributes:
            name (None | str | Unset):
            description (None | str | Unset):
            is_active (bool | None | Unset):
            default_schedule_config (None | Unset | WatchedItemPatchDefaultScheduleConfigType0):
            default_content_type (None | str | Unset):
            default_tags (list[str] | None | Unset):
            effective_url (None | str | Unset):
            source_specs (list[WatchedItemPatchSourceSpecsType0Item] | None | Unset):
            archiver_info_source_id (None | str | Unset):
    """

    name: None | str | Unset = UNSET
    description: None | str | Unset = UNSET
    is_active: bool | None | Unset = UNSET
    default_schedule_config: None | Unset | WatchedItemPatchDefaultScheduleConfigType0 = UNSET
    default_content_type: None | str | Unset = UNSET
    default_tags: list[str] | None | Unset = UNSET
    effective_url: None | str | Unset = UNSET
    source_specs: list[WatchedItemPatchSourceSpecsType0Item] | None | Unset = UNSET
    archiver_info_source_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.watched_item_patch_default_schedule_config_type_0 import (
            WatchedItemPatchDefaultScheduleConfigType0,
        )

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        is_active: bool | None | Unset
        if isinstance(self.is_active, Unset):
            is_active = UNSET
        else:
            is_active = self.is_active

        default_schedule_config: dict[str, Any] | None | Unset
        if isinstance(self.default_schedule_config, Unset):
            default_schedule_config = UNSET
        elif isinstance(self.default_schedule_config, WatchedItemPatchDefaultScheduleConfigType0):
            default_schedule_config = self.default_schedule_config.to_dict()
        else:
            default_schedule_config = self.default_schedule_config

        default_content_type: None | str | Unset
        if isinstance(self.default_content_type, Unset):
            default_content_type = UNSET
        else:
            default_content_type = self.default_content_type

        default_tags: list[str] | None | Unset
        if isinstance(self.default_tags, Unset):
            default_tags = UNSET
        elif isinstance(self.default_tags, list):
            default_tags = self.default_tags

        else:
            default_tags = self.default_tags

        effective_url: None | str | Unset
        if isinstance(self.effective_url, Unset):
            effective_url = UNSET
        else:
            effective_url = self.effective_url

        source_specs: list[dict[str, Any]] | None | Unset
        if isinstance(self.source_specs, Unset):
            source_specs = UNSET
        elif isinstance(self.source_specs, list):
            source_specs = []
            for source_specs_type_0_item_data in self.source_specs:
                source_specs_type_0_item = source_specs_type_0_item_data.to_dict()
                source_specs.append(source_specs_type_0_item)

        else:
            source_specs = self.source_specs

        archiver_info_source_id: None | str | Unset
        if isinstance(self.archiver_info_source_id, Unset):
            archiver_info_source_id = UNSET
        else:
            archiver_info_source_id = self.archiver_info_source_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if name is not UNSET:
            field_dict["name"] = name
        if description is not UNSET:
            field_dict["description"] = description
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if default_schedule_config is not UNSET:
            field_dict["default_schedule_config"] = default_schedule_config
        if default_content_type is not UNSET:
            field_dict["default_content_type"] = default_content_type
        if default_tags is not UNSET:
            field_dict["default_tags"] = default_tags
        if effective_url is not UNSET:
            field_dict["effective_url"] = effective_url
        if source_specs is not UNSET:
            field_dict["source_specs"] = source_specs
        if archiver_info_source_id is not UNSET:
            field_dict["archiver_info_source_id"] = archiver_info_source_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.watched_item_patch_default_schedule_config_type_0 import (
            WatchedItemPatchDefaultScheduleConfigType0,
        )
        from ..models.watched_item_patch_source_specs_type_0_item import (
            WatchedItemPatchSourceSpecsType0Item,
        )

        d = dict(src_dict)

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_is_active(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_active = _parse_is_active(d.pop("is_active", UNSET))

        def _parse_default_schedule_config(
            data: object,
        ) -> None | Unset | WatchedItemPatchDefaultScheduleConfigType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                default_schedule_config_type_0 = (
                    WatchedItemPatchDefaultScheduleConfigType0.from_dict(data)
                )

                return default_schedule_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | WatchedItemPatchDefaultScheduleConfigType0, data)

        default_schedule_config = _parse_default_schedule_config(
            d.pop("default_schedule_config", UNSET)
        )

        def _parse_default_content_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        default_content_type = _parse_default_content_type(d.pop("default_content_type", UNSET))

        def _parse_default_tags(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                default_tags_type_0 = cast(list[str], data)

                return default_tags_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        default_tags = _parse_default_tags(d.pop("default_tags", UNSET))

        def _parse_effective_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        effective_url = _parse_effective_url(d.pop("effective_url", UNSET))

        def _parse_source_specs(
            data: object,
        ) -> list[WatchedItemPatchSourceSpecsType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                source_specs_type_0 = []
                _source_specs_type_0 = data
                for source_specs_type_0_item_data in _source_specs_type_0:
                    source_specs_type_0_item = WatchedItemPatchSourceSpecsType0Item.from_dict(
                        source_specs_type_0_item_data
                    )

                    source_specs_type_0.append(source_specs_type_0_item)

                return source_specs_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[WatchedItemPatchSourceSpecsType0Item] | None | Unset, data)

        source_specs = _parse_source_specs(d.pop("source_specs", UNSET))

        def _parse_archiver_info_source_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        archiver_info_source_id = _parse_archiver_info_source_id(
            d.pop("archiver_info_source_id", UNSET)
        )

        watched_item_patch = cls(
            name=name,
            description=description,
            is_active=is_active,
            default_schedule_config=default_schedule_config,
            default_content_type=default_content_type,
            default_tags=default_tags,
            effective_url=effective_url,
            source_specs=source_specs,
            archiver_info_source_id=archiver_info_source_id,
        )

        watched_item_patch.additional_properties = d
        return watched_item_patch

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
