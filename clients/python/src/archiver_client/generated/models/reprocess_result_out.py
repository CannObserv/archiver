from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.reprocess_result_out_outcome import ReprocessResultOutOutcome

T = TypeVar("T", bound="ReprocessResultOut")


@_attrs_define
class ReprocessResultOut:
    """What happened to one requested entry. Only `reprocessed` removed it.

    Attributes:
        detail (None | str): Why it stayed: the parking group, or the error. Null when it did not.
        entry_id (str):
        outcome (ReprocessResultOutOutcome): `reprocessed`: the handler settled it and it was deleted. `not_owned`:
            another group parked it, or it has no provenance. `undecodable`: still does not decode. `rejected`: the
            handler's poison - discard it. `failed`: any other handler error, e.g. the database down - retry. `deferred`:
            the handler asked for redelivery.
    """

    detail: None | str
    entry_id: str
    outcome: ReprocessResultOutOutcome
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        detail: None | str
        detail = self.detail

        entry_id = self.entry_id

        outcome = self.outcome.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "detail": detail,
                "entry_id": entry_id,
                "outcome": outcome,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_detail(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        detail = _parse_detail(d.pop("detail"))

        entry_id = d.pop("entry_id")

        outcome = ReprocessResultOutOutcome(d.pop("outcome"))

        reprocess_result_out = cls(
            detail=detail,
            entry_id=entry_id,
            outcome=outcome,
        )

        reprocess_result_out.additional_properties = d
        return reprocess_result_out

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
