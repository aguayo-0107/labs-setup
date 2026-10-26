"""Errors the gateway reports to clients, named after Athena's error types."""

from __future__ import annotations


class AthenaError(Exception):
    """Base of every error returned to the client as `{"__type": code}`."""

    code = "InternalServerException"
    status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidRequestError(AthenaError):
    code = "InvalidRequestException"
    status = 400


class UnknownOperationError(AthenaError):
    code = "UnknownOperationException"
    status = 400


class QueryFailedError(Exception):
    """The engine rejected or failed the statement; the message becomes StateChangeReason."""
