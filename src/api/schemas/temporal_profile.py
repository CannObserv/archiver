"""Request/response models for an InfoItem's temporal profile (archiver#365)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictInt

ProfileType = Literal["event", "seasonal", "deadline"]
PostAction = Literal["reduce_frequency", "deactivate", "archive"]


class TemporalProfileRule(BaseModel):
    """One rule: from ``days_before`` the reference date, check every ``interval``.

    A seasonal profile takes exactly one rule, with no ``days_before``.
    """

    model_config = {"extra": "forbid"}
    days_before: StrictInt | None = Field(
        default=None,
        ge=0,
        description="event/deadline: the rule applies from this many days before the "
        "reference date. The smallest days_before still covering the day wins.",
    )
    interval: str = Field(
        description="A WatchSpec v1 interval ('30m', '6h', '1d'), greater than zero."
    )


class TemporalProfilePut(BaseModel):
    """Request body for PUT /info-items/{id}/temporal-profile: the whole profile.

    A create-or-replace, never a merge. ``event`` and ``deadline`` take a
    ``reference_date`` and no range; ``seasonal`` takes an inclusive range and
    no ``reference_date``. Dates are UTC calendar days and absolute: nothing
    recurs yearly. A profile whose window has already ended is refused - every
    accepted write re-arms the post-action, which would then fire again.
    """

    model_config = {"extra": "forbid"}
    profile_type: ProfileType
    reference_date: date | None = None
    date_range_start: date | None = None
    date_range_end: date | None = None
    rules: list[TemporalProfileRule] = Field(default_factory=list)
    post_action: PostAction = Field(
        description="Fired once, at the first daily boundary after the window: "
        "reduce_frequency sets the item's own interval to 1d if its base cadence is "
        "faster; deactivate pauses the item; archive archives its watch."
    )
    is_active: bool = Field(
        default=True,
        description="The operator's switch: an inactive profile contributes no "
        "interval and never fires.",
    )


class TemporalProfileOut(BaseModel):
    """An InfoItem's temporal profile, with the result it resolved to last."""

    info_item_id: str
    profile_type: ProfileType
    reference_date: date | None
    date_range_start: date | None
    date_range_end: date | None
    rules: list[dict[str, Any]] = Field(
        description="As stored: TemporalProfileRule objects (untyped here so a "
        "hand-edited row still reads back)."
    )
    post_action: PostAction
    is_active: bool
    resolved_interval: str | None = Field(
        description="The interval the profile contributes as of evaluated_on: the top "
        "tier of the announced cadence. null contributes none."
    )
    evaluated_on: date = Field(
        description="The UTC day resolved_interval was computed for: the last write or "
        "daily boundary."
    )
    fired_at: datetime | None = Field(
        description="When the post-action fired; null while it has not. A PUT clears it."
    )
    created_at: datetime
    updated_at: datetime
