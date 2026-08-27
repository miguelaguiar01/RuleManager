"""analysis.records: EAV pivot and MV remapping."""
from analysis import records as rec


def test_build_records_from_eav_pivots_attributes():
    base = [
        {"ca_id": 1, "mnemonic": "DVD_CASH", "swift_code": "DVCA"},
        {"ca_id": 2, "mnemonic": "STOCK_SPLT", "swift_code": "SPLR"},
    ]
    attrs = [
        {"ca_id": 1, "attribute": "CP_STOCK_OPT", "value": "S"},
        {"ca_id": 1, "attribute": "CP_DVD_TYP", "value": "1027"},
        {"ca_id": 2, "attribute": "CP_RATIO", "value": 2},
    ]
    out = rec.build_records_from_eav(base, attrs)
    assert out[1].assigned_code == "DVCA"
    assert out[1].fields == {"mnemonic": "DVD_CASH", "CP_STOCK_OPT": "S", "CP_DVD_TYP": "1027"}
    assert out[2].fields["CP_RATIO"] == 2


def test_eav_attribute_without_base_row_is_kept():
    out = rec.build_records_from_eav([], [{"ca_id": 9, "attribute": "X", "value": "1"}])
    assert out[9].assigned_code is None
    assert out[9].fields == {"X": "1"}


def test_build_records_from_mv_remaps_lowercase_columns():
    # MV stores lowercase column names; rules reference the original case.
    mv_rows = [{
        "ca_id": 1, "mnemonic": "DVD_CASH", "swift_code": "DVCA",
        "cp_stock_opt": "S", "ud006a": "07",
    }]
    columns = {"mnemonic", "CP_STOCK_OPT", "UD006A"}
    out = rec.build_records_from_mv(mv_rows, columns)
    assert out[1].assigned_code == "DVCA"
    assert out[1].fields["CP_STOCK_OPT"] == "S"     # remapped from cp_stock_opt
    assert out[1].fields["UD006A"] == "07"          # remapped from ud006a
    assert out[1].fields["mnemonic"] == "DVD_CASH"
    assert "swift_code" not in out[1].fields
