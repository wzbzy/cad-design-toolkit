"""DWG->DXF conversion adapters (issue #3).

The conversion adapter is an injection seam: the extraction pipeline depends
only on :class:`ConversionAdapter`, never on a concrete converter.

- :class:`DxfDirectAdapter` reads DXF files as-is (tests and fixtures; no
  external binary).
- :class:`OdaFileConverterAdapter` shells out to the ODA File Converter
  (production; binary path configurable).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

__all__ = ["ConversionAdapter", "DxfDirectAdapter", "OdaFileConverterAdapter"]


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


class OdaFileConverterAdapter(ConversionAdapter):
    """Converts DWG (and other formats) to DXF via the ODA File Converter.

    The converter binary is free but external; its path is configurable.
    The ODA CLI converts whole directories, so each conversion happens in a
    private temp directory and the resulting DXF is placed next to the
    source (source itself is never modified).
    """

    def __init__(
        self,
        oda_path,
        output_version: str = "ACAD2018",
        output_type: str = "DXF",
    ):
        self.oda_path = Path(oda_path)
        self.output_version = output_version
        self.output_type = output_type

    def to_dxf(self, source: Path) -> Path:
        source = Path(source)
        if not self.oda_path.is_file():
            raise FileNotFoundError(
                f"ODA File Converter not found at {self.oda_path}. "
                "Install it (https://www.opendesign.com/guestfiles/oda_file_converter) "
                "and pass its path, or inject DxfDirectAdapter when input is already DXF."
            )

        target = source.with_suffix(".dxf")
        with tempfile.TemporaryDirectory(prefix="audit_oda_") as tmp:
            staging = Path(tmp) / source.name
            shutil.copyfile(source, staging)
            result = subprocess.run(
                [
                    str(self.oda_path),
                    str(tmp),
                    str(tmp),
                    self.output_version,
                    self.output_type,
                    "0",  # no recursion
                    "1",  # audit input files
                    staging.name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            produced = Path(tmp) / (source.stem + ".dxf")
            if result.returncode != 0 or not produced.is_file():
                raise RuntimeError(
                    f"ODA File Converter failed for {source.name} "
                    f"(exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
                )
            shutil.copyfile(produced, target)
        return target
