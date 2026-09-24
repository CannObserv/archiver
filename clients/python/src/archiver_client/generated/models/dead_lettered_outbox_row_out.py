from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="DeadLetteredOutboxRowOut")


@_attrs_define
class DeadLetteredOutboxRowOut:
    """One dead-lettered ``changes_outbox`` row, described for triage.

    Attributes:
        created_at (datetime.datetime):
        dead_lettered_at (datetime.datetime):
        event_type (None | str): The payload's `event_type`, if it has one.
        last_error (None | str): Why it was dead-lettered, capped at 1000 characters. The full traceback is on the
            journald line `Dead-lettering outbox row`, while retention lasts.
        payload (Any): The stored payload, as the publisher saw it. Usually an object, but a non-object payload is one
            of the poison cases, so it is returned as stored.
        publish_attempts (int): Failed attempts before it was dead-lettered.
        rearmable (bool): Whether its topic may go back to the drain. Only `info.changes` does: `info.registry` is
            repaired by the hourly snapshot, and a late `content.replicate` command may already be abandoned. Discard the
            rest.
        row_id (str): The outbox row's ULID; what discard and rearm take.
        topic (str): The stream the row was bound for.
    """

    created_at: datetime.datetime
    dead_lettered_at: datetime.datetime
    event_type: None | str
    last_error: None | str
    payload: Any
    publish_attempts: int
    rearmable: bool
    row_id: str
    topic: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        dead_lettered_at = self.dead_lettered_at.isoformat()

        event_type: None | str
        event_type = self.event_type

        last_error: None | str
        last_error = self.last_error

        payload = self.payload

        publish_attempts = self.publish_attempts

        rearmable = self.rearmable

        row_id = self.row_id

        topic = self.topic

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "dead_lettered_at": dead_lettered_at,
                "event_type": event_type,
                "last_error": last_error,
                "payload": payload,
                "publish_attempts": publish_attempts,
                "rearmable": rearmable,
                "row_id": row_id,
                "topic": topic,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        dead_lettered_at = isoparse(d.pop("dead_lettered_at"))

        def _parse_event_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        event_type = _parse_event_type(d.pop("event_type"))

        def _parse_last_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        last_error = _parse_last_error(d.pop("last_error"))

        payload = d.pop("payload")

        publish_attempts = d.pop("publish_attempts")

        rearmable = d.pop("rearmable")

        row_id = d.pop("row_id")

        topic = d.pop("topic")

        dead_lettered_outbox_row_out = cls(
            created_at=created_at,
            dead_lettered_at=dead_lettered_at,
            event_type=event_type,
            last_error=last_error,
            payload=payload,
            publish_attempts=publish_attempts,
            rearmable=rearmable,
            row_id=row_id,
            topic=topic,
        )

        dead_lettered_outbox_row_out.additional_properties = d
        return dead_lettered_outbox_row_out

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
