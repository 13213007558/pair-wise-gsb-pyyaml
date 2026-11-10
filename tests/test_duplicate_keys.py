import pytest

import yaml
from yaml.constructor import ConstructorError


# A short permission config that exercises every merge outcome in one place.
# Line numbers are asserted on, so start at line 1 with no leading newline.
PERMISSION_CONFIG = """\
defaults: &defaults
  read: true
  write: false
  admin: false
viewer: &viewer
  <<: *defaults
  write: false
role:
  <<: [*defaults, *viewer]
  write: true
"""

EXPLICIT_CONFLICT = """\
role:
  write: true
  write: false
"""

PARSED_EQUALITY_CONFLICT = """\
role:
  1: viewer
  0x1: admin
"""


def strict_loaders():
    # The strict check lives in the pure-Python SafeLoader only.
    return [yaml.StrictSafeLoader]


@pytest.mark.parametrize("Loader", strict_loaders())
def test_default_mode_keeps_last_occurrence(Loader):
    assert yaml.load(EXPLICIT_CONFLICT, Loader=yaml.SafeLoader) == {
        "role": {"write": False}
    }


@pytest.mark.parametrize("Loader", strict_loaders())
def test_explicit_duplicate_key_reports_both_locations(Loader):
    with pytest.raises(ConstructorError) as excinfo:
        yaml.load(EXPLICIT_CONFLICT, Loader=Loader)
    error = excinfo.value
    assert error.problem == "found duplicate key 'write'"
    # The repeated occurrence is the problem mark ...
    assert (error.problem_mark.line, error.problem_mark.column) == (2, 2)
    # ... and the first occurrence is preserved as a separate source location.
    assert (error.first_mark.line, error.first_mark.column) == (1, 2)
    rendered = str(error)
    assert "line 3, column 3" in rendered
    assert "first occurrence of the key, line 2, column 3" in rendered


def test_safe_load_keyword_enables_strict_check():
    with pytest.raises(ConstructorError):
        yaml.safe_load(EXPLICIT_CONFLICT, strict_duplicate_keys=True)
    assert yaml.safe_load(EXPLICIT_CONFLICT) == {"role": {"write": False}}


@pytest.mark.parametrize("Loader", strict_loaders())
def test_explicit_key_overrides_merged_default(Loader):
    result = yaml.load(PERMISSION_CONFIG, Loader=Loader)
    # The explicit `write: true` wins over every merged default.
    assert result["role"] == {
        "read": True,
        "write": True,
        "admin": False,
    }


@pytest.mark.parametrize("Loader", strict_loaders())
def test_multiple_merge_sources_keep_convention_order(Loader):
    source = (
        "first: &first {x: 1, y: 1}\n"
        "second: &second {y: 2, z: 2}\n"
        "role:\n"
        "  <<: [*first, *second]\n"
    )
    result = yaml.load(source, Loader=Loader)["role"]
    # Earlier merge source wins for a shared key; both contribute unique keys.
    assert result == {"x": 1, "y": 1, "z": 2}


@pytest.mark.parametrize("Loader", strict_loaders())
def test_duplicate_decided_after_construction_not_on_text(Loader):
    with pytest.raises(ConstructorError) as excinfo:
        yaml.load(PARSED_EQUALITY_CONFLICT, Loader=Loader)
    error = excinfo.value
    assert error.problem == "found duplicate key 1"
    assert error.first_mark.line == 1
    assert error.problem_mark.line == 2
    # Distinct key types that merely look alike remain legal.
    assert yaml.load("role:\n  1: a\n  '1': b\n", Loader=Loader) == {
        "role": {1: "a", "1": "b"}
    }


@pytest.mark.parametrize("Loader", strict_loaders())
def test_unhashable_key_still_raises_constructor_error(Loader):
    with pytest.raises(ConstructorError) as excinfo:
        yaml.load("role:\n  [a, b]: x\n", Loader=Loader)
    error = excinfo.value
    assert error.problem == "found unhashable key"
    assert error.problem_mark.line == 1
    assert not isinstance(excinfo.value, TypeError)


@pytest.mark.parametrize("Loader", strict_loaders())
@pytest.mark.parametrize(
    "source",
    [
        # The same anchored mapping merged twice is not an explicit duplicate.
        "base: &base {x: 1, y: 2}\n"
        "role:\n  <<: *base\n  <<: *base\n  z: 3\n",
        # Nested merges that reuse the same nodes repeatedly.
        "a0: &a0 {k0: 0}\n"
        "a1: &a1\n  <<: [*a0, *a0]\n  k1: 1\n"
        "role:\n  <<: [*a1, *a1]\n  k2: 2\n",
        # One node referenced as a value in several places.
        "shared: &shared {a: 1}\n"
        "role:\n  one: *shared\n  two: *shared\n",
    ],
)
def test_shared_and_nested_merges_remain_valid(Loader, source):
    yaml.load(source, Loader=Loader)


@pytest.mark.parametrize("Loader", strict_loaders())
def test_duplicate_inside_anchored_mapping_is_still_rejected(Loader):
    source = (
        "base: &base\n"
        "  x: 1\n"
        "  x: 2\n"
        "role:\n  <<: *base\n"
    )
    with pytest.raises(ConstructorError) as excinfo:
        yaml.load(source, Loader=Loader)
    assert excinfo.value.problem_mark.line == 2


@pytest.mark.parametrize("Loader", strict_loaders())
def test_check_is_independent_of_load_order(Loader):
    # Repeated construction must give the same answer regardless of which
    # branch of the shared anchor is encountered first.
    source = (
        "base: &base {x: 1}\n"
        "a:\n  <<: *base\n  y: 2\n"
        "b:\n  y: 2\n  <<: *base\n"
    )
    first = yaml.load(source, Loader=Loader)
    second = yaml.load(source, Loader=Loader)
    assert first == second
    assert first["a"] == {"x": 1, "y": 2}
    assert first["b"] == {"x": 1, "y": 2}


def test_safe_load_all_strict_flag():
    documents = list(
        yaml.safe_load_all("a: 1\n---\nb: 2\n", strict_duplicate_keys=True)
    )
    assert documents == [{"a": 1}, {"b": 2}]
    with pytest.raises(ConstructorError):
        list(
            yaml.safe_load_all(
                "a: 1\n---\na: 1\na: 2\n", strict_duplicate_keys=True
            )
        )
