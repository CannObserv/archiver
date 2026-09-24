from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..models.dead_letter_out_parked_as_type_0 import DeadLetterOutParkedAsType0

if TYPE_CHECKING:
    from ..models.dead_letter_out_fields import DeadLetterOutFields
    from ..models.dead_letter_provenance_out import DeadLetterProvenanceOut


T = TypeVar("T", bound="DeadLetterOut")


@_attrs_define
class DeadLetterOut:
    """One entry of a dead-letter queue, described for triage.

    Attributes:
        dead_lettered_at (datetime.datetime): When the entry was dead-lettered, from its stream id. On an entry with no
            provenance, the way back to the journald line that says why.
        decode_error (None | str): Why it does not decode; null when it does.
        decodes (bool): Whether the frame decodes against the running co-core. True on an entry that failed to decode
            when it was parked is the version-skew case.
        entry_id (str): The entry's stream id in the DLQ; what discard takes.
        event_type (None | str): The frame's `event_type` field, if it has one.
        fields (DeadLetterOutFields): The raw entry: the wire fields `dead_letter` copied, plus its `dlq.*` provenance
            fields.
        owned (bool): Whether archiver's own group for this queue's topic parked it. A fact stream's DLQ is shared by
            every consuming service; only owned entries are archiver's to reprocess.
        parked_as (DeadLetterOutParkedAsType0 | None): Which quarantine path parked it, read off the reason's prefix.
            `handler_poison` decoded and still failed: discard. `undecodable` with `decodes` true is version skew:
            reprocess. Null with no reason, or one archiver did not write.
        provenance (DeadLetterProvenanceOut): What `dead_letter` recorded about an entry (co-core >= 0.19.1,
            cannobserv#474).

            Every field is null on an entry written before that.
    """

    dead_lettered_at: datetime.datetime
    decode_error: None | str
    decodes: bool
    entry_id: str
    event_type: None | str
    fields: DeadLetterOutFields
    owned: bool
    parked_as: DeadLetterOutParkedAsType0 | None
    provenance: DeadLetterProvenanceOut
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dead_lettered_at = self.dead_lettered_at.isoformat()

        decode_error: None | str
        decode_error = self.decode_error

        decodes = self.decodes

        entry_id = self.entry_id

        event_type: None | str
        event_type = self.event_type

        fields = self.fields.to_dict()

        owned = self.owned

        parked_as: None | str
        if isinstance(self.parked_as, DeadLetterOutParkedAsType0):
            parked_as = self.parked_as.value
        else:
            parked_as = self.parked_as

        provenance = self.provenance.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dead_lettered_at": dead_lettered_at,
                "decode_error": decode_error,
                "decodes": decodes,
                "entry_id": entry_id,
                "event_type": event_type,
                "fields": fields,
                "owned": owned,
                "parked_as": parked_as,
                "provenance": provenance,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dead_letter_out_fields import DeadLetterOutFields
        from ..models.dead_letter_provenance_out import DeadLetterProvenanceOut

        d = dict(src_dict)
        dead_lettered_at = isoparse(d.pop("dead_lettered_at"))

        def _parse_decode_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        decode_error = _parse_decode_error(d.pop("decode_error"))

        decodes = d.pop("decodes")

        entry_id = d.pop("entry_id")

        def _parse_event_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        event_type = _parse_event_type(d.pop("event_type"))

        fields = DeadLetterOutFields.from_dict(d.pop("fields"))

        owned = d.pop("owned")

        def _parse_parked_as(data: object) -> DeadLetterOutParkedAsType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                parked_as_type_0 = DeadLetterOutParkedAsType0(data)

                return parked_as_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DeadLetterOutParkedAsType0 | None, data)

        parked_as = _parse_parked_as(d.pop("parked_as"))

        provenance = DeadLetterProvenanceOut.from_dict(d.pop("provenance"))

        dead_letter_out = cls(
            dead_lettered_at=dead_lettered_at,
            decode_error=decode_error,
            decodes=decodes,
            entry_id=entry_id,
            event_type=event_type,
            fields=fields,
            owned=owned,
            parked_as=parked_as,
            provenance=provenance,
        )

        dead_letter_out.additional_properties = d
        return dead_letter_out

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
