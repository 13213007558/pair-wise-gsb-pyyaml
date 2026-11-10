import datetime
import math
import re

import pytest

import yaml
from yaml import JSONSafeLoader, SafeLoader, json_safe_load, json_safe_load_all
from yaml.resolver import JSONSchemaResolver, Resolver


# --------------------------------------------------------------------------
# YAML 1.2 JSON schema lexical resolution
# --------------------------------------------------------------------------

SCALAR_CASES = [
    # null
    ("null", None),
    ("Null", None),
    ("NULL", None),
    # JSON booleans
    ("true", True),
    ("True", True),
    ("TRUE", True),
    ("false", False),
    ("False", False),
    ("FALSE", False),
    # plain decimal integers (no leading zero)
    ("0", 0),
    ("42", 42),
    ("-7", -7),
    ("+3", 3),
    # JSON-style floats
    ("1.5", 1.5),
    ("-1.5", -1.5),
    ("5.", 5.0),
    ("0.0", 0.0),
    ("1e3", 1000.0),
    ("1E3", 1000.0),
    ("2.5e-2", 0.025),
    ("-2.5E+2", -250.0),
]


def _load_scalar(text):
    # Wrap the scalar as a mapping value so empty scalars can be expressed.
    return yaml.load("value: " + text, Loader=JSONSafeLoader)["value"]


@pytest.mark.parametrize("text,expected", SCALAR_CASES)
def test_json_scalars_resolve(text, expected):
    result = _load_scalar(text)
    assert result == expected
    if isinstance(expected, float):
        assert isinstance(result, float)


def test_empty_scalar_is_none():
    assert _load_scalar("") is None
    assert yaml.load("a:\nb: x", Loader=JSONSafeLoader) == {"a": None, "b": "x"}


# Values that the JSON schema must leave as strings (failsafe str resolution).
STRING_CASES = [
    # YAML 1.1 booleans
    "on", "On", "ON", "off", "Off", "OFF", "yes", "Yes", "YES",
    "no", "No", "NO",
    # YAML 1.1 null shorthand
    "~",
    # timestamps / dates
    "2026-11-10", "2026-11-10T12:30:00Z",
    # octal / hexadecimal / sexagesimal / leading-zero numbers
    "017", "0o17", "0O17", "0x1f", "0b101", "12:30:00", "1:30",
    # special floats
    ".inf", ".Inf", ".INF", "-.inf", ".nan", ".NaN", ".NAN",
    # leading-dot fraction is not valid JSON number
    ".5",
]


@pytest.mark.parametrize("text", STRING_CASES)
def test_non_json_scalars_stay_strings(text):
    result = yaml.load(text, Loader=JSONSafeLoader)
    assert result == text
    assert isinstance(result, str)


def test_special_floats_are_not_float():
    data = yaml.load("a: .inf\nb: .nan\nc: -.inf", Loader=JSONSafeLoader)
    assert data == {"a": ".inf", "b": ".nan", "c": "-.inf"}
    assert all(isinstance(v, str) for v in data.values())


def test_underscored_numbers_stay_strings():
    # Underscores are a YAML 1.1 / core-schema convenience, not JSON lexical.
    data = yaml.load("a: 1_000\nb: 1_000.5", Loader=JSONSafeLoader)
    assert data == {"a": "1_000", "b": "1_000.5"}


# --------------------------------------------------------------------------
# Mapping keys use the same rules as values
# --------------------------------------------------------------------------

def test_mapping_keys_follow_same_rules():
    data = yaml.load(
        "true: 1\n"
        "42: two\n"
        "on: three\n"
        "017: four\n"
        "2026-11-10: five\n",
        Loader=JSONSafeLoader,
    )
    assert data == {True: 1, 42: "two", "on": "three",
                    "017": "four", "2026-11-10": "five"}


def test_nested_mapping_keys_and_values():
    data = yaml.load(
        "outer:\n"
        "  017:\n"
        "    on: 1.5\n"
        "  true:\n"
        "    - 42\n"
        "    - off\n",
        Loader=JSONSafeLoader,
    )
    assert data == {
        "outer": {
            "017": {"on": 1.5},
            True: [42, "off"],
        }
    }
    assert isinstance(list(data["outer"])[0], str)


# --------------------------------------------------------------------------
# Explicit tags still go through the safe constructor
# --------------------------------------------------------------------------

def test_explicit_safe_tags_construct():
    data = yaml.load(
        "a: !!int '42'\n"
        "b: !!float '1.5'\n"
        "c: !!bool 'true'\n"
        "d: !!str on\n"
        "e: !!null ''\n"
        "f: !!timestamp 2026-11-10\n"
        "g: !!seq [1, 2]\n"
        "h: !!map {x: 1}\n",
        Loader=JSONSafeLoader,
    )
    assert data["a"] == 42 and isinstance(data["a"], int)
    assert data["b"] == 1.5 and isinstance(data["b"], float)
    assert data["c"] is True
    assert data["d"] == "on" and isinstance(data["d"], str)
    assert data["e"] is None
    assert data["f"] == datetime.date(2026, 11, 10)
    assert data["g"] == [1, 2]
    assert data["h"] == {"x": 1}


def test_explicit_tag_overrides_string_resolution():
    # A value that would be a plain string under JSON rules can be forced to a
    # number with an explicit tag.
    data = yaml.load("a: !!int '017'\nb: !!float '.5'", Loader=JSONSafeLoader)
    assert data == {"a": 15, "b": 0.5}


@pytest.mark.parametrize("payload", [
    "!!python/object/apply:os.system ['echo pwned']",
    "!!python/name:os.system",
    "!!python/object/new:dict {a: 1}",
    "!!python/module:os",
])
def test_python_tags_are_rejected(payload):
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load(payload, Loader=JSONSafeLoader)


def test_unknown_tag_is_rejected():
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("!no-such-tag x", Loader=JSONSafeLoader)


# --------------------------------------------------------------------------
# Isolation from the legacy SafeLoader / global resolver table
# --------------------------------------------------------------------------

def test_resolver_tables_are_separate_objects():
    assert JSONSchemaResolver.yaml_implicit_resolvers is not \
        Resolver.yaml_implicit_resolvers


def test_legacy_resolver_is_unchanged():
    # SafeLoader keeps all YAML 1.1 behaviour.
    assert yaml.load("on", Loader=SafeLoader) is True
    assert yaml.load("yes", Loader=SafeLoader) is True
    assert yaml.load("017", Loader=SafeLoader) == 15
    assert yaml.load("0x1f", Loader=SafeLoader) == 31
    assert yaml.load("2026-11-10", Loader=SafeLoader) == datetime.date(2026, 11, 10)
    assert math.isinf(yaml.load(".inf", Loader=SafeLoader))


def test_interleaving_loaders_does_not_pollute():
    for _ in range(3):
        assert yaml.load("on: 017", Loader=SafeLoader) == {True: 15}
        assert yaml.load("on: 017", Loader=JSONSafeLoader) == {"on": "017"}


def test_subclass_resolver_addition_does_not_leak():
    class MySafe(SafeLoader):
        pass

    MySafe.add_implicit_resolver(
        "tag:yaml.org,2002:str", re.compile(r"^(custom)$"), ["c"]
    )
    assert yaml.load("custom", Loader=MySafe) == "custom"
    # Neither the JSON loader nor the base SafeLoader gained the entry.
    leaked = any(
        regex.pattern == r"^(custom)$"
        for entries in JSONSchemaResolver.yaml_implicit_resolvers.values()
        for _tag, regex in entries
    )
    assert not leaked
    assert yaml.load("on", Loader=JSONSafeLoader) == "on"
    assert yaml.load("on", Loader=SafeLoader) is True


def test_json_loader_is_pure_python():
    # The JSON loader must not pull in the libyaml C parser; it composes the
    # same pure-Python machinery as SafeLoader.
    from yaml.reader import Reader
    from yaml.scanner import Scanner
    assert issubclass(JSONSafeLoader, Reader)
    assert issubclass(JSONSafeLoader, Scanner)
    assert not JSONSafeLoader.__module__.startswith("yaml._yaml")


# --------------------------------------------------------------------------
# Public convenience API and multi-document streams
# --------------------------------------------------------------------------

def test_convenience_functions():
    assert json_safe_load("a: on\nb: 42") == {"a": "on", "b": 42}
    docs = list(json_safe_load_all("a: 1\n---\na: 2\n"))
    assert docs == [{"a": 1}, {"a": 2}]


def test_merge_key_still_works():
    data = yaml.load(
        "base: &b {a: 1, b: 2}\n"
        "child:\n"
        "  <<: *b\n"
        "  b: 3\n",
        Loader=JSONSafeLoader,
    )
    assert data["child"] == {"a": 1, "b": 3}
