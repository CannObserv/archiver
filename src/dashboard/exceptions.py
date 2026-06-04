"""Dashboard-specific exceptions with corresponding HTML response handlers."""


class DashboardNotFound(Exception):
    """Raised by dashboard routes when a resource is absent.

    Caught by the handler registered in ``register_dashboard()``, which
    returns a plain HTML 404 instead of the API's JSON error envelope.
    """

    def __init__(self, message: str = "Not found") -> None:
        self.message = message
        super().__init__(message)
