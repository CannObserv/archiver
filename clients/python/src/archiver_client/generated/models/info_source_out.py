from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.capture_policy import CapturePolicy
    from ..models.info_source_out_source_specs_item import InfoSourceOutSourceSpecsItem


T = TypeVar("T", bound="InfoSourceOut")


@_attrs_define
class InfoSourceOut:
    """Projection of an info_sources row.

    Attributes:
        created_at (datetime.datetime): UTC timestamp when the InfoSource was created.
        domain_name (None | str): Hostname derived from URL; references the domains table.
        info_source_id (str): ULID identifying this InfoSource.
        source_specs (list[InfoSourceOutSourceSpecsItem]): Ordered list of extraction specs.
        url (str): URL to fetch.
        capture_policy (CapturePolicy | None | Unset): What a viewport capture of this source sends (viewport,
            full_page, wait) and whether each new revision triggers one (on_revision). null = no policy: an on-demand
            capture uses 1280x800, full page, no wait, and no revision triggers one (archiver#380).
    """

    created_at: datetime.datetime
    domain_name: None | str
    info_source_id: str
    source_specs: list[InfoSourceOutSourceSpecsItem]
    url: str
    capture_policy: CapturePolicy | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.capture_policy import CapturePolicy

        created_at = self.created_at.isoformat()

        domain_name: None | str
        domain_name = self.domain_name

        info_source_id = self.info_source_id

        source_specs = []
        for source_specs_item_data in self.source_specs:
            source_specs_item = source_specs_item_data.to_dict()
            source_specs.append(source_specs_item)

        url = self.url

        capture_policy: dict[str, Any] | None | Unset
        if isinstance(self.capture_policy, Unset):
            capture_policy = UNSET
        elif isinstance(self.capture_policy, CapturePolicy):
            capture_policy = self.capture_policy.to_dict()
        else:
            capture_policy = self.capture_policy

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "domain_name": domain_name,
                "info_source_id": info_source_id,
                "source_specs": source_specs,
                "url": url,
            }
        )
        if capture_policy is not UNSET:
            field_dict["capture_policy"] = capture_policy

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.capture_policy import CapturePolicy
        from ..models.info_source_out_source_specs_item import InfoSourceOutSourceSpecsItem

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_domain_name(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        domain_name = _parse_domain_name(d.pop("domain_name"))

        info_source_id = d.pop("info_source_id")

        source_specs = []
        _source_specs = d.pop("source_specs")
        for source_specs_item_data in _source_specs:
            source_specs_item = InfoSourceOutSourceSpecsItem.from_dict(source_specs_item_data)

            source_specs.append(source_specs_item)

        url = d.pop("url")

        def _parse_capture_policy(data: object) -> CapturePolicy | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                capture_policy_type_0 = CapturePolicy.from_dict(data)

                return capture_policy_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CapturePolicy | None | Unset, data)

        capture_policy = _parse_capture_policy(d.pop("capture_policy", UNSET))

        info_source_out = cls(
            created_at=created_at,
            domain_name=domain_name,
            info_source_id=info_source_id,
            source_specs=source_specs,
            url=url,
            capture_policy=capture_policy,
        )

        info_source_out.additional_properties = d
        return info_source_out

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
