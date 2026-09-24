from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="DeadLetterProvenanceOut")


@_attrs_define
class DeadLetterProvenanceOut:
    """What `dead_letter` recorded about an entry (co-core >= 0.19.1, cannobserv#474).

    Every field is null on an entry written before that.

        Attributes:
            consumer (None | str): The consumer within that group.
            group (None | str): The consumer group that parked it.
            reason (None | str): Why it was parked. Archiver's own start `handler poison: ` or `undecodable: `, then the
                error; capped at 2000 characters.
            source_id (None | str): The original entry's id on the source stream.
    """

    consumer: None | str
    group: None | str
    reason: None | str
    source_id: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        consumer: None | str
        consumer = self.consumer

        group: None | str
        group = self.group

        reason: None | str
        reason = self.reason

        source_id: None | str
        source_id = self.source_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "consumer": consumer,
                "group": group,
                "reason": reason,
                "source_id": source_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_consumer(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        consumer = _parse_consumer(d.pop("consumer"))

        def _parse_group(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        group = _parse_group(d.pop("group"))

        def _parse_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        reason = _parse_reason(d.pop("reason"))

        def _parse_source_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_id = _parse_source_id(d.pop("source_id"))

        dead_letter_provenance_out = cls(
            consumer=consumer,
            group=group,
            reason=reason,
            source_id=source_id,
        )

        dead_letter_provenance_out.additional_properties = d
        return dead_letter_provenance_out

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
