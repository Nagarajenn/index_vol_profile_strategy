class DhanClientError(Exception):
    """Base error for anything wrong with a Dhan API call."""


class DhanAPIError(DhanClientError):
    """The API responded with status=failure."""

    def __init__(self, endpoint: str, remarks):
        self.endpoint = endpoint
        self.remarks = remarks
        super().__init__(f"Dhan API call to {endpoint} failed: {remarks}")


class ScripNotFoundError(DhanClientError):
    """A requested symbol could not be resolved in the scrip master."""
