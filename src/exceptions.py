# Everything in this file is from https://github.com/TheOnlyWayUp/WattpadDownloader


class WattpadError(Exception):
    """Base Exception class for Wattpad related errors."""


class StoryNotFoundError(WattpadError):
    """Display the "This story was not found" error to the user."""

    ...


class PartNotFoundError(StoryNotFoundError): ...
