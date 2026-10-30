"""An in-memory Notifier for tests (archiver#368). CI never calls live Notifier.

Duck-types ``src.core.notifier.client.Notifier``: ``list_channels`` answers what
the test planted, or raises ``unavailable``; ``dispatch_composed`` (#367) records
its arguments in ``dispatches`` and answers ``dispatched``, or raises
``unavailable``. ``calls`` records each call by name, so a test can assert a page
made exactly the calls it should.
"""

from __future__ import annotations

from src.core.notifier.client import Channel, Dispatched, NotifierUnavailable

DEV_SINK = Channel(id="01M5APS9R7A0QEDB9522MRA4CT", name="dev-sink", kind="syslog")
DEV_SINK_FAILING = Channel(id="01M5APS9R7A0QEDB9522MRA4CV", name="dev-sink-failing", kind="sink")


class FakeNotifier:
    def __init__(
        self,
        *channels: Channel,
        unavailable: NotifierUnavailable | None = None,
        base_url: str = "http://notifier.test:9001",
        key_source: str = "environment",
    ) -> None:
        self.channels = list(channels)
        self.unavailable = unavailable
        self.base_url = base_url
        self.key_source = key_source
        self.calls: list[str] = []
        self.dispatches: list[dict] = []
        self.dispatched = Dispatched(id="01M5DISPATCH0000000000000A", status="succeeded")

    async def list_channels(self) -> list[Channel]:
        self.calls.append("list_channels")
        if self.unavailable is not None:
            raise self.unavailable
        return list(self.channels)

    async def dispatch_composed(self, **kwargs) -> Dispatched:
        self.calls.append("dispatch_composed")
        self.dispatches.append(kwargs)
        if self.unavailable is not None:
            raise self.unavailable
        return self.dispatched

    async def aclose(self) -> None:
        self.calls.append("aclose")
