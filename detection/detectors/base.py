from abc import ABC, abstractmethod


class BaseDetector(ABC):
    @abstractmethod
    def process(self, trade: dict) -> dict | None:
        """Return a signal dict if fired, None otherwise."""

    @abstractmethod
    def reset(self) -> None:
        """Reset all rolling windows (called on reconnect)."""
