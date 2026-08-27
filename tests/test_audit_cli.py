"""analysis.__main__ CLI helpers (no DB): provider/rules resolution, export naming."""
from pathlib import Path

import pytest

from analysis import __main__ as cli


CONFIG = {
    "naming": {"ca_table": "ca_{provider}", "attribute_table": "{type}_a_{provider}",
               "materialized_view": "mv_{provider}", "attribute_types": ["int"]},
    "columns": {"ca_id": "{provider}_ca_id"},
    "providers": {"bb": {"rules": "/rules/bb.json"}, "wm": {"rules": "/rules/wm.json"}},
}


def test_resolve_single_provider():
    assert cli.resolve_providers("bb", CONFIG) == ["bb"]


def test_resolve_all_providers_when_omitted():
    assert cli.resolve_providers(None, CONFIG) == ["bb", "wm"]


def test_resolve_providers_errors_when_none_configured():
    with pytest.raises(SystemExit):
        cli.resolve_providers(None, {"providers": {}})


def test_rules_from_config():
    assert cli.resolve_rules_path(None, CONFIG, "bb") == "/rules/bb.json"


def test_rules_cli_overrides_config():
    assert cli.resolve_rules_path("/other/x.json", CONFIG, "bb") == "/other/x.json"


def test_rules_missing_raises():
    with pytest.raises(SystemExit):
        cli.resolve_rules_path(None, CONFIG, "unknown")


def test_export_path_single_provider_is_unchanged():
    assert cli.export_path("exports/audit.json", "bb", multi=False) == Path("exports/audit.json")


def test_export_path_multi_provider_appends_name():
    assert cli.export_path("exports/audit.json", "bb", multi=True) == Path("exports/audit_bb.json")
    assert cli.export_path("exports/audit.json", "wm", multi=True) == Path("exports/audit_wm.json")


def test_connection_target_host_port():
    cfg = {"connection": {"host": "db.dev", "port": 5433, "dbname": "mdm_ca"}}
    assert cli._connection_target(cfg) == "db.dev:5433/mdm_ca"


def test_connection_target_hides_dsn_and_service():
    assert cli._connection_target({"connection": {"dsn": "postgresql://secret@h/d"}}) == "configured DSN"
    assert cli._connection_target({"connection": {"service": "prod"}}) == "service prod"


def test_parse_args_provider_optional():
    args = cli.parse_args(["--provider", "bb"])
    assert args.provider == "bb"
    assert args.source == "both"
    assert cli.parse_args([]).provider is None   # omitting provider is allowed
