"""A ``LoopProgress`` that records each stamp, for the bus loops' liveness tests (archiver#297)."""

from src.core.liveness import LoopProgress


class Stamps(LoopProgress):
    """Every stamp's ``backing_off``, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[bool] = []

    def stamp(self, *, backing_off: bool = False) -> None:
        super().stamp(backing_off=backing_off)
        self.log.append(backing_off)
