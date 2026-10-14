"""Tests for the DWG->DXF conversion adapter seam (issue #3).

Adapters are the injection point agreed for this ticket: production injects
``OdaFileConverterAdapter``, tests inject ``DxfDirectAdapter``. Tests never
touch DWG/ODA binaries -- the ODA path is only exercised through its
missing-binary error, which fails before any external tool is invoked.
"""

from pathlib import Path

import pytest

from audit_tool.converters import (
    ConversionAdapter,
    DxfDirectAdapter,
    OdaFileConverterAdapter,
)


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
