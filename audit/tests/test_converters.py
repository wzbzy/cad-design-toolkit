"""Tests for the DWG->DXF conversion adapter seam (issue #3).

Adapters are the injection point agreed for this ticket: production injects
``OdaFileConverterAdapter``, tests inject ``DxfDirectAdapter``. Tests never
touch DWG/ODA binaries -- the ODA path is only exercised through its
missing-binary error, which fails before any external tool is invoked.
"""

from pathlib import Path

import pytest

from audit_tool import fixtures
from audit_tool.converters import (
    ConversionAdapter,
    DxfDirectAdapter,
    OdaFileConverterAdapter,
)
from audit_tool.extract import extract_cabinets


def test_dxf_direct_adapter_is_a_conversion_adapter():
    assert isinstance(DxfDirectAdapter(), ConversionAdapter)


def test_dxf_direct_adapter_passes_dxf_through_untouched(tmp_path):
    dxf = tmp_path / "order.dxf"
    dxf.write_text("0\nSECTION\n", encoding="ascii")

    out = DxfDirectAdapter().to_dxf(dxf)

    assert out == dxf
    assert dxf.read_text(encoding="ascii") == "0\nSECTION\n"


def test_dxf_direct_adapter_rejects_non_dxf_without_touching_file(tmp_path):
    missing = tmp_path / "order.dwg"

    with pytest.raises(ValueError, match="only reads DXF"):
        DxfDirectAdapter().to_dxf(missing)


def test_oda_adapter_is_a_conversion_adapter():
    adapter = OdaFileConverterAdapter(oda_path=Path("C:/no/such/ODAFileConverter.exe"))
    assert isinstance(adapter, ConversionAdapter)


def test_oda_adapter_reports_missing_binary_clearly(tmp_path):
    adapter = OdaFileConverterAdapter(oda_path=tmp_path / "ODAFileConverter.exe")
    source = tmp_path / "order.dwg"
    source.write_bytes(b"fake")  # plain bytes; never a real DWG, never opened by ODA

    with pytest.raises(FileNotFoundError, match="ODA File Converter"):
        adapter.to_dxf(source)


def test_custom_adapter_can_replace_dxf_direct_in_the_pipeline(tmp_path):
    """Any ConversionAdapter implementation can drive extraction (issue #3:
    interface independently injectable/replaceable)."""

    class FixedFixtureAdapter(ConversionAdapter):
        """Stands in for any real converter: always yields the fixture DXF."""

        def __init__(self, dxf_path):
            self.dxf_path = dxf_path

        def to_dxf(self, source):
            return self.dxf_path

    path = tmp_path / "cabinet.dxf"
    fixtures.save_dxf(fixtures.build_scenario("base_cabinet_800"), path)

    cabinets = extract_cabinets(FixedFixtureAdapter(path).to_dxf(Path("ignored.dwg")))

    assert len(cabinets) == 1
    assert cabinets[0].bbox == pytest.approx((-20.0, 0.0, 820.0, 800.0))
