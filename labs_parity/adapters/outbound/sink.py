"""Sink that keeps the raw freeze listings out of the notebook output."""

from __future__ import annotations

from labs_runtime.ports.outbound import OutputSinkPort


class DiscardSink(OutputSinkPort):
    def write(self, text: str) -> None:
        return None
