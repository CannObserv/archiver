from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="InfoItemOrgOut")


@_attrs_define
class InfoItemOrgOut:
    """The linked Power Map org, as archiver last saw it (archiver#304).

    A local snapshot, refreshed on link and by the follower. The nullable
    fields are notices; none of them stops replication.

        Attributes:
            acronym (None | str): Canonical acronym: the effective bag's org.acronym, absent when null.
            active (bool): Power Map's active flag.
            archived_at (datetime.datetime | None): When Power Map archived the org, if it did.
            checked_at (datetime.datetime): When archiver last got an answer about the org.
            merged_into (None | str): Set when this org was merged into another.
            missing_since (datetime.datetime | None): First check that found the org gone from Power Map; the snapshot still
                renders.
            name (str): Canonical name: the effective bag's org.title.
            pm_org_id (str): Power Map org id.
            renamed_at (datetime.datetime | None): When archiver saw that change.
            renamed_from (None | str): The previous canonical name, when a refresh saw the name or acronym change.
            succeeded_by (None | str): A re-key: the id of the *different* org that succeeds this one. Not followed.
    """

    acronym: None | str
    active: bool
    archived_at: datetime.datetime | None
    checked_at: datetime.datetime
    merged_into: None | str
    missing_since: datetime.datetime | None
    name: str
    pm_org_id: str
    renamed_at: datetime.datetime | None
    renamed_from: None | str
    succeeded_by: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        acronym: None | str
        acronym = self.acronym

        active = self.active

        archived_at: None | str
        if isinstance(self.archived_at, datetime.datetime):
            archived_at = self.archived_at.isoformat()
        else:
            archived_at = self.archived_at

        checked_at = self.checked_at.isoformat()

        merged_into: None | str
        merged_into = self.merged_into

        missing_since: None | str
        if isinstance(self.missing_since, datetime.datetime):
            missing_since = self.missing_since.isoformat()
        else:
            missing_since = self.missing_since

        name = self.name

        pm_org_id = self.pm_org_id

        renamed_at: None | str
        if isinstance(self.renamed_at, datetime.datetime):
            renamed_at = self.renamed_at.isoformat()
        else:
            renamed_at = self.renamed_at

        renamed_from: None | str
        renamed_from = self.renamed_from

        succeeded_by: None | str
        succeeded_by = self.succeeded_by

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "acronym": acronym,
                "active": active,
                "archived_at": archived_at,
                "checked_at": checked_at,
                "merged_into": merged_into,
                "missing_since": missing_since,
                "name": name,
                "pm_org_id": pm_org_id,
                "renamed_at": renamed_at,
                "renamed_from": renamed_from,
                "succeeded_by": succeeded_by,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_acronym(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        acronym = _parse_acronym(d.pop("acronym"))

        active = d.pop("active")

        def _parse_archived_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                archived_at_type_0 = isoparse(data)

                return archived_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        archived_at = _parse_archived_at(d.pop("archived_at"))

        checked_at = isoparse(d.pop("checked_at"))

        def _parse_merged_into(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        merged_into = _parse_merged_into(d.pop("merged_into"))

        def _parse_missing_since(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                missing_since_type_0 = isoparse(data)

                return missing_since_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        missing_since = _parse_missing_since(d.pop("missing_since"))

        name = d.pop("name")

        pm_org_id = d.pop("pm_org_id")

        def _parse_renamed_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                renamed_at_type_0 = isoparse(data)

                return renamed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        renamed_at = _parse_renamed_at(d.pop("renamed_at"))

        def _parse_renamed_from(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        renamed_from = _parse_renamed_from(d.pop("renamed_from"))

        def _parse_succeeded_by(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        succeeded_by = _parse_succeeded_by(d.pop("succeeded_by"))

        info_item_org_out = cls(
            acronym=acronym,
            active=active,
            archived_at=archived_at,
            checked_at=checked_at,
            merged_into=merged_into,
            missing_since=missing_since,
            name=name,
            pm_org_id=pm_org_id,
            renamed_at=renamed_at,
            renamed_from=renamed_from,
            succeeded_by=succeeded_by,
        )

        info_item_org_out.additional_properties = d
        return info_item_org_out

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
