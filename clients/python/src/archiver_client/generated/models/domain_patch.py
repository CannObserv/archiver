from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.domain_patch_default_watch_spec_type_0 import DomainPatchDefaultWatchSpecType0


T = TypeVar("T", bound="DomainPatch")


@_attrs_define
class DomainPatch:
    """Request body for PATCH /domains/{name} — upsert fields.

    An omitted field is left as it is. ``default_watch_spec: null`` clears the
    cadence; ``min_interval_seconds`` cannot be null (every host carries an
    explicit policy).

        Attributes:
            default_watch_spec (DomainPatchDefaultWatchSpecType0 | None | Unset): Default cadence for Information Items on
                this host: a WatchSpec v1 document that carries an interval, or null for no domain default. Live (#364): an item
                on this host with no interval of its own announces this one on info.registry, and a change re-announces those
                items.
            is_active (bool | None | Unset): Suspension lever (archiver#360). false suspends the host: every Information
                Item announced on it goes out with active=false on info.registry, whatever its own watch_active. Archiving
                suspends it too.
            min_interval_seconds (float | Unset): Minimum spacing between requests to this host, in seconds (finite, >= 0;
                default 1.0). Live: Archiver publishes it on content.fetch-policy (#366, since flip F1), and a suspended host
                publishes revoked with no interval.
            notes (None | str | Unset): Operator annotations.
    """

    default_watch_spec: DomainPatchDefaultWatchSpecType0 | None | Unset = UNSET
    is_active: bool | None | Unset = UNSET
    min_interval_seconds: float | Unset = UNSET
    notes: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.domain_patch_default_watch_spec_type_0 import DomainPatchDefaultWatchSpecType0

        default_watch_spec: dict[str, Any] | None | Unset
        if isinstance(self.default_watch_spec, Unset):
            default_watch_spec = UNSET
        elif isinstance(self.default_watch_spec, DomainPatchDefaultWatchSpecType0):
            default_watch_spec = self.default_watch_spec.to_dict()
        else:
            default_watch_spec = self.default_watch_spec

        is_active: bool | None | Unset
        if isinstance(self.is_active, Unset):
            is_active = UNSET
        else:
            is_active = self.is_active

        min_interval_seconds = self.min_interval_seconds

        notes: None | str | Unset
        if isinstance(self.notes, Unset):
            notes = UNSET
        else:
            notes = self.notes

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if default_watch_spec is not UNSET:
            field_dict["default_watch_spec"] = default_watch_spec
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if min_interval_seconds is not UNSET:
            field_dict["min_interval_seconds"] = min_interval_seconds
        if notes is not UNSET:
            field_dict["notes"] = notes

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.domain_patch_default_watch_spec_type_0 import DomainPatchDefaultWatchSpecType0

        d = dict(src_dict)

        def _parse_default_watch_spec(
            data: object,
        ) -> DomainPatchDefaultWatchSpecType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                default_watch_spec_type_0 = DomainPatchDefaultWatchSpecType0.from_dict(data)

                return default_watch_spec_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DomainPatchDefaultWatchSpecType0 | None | Unset, data)

        default_watch_spec = _parse_default_watch_spec(d.pop("default_watch_spec", UNSET))

        def _parse_is_active(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_active = _parse_is_active(d.pop("is_active", UNSET))

        min_interval_seconds = d.pop("min_interval_seconds", UNSET)

        def _parse_notes(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        notes = _parse_notes(d.pop("notes", UNSET))

        domain_patch = cls(
            default_watch_spec=default_watch_spec,
            is_active=is_active,
            min_interval_seconds=min_interval_seconds,
            notes=notes,
        )

        return domain_patch
