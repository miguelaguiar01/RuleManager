"""Config-driven schema: turns name *templates* from a laptop-only config file
into concrete, validated Postgres identifiers.

The public repo carries no real table or column names. Everything here is
generic templating over `{provider}` and `{type}`, and every identifier that
will reach a query is validated against a strict lowercase-identifier regex
before use, so a malformed or malicious config can never inject SQL.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List

# Postgres unquoted identifier, lowercased. Templates may also contain the
# placeholders {provider} and {type}, which are substituted before validation.
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class ConfigError(ValueError):
    """Raised when a config value is missing or unsafe."""


def validate_identifier(name: str, what: str = "identifier") -> str:
    if not isinstance(name, str) or not _IDENTIFIER.match(name):
        raise ConfigError(f"Unsafe {what}: {name!r} (must match {_IDENTIFIER.pattern})")
    return name


def _render(template: str, **subs: str) -> str:
    try:
        return template.format(**subs)
    except (KeyError, IndexError) as exc:
        raise ConfigError(f"Bad template {template!r}: {exc}") from exc


@dataclass(frozen=True)
class Naming:
    """Name templates. Real values come from the laptop config; the example
    file ships with placeholders only."""
    ca_table: str
    attribute_table: str
    materialized_view: str
    attribute_types: List[str]
    ca_id: str
    mnemonic: str = "mnemonic"
    swift_code: str = "swift_code"
    attribute_name: str = "attribute"
    attribute_value: str = "value"
    db_schema: str = "public"   # Postgres schema/namespace the tables live in

    @staticmethod
    def from_dict(naming: Dict, columns: Dict) -> "Naming":
        try:
            return Naming(
                ca_table=naming["ca_table"],
                attribute_table=naming["attribute_table"],
                materialized_view=naming["materialized_view"],
                attribute_types=list(naming["attribute_types"]),
                ca_id=columns["ca_id"],
                mnemonic=columns.get("mnemonic", "mnemonic"),
                swift_code=columns.get("swift_code", "swift_code"),
                attribute_name=columns.get("attribute_name", "attribute"),
                attribute_value=columns.get("attribute_value", "value"),
                db_schema=naming.get("schema", "public"),
            )
        except KeyError as exc:
            raise ConfigError(f"Missing config key: {exc}") from exc


@dataclass(frozen=True)
class ProviderSchema:
    """Concrete, validated names for one provider."""
    provider: str
    ca_table: str
    materialized_view: str
    ca_id: str
    mnemonic: str
    swift_code: str
    attribute_name: str
    attribute_value: str
    db_schema: str = "public"
    attribute_tables: Dict[str, str] = field(default_factory=dict)

    def matchable_attribute_tables(self) -> Dict[str, str]:
        """Attribute tables we evaluate rules against — excludes `object`,
        which holds free-form extra info no rule references."""
        return {t: name for t, name in self.attribute_tables.items() if t != "object"}


def build_provider_schema(provider: str, naming: Naming) -> ProviderSchema:
    """Render + validate every identifier for one provider."""
    validate_identifier(provider, "provider")

    db_schema = validate_identifier(_render(naming.db_schema, provider=provider), "schema")
    ca_table = validate_identifier(_render(naming.ca_table, provider=provider), "ca_table")
    mv = validate_identifier(_render(naming.materialized_view, provider=provider), "materialized_view")
    ca_id = validate_identifier(_render(naming.ca_id, provider=provider), "ca_id")

    attribute_tables = {}
    for attr_type in naming.attribute_types:
        validate_identifier(attr_type, "attribute_type")
        name = _render(naming.attribute_table, provider=provider, type=attr_type)
        attribute_tables[attr_type] = validate_identifier(name, "attribute_table")

    return ProviderSchema(
        provider=provider,
        ca_table=ca_table,
        materialized_view=mv,
        ca_id=ca_id,
        db_schema=db_schema,
        mnemonic=validate_identifier(naming.mnemonic, "mnemonic"),
        swift_code=validate_identifier(naming.swift_code, "swift_code"),
        attribute_name=validate_identifier(naming.attribute_name, "attribute_name"),
        attribute_value=validate_identifier(naming.attribute_value, "attribute_value"),
        attribute_tables=attribute_tables,
    )


def load_config(path) -> Dict:
    """Load a TOML config from a path that must live OUTSIDE the repo."""
    try:
        import tomllib as toml_reader  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
        import tomli as toml_reader

    with open(path, "rb") as fh:
        return toml_reader.load(fh)


def naming_from_config(config: Dict) -> Naming:
    if "naming" not in config or "columns" not in config:
        raise ConfigError("config must contain [naming] and [columns] tables")
    return Naming.from_dict(config["naming"], config["columns"])


def configured_providers(config: Dict) -> List[str]:
    """Providers declared under [providers.*] in the config."""
    return list(config.get("providers", {}).keys())


def _provider_section(config: Dict, provider: str) -> Dict:
    return config.get("providers", {}).get(provider, {})


def naming_for_provider(config: Dict, provider: str) -> Naming:
    """Shared [naming]/[columns] overlaid with any per-provider overrides in
    [providers.<provider>.naming] / [providers.<provider>.columns]."""
    if "naming" not in config or "columns" not in config:
        raise ConfigError("config must contain [naming] and [columns] tables")
    naming = dict(config["naming"])
    columns = dict(config["columns"])
    section = _provider_section(config, provider)
    naming.update(section.get("naming", {}))
    columns.update(section.get("columns", {}))
    return Naming.from_dict(naming, columns)


def provider_rules_path(config: Dict, provider: str):
    """The ruleset JSON path declared for a provider, if any."""
    return _provider_section(config, provider).get("rules")
