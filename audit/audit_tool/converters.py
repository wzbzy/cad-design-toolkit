"""DWG->DXF conversion adapters (issue #3).

The conversion adapter is an injection seam: the extraction pipeline depends
only on :class:`ConversionAdapter`, never on a concrete converter.

- :class:`DxfDirectAdapter` reads DXF files as-is (tests and fixtures; no
  external binary).
- :class:`OdaFileConverterAdapter` shells out to the ODA File Converter
  (production; binary path configurable).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

__all__ = ["ConversionAdapter", "DxfDirectAdapter"]


class ConversionAdapter(ABC):
    """Interface for turning an order drawing into a DXF file path."""

    @abstractmethod
    def to_dxf(self, source: Path) -> Path:
        """Return the path of a readable DXF file for ``source``.

        Implementations must not modify the source file.
        """


class DxfDirectAdapter(ConversionAdapter):
    """Pass-through adapter for drawings that are already DXF."""

    def to_dxf(self, source: Path) -> Path:
        source = Path(source)
        if source.suffix.lower() != ".dxf":
            raise ValueError(
                f"DxfDirectAdapter only reads DXF files, got {source.suffix!r} "
                f"({source.name}); use OdaFileConverterAdapter for DWG input"
            )
        return source
