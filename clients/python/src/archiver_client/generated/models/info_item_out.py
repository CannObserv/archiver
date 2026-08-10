from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.info_item_out_rep_fields import InfoItemOutRepFields
    from ..models.info_item_out_watch_spec import InfoItemOutWatchSpec
    from ..models.info_item_rep_spec_out import InfoItemRepSpecOut
    from ..models.info_item_source_out import InfoItemSourceOut


T = TypeVar("T", bound="InfoItemOut")


@_attrs_define
class InfoItemOut:
    """
    Attributes:
        created_at (datetime.datetime): UTC timestamp when the InfoItem was created.
        description (None | str): Optional freetext description of the InfoItem's content or purpose.
        info_item_id (str): ULID identifying this InfoItem.
        name (str): Human-readable label for the InfoItem.
        owner (None | str): Optional owner identifier (team or individual) for this InfoItem.
        rep_fields (InfoItemOutRepFields): Operator-defined JSONB bag of structured metadata fields for this item.
        updated_at (datetime.datetime): UTC timestamp of the last update to the InfoItem.
        watch_spec (InfoItemOutWatchSpec): Scheduling policy for this item (WatchSpec v1): '{"schema_version": 1,
            "active": true, "interval": "1d"}'. ``active: false`` is registered-but-paused, not removed. ``interval`` is
            optional — when absent the consumer applies its own default. Written via PUT /info-items/{id}/watch-spec.
        dashboard_url (None | str | Unset): Absolute URL of this item's Archiver dashboard detail page. Null when
            ARCHIVER_PUBLIC_BASE_URL is not configured on the server.
        info_item_rep_specs (list[InfoItemRepSpecOut] | Unset): Effective-dated RepSpec assignments for this InfoItem.
        info_item_sources (list[InfoItemSourceOut] | Unset): Bound InfoSources. By default only active bindings are
            returned (is_active=true). Pass include_deactivated=true to also include previous primaries and other
            deactivated bindings. At most one active binding (is_active=true) exists — the current primary. Deactivated
            bindings (is_active=false) are previous primaries, preserved as succession history.
    """

    created_at: datetime.datetime
    description: None | str
    info_item_id: str
    name: str
    owner: None | str
    rep_fields: InfoItemOutRepFields
    updated_at: datetime.datetime
    watch_spec: InfoItemOutWatchSpec
    dashboard_url: None | str | Unset = UNSET
    info_item_rep_specs: list[InfoItemRepSpecOut] | Unset = UNSET
    info_item_sources: list[InfoItemSourceOut] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        description: None | str
        description = self.description

        info_item_id = self.info_item_id

        name = self.name

        owner: None | str
        owner = self.owner

        rep_fields = self.rep_fields.to_dict()

        updated_at = self.updated_at.isoformat()

        watch_spec = self.watch_spec.to_dict()

        dashboard_url: None | str | Unset
        if isinstance(self.dashboard_url, Unset):
            dashboard_url = UNSET
        else:
            dashboard_url = self.dashboard_url

        info_item_rep_specs: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.info_item_rep_specs, Unset):
            info_item_rep_specs = []
            for info_item_rep_specs_item_data in self.info_item_rep_specs:
                info_item_rep_specs_item = info_item_rep_specs_item_data.to_dict()
                info_item_rep_specs.append(info_item_rep_specs_item)

        info_item_sources: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.info_item_sources, Unset):
            info_item_sources = []
            for info_item_sources_item_data in self.info_item_sources:
                info_item_sources_item = info_item_sources_item_data.to_dict()
                info_item_sources.append(info_item_sources_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "description": description,
                "info_item_id": info_item_id,
                "name": name,
                "owner": owner,
                "rep_fields": rep_fields,
                "updated_at": updated_at,
                "watch_spec": watch_spec,
            }
        )
        if dashboard_url is not UNSET:
            field_dict["dashboard_url"] = dashboard_url
        if info_item_rep_specs is not UNSET:
            field_dict["info_item_rep_specs"] = info_item_rep_specs
        if info_item_sources is not UNSET:
            field_dict["info_item_sources"] = info_item_sources

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_item_out_rep_fields import InfoItemOutRepFields
        from ..models.info_item_out_watch_spec import InfoItemOutWatchSpec
        from ..models.info_item_rep_spec_out import InfoItemRepSpecOut
        from ..models.info_item_source_out import InfoItemSourceOut

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        info_item_id = d.pop("info_item_id")

        name = d.pop("name")

        def _parse_owner(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        owner = _parse_owner(d.pop("owner"))

        rep_fields = InfoItemOutRepFields.from_dict(d.pop("rep_fields"))

        updated_at = isoparse(d.pop("updated_at"))

        watch_spec = InfoItemOutWatchSpec.from_dict(d.pop("watch_spec"))

        def _parse_dashboard_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dashboard_url = _parse_dashboard_url(d.pop("dashboard_url", UNSET))

        _info_item_rep_specs = d.pop("info_item_rep_specs", UNSET)
        info_item_rep_specs: list[InfoItemRepSpecOut] | Unset = UNSET
        if _info_item_rep_specs is not UNSET:
            info_item_rep_specs = []
            for info_item_rep_specs_item_data in _info_item_rep_specs:
                info_item_rep_specs_item = InfoItemRepSpecOut.from_dict(
                    info_item_rep_specs_item_data
                )

                info_item_rep_specs.append(info_item_rep_specs_item)

        _info_item_sources = d.pop("info_item_sources", UNSET)
        info_item_sources: list[InfoItemSourceOut] | Unset = UNSET
        if _info_item_sources is not UNSET:
            info_item_sources = []
            for info_item_sources_item_data in _info_item_sources:
                info_item_sources_item = InfoItemSourceOut.from_dict(info_item_sources_item_data)

                info_item_sources.append(info_item_sources_item)

        info_item_out = cls(
            created_at=created_at,
            description=description,
            info_item_id=info_item_id,
            name=name,
            owner=owner,
            rep_fields=rep_fields,
            updated_at=updated_at,
            watch_spec=watch_spec,
            dashboard_url=dashboard_url,
            info_item_rep_specs=info_item_rep_specs,
            info_item_sources=info_item_sources,
        )

        info_item_out.additional_properties = d
        return info_item_out

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
