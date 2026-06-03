from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.info_item_create_rep_fields import InfoItemCreateRepFields
    from ..models.rep_spec_assignment_create import RepSpecAssignmentCreate


T = TypeVar("T", bound="InfoItemCreate")


@_attrs_define
class InfoItemCreate:
    """
    Attributes:
        name (str):
        description (None | str | Unset):
        initial_rep_spec_assignments (list[RepSpecAssignmentCreate] | Unset): Optional list of
            RepSpec assignments to atomically create alongside the new InfoItem. Each rep_spec_id
            must reference an existing RepSpec. rep_fields are validated against each RepSpec's
            required_fields.
        initial_url (None | str | Unset): Optional URL to atomically create an InfoSource binding
            for this item.
        initial_source_specs (list[Any] | None | Unset): Extraction specs for the initial
            InfoSource. Required when initial_url is set. Each element is a SourceSpec v1 document
            (schema_version, extraction, fingerprint).
        owner (None | str | Unset):
        rep_fields (InfoItemCreateRepFields | Unset):
    """

    name: str
    description: None | str | Unset = UNSET
    initial_rep_spec_assignments: list[RepSpecAssignmentCreate] | Unset = UNSET
    initial_url: None | str | Unset = UNSET
    initial_source_specs: list[Any] | None | Unset = UNSET
    owner: None | str | Unset = UNSET
    rep_fields: InfoItemCreateRepFields | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        initial_rep_spec_assignments: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.initial_rep_spec_assignments, Unset):
            initial_rep_spec_assignments = []
            for item_data in self.initial_rep_spec_assignments:
                initial_rep_spec_assignments.append(item_data.to_dict())

        initial_url: None | str | Unset
        if isinstance(self.initial_url, Unset):
            initial_url = UNSET
        else:
            initial_url = self.initial_url

        initial_source_specs: list[Any] | None | Unset
        if isinstance(self.initial_source_specs, Unset):
            initial_source_specs = UNSET
        else:
            initial_source_specs = self.initial_source_specs

        owner: None | str | Unset
        if isinstance(self.owner, Unset):
            owner = UNSET
        else:
            owner = self.owner

        rep_fields: dict[str, Any] | Unset = UNSET
        if not isinstance(self.rep_fields, Unset):
            rep_fields = self.rep_fields.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({"name": name})
        if description is not UNSET:
            field_dict["description"] = description
        if initial_rep_spec_assignments is not UNSET:
            field_dict["initial_rep_spec_assignments"] = initial_rep_spec_assignments
        if initial_url is not UNSET:
            field_dict["initial_url"] = initial_url
        if initial_source_specs is not UNSET:
            field_dict["initial_source_specs"] = initial_source_specs
        if owner is not UNSET:
            field_dict["owner"] = owner
        if rep_fields is not UNSET:
            field_dict["rep_fields"] = rep_fields

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_item_create_rep_fields import InfoItemCreateRepFields
        from ..models.rep_spec_assignment_create import RepSpecAssignmentCreate

        d = dict(src_dict)
        name = d.pop("name")

        def _parse_nullable_str(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return str(data)

        description = _parse_nullable_str(d.pop("description", UNSET))
        owner = _parse_nullable_str(d.pop("owner", UNSET))
        initial_url = _parse_nullable_str(d.pop("initial_url", UNSET))

        _initial_rep_spec_assignments = d.pop("initial_rep_spec_assignments", UNSET)
        initial_rep_spec_assignments: list[RepSpecAssignmentCreate] | Unset = UNSET
        if _initial_rep_spec_assignments is not UNSET:
            initial_rep_spec_assignments = [
                RepSpecAssignmentCreate.from_dict(item) for item in _initial_rep_spec_assignments
            ]

        initial_source_specs = d.pop("initial_source_specs", UNSET)

        _rep_fields = d.pop("rep_fields", UNSET)
        rep_fields: InfoItemCreateRepFields | Unset
        if isinstance(_rep_fields, Unset):
            rep_fields = UNSET
        else:
            rep_fields = InfoItemCreateRepFields.from_dict(_rep_fields)

        obj = cls(
            name=name,
            description=description,
            initial_rep_spec_assignments=initial_rep_spec_assignments,
            initial_url=initial_url,
            initial_source_specs=initial_source_specs,
            owner=owner,
            rep_fields=rep_fields,
        )
        obj.additional_properties = d
        return obj

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
