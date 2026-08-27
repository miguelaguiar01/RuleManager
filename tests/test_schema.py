"""analysis.schema: templating, identifier validation, config loading."""
import pytest

from analysis import schema
from analysis.schema import ConfigError, Naming, build_provider_schema, validate_identifier


def _naming():
    return Naming(
        ca_table="ca_{provider}",
        attribute_table="{type}_attrs_{provider}",
        materialized_view="mv_{provider}",
        attribute_types=["date", "int", "string", "decimal", "object"],
        ca_id="{provider}_ca_id",
    )


def test_templating_renders_all_names():
    s = build_provider_schema("bb", _naming())
    assert s.ca_table == "ca_bb"
    assert s.materialized_view == "mv_bb"
    assert s.ca_id == "bb_ca_id"
    assert s.attribute_tables["string"] == "string_attrs_bb"
    assert set(s.attribute_tables) == {"date", "int", "string", "decimal", "object"}


def test_object_excluded_from_matchable_tables():
    s = build_provider_schema("wm", _naming())
    assert "object" not in s.matchable_attribute_tables()
    assert "string" in s.matchable_attribute_tables()


@pytest.mark.parametrize("bad", ["Foo", "a-b", "1abc", "a b", "drop;table", "", "café"])
def test_validate_identifier_rejects_unsafe(bad):
    with pytest.raises(ConfigError):
        validate_identifier(bad)


def test_validate_identifier_accepts_lowercase():
    assert validate_identifier("string_attrs_bb") == "string_attrs_bb"


def test_injection_in_provider_is_rejected():
    with pytest.raises(ConfigError):
        build_provider_schema("bb; drop table x", _naming())


def test_missing_config_key_raises():
    with pytest.raises(ConfigError):
        Naming.from_dict({"ca_table": "ca_{provider}"}, {})  # missing keys


def _two_provider_config():
    return {
        "naming": {
            "ca_table": "ca_{provider}",
            "attribute_table": "{type}_attrs_{provider}",
            "materialized_view": "mv_{provider}",
            "attribute_types": ["int", "string"],
        },
        "columns": {"ca_id": "{provider}_ca_id"},
        "providers": {
            "bb": {"rules": "/rules/bb.json"},
            "wm": {"rules": "/rules/wm.json", "columns": {"ca_id": "wm_ca_id"}},
        },
    }


def test_configured_providers_and_rules():
    cfg = _two_provider_config()
    assert schema.configured_providers(cfg) == ["bb", "wm"]
    assert schema.provider_rules_path(cfg, "bb") == "/rules/bb.json"
    assert schema.provider_rules_path(cfg, "wm") == "/rules/wm.json"
    assert schema.provider_rules_path(cfg, "xx") is None


def test_naming_for_provider_uses_shared_templates():
    cfg = _two_provider_config()
    s = build_provider_schema("bb", schema.naming_for_provider(cfg, "bb"))
    assert s.ca_table == "ca_bb"
    assert s.ca_id == "bb_ca_id"          # from shared template
    assert s.attribute_tables["string"] == "string_attrs_bb"


def test_naming_for_provider_applies_override():
    cfg = _two_provider_config()
    # wm overrides ca_id to a fixed name (no template)
    s = build_provider_schema("wm", schema.naming_for_provider(cfg, "wm"))
    assert s.ca_id == "wm_ca_id"
    assert s.ca_table == "ca_wm"          # still from shared template


def test_load_config_from_file(tmp_path):
    cfg = tmp_path / "audit.local.toml"
    cfg.write_text(
        '[naming]\n'
        'ca_table = "ca_{provider}"\n'
        'attribute_table = "{type}_attrs_{provider}"\n'
        'materialized_view = "mv_{provider}"\n'
        'attribute_types = ["int", "string"]\n'
        '[columns]\n'
        'ca_id = "{provider}_ca_id"\n'
    )
    config = schema.load_config(str(cfg))
    naming = schema.naming_from_config(config)
    s = build_provider_schema("bb", naming)
    assert s.attribute_tables == {"int": "int_attrs_bb", "string": "string_attrs_bb"}
    assert s.mnemonic == "mnemonic"  # default applied
