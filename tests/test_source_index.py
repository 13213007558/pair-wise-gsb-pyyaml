import pytest

import yaml
from yaml import (
    safe_load,
    safe_load_with_source,
    safe_load_all_with_source,
    format_path,
    parse_path,
)
from yaml.source import (
    SourceIndex,
    SourceInfo,
    SourceLocation,
    MergeSource,
    SourceIndexSafeLoader,
)


ALIAS_DOC = """\
tpl: &t
  action: drop
  nested: {x: 1}
a: *t
b: *t
seq:
  - *t
  - null
  - 1
  - true
1: intkey
true: boolkey
~: nullkey
"""


def test_loaded_value_and_identity_match_safe_load():
    data, index = safe_load_with_source(ALIAS_DOC)
    assert data == safe_load(ALIAS_DOC)
    assert data["a"] is data["b"] is data["seq"][0] is data["tpl"]
    assert isinstance(index, SourceIndex)


def test_index_is_not_embedded_in_user_data():
    data, index = safe_load_with_source(ALIAS_DOC)
    assert not hasattr(data, "__yaml_source__")
    assert not hasattr(data["tpl"], "__yaml_source__")
    assert not hasattr(data["seq"], "__yaml_source__")


def test_every_alias_reference_keeps_its_own_site():
    data, index = safe_load_with_source(ALIAS_DOC)
    refs = [
        index.lookup("a"),
        index.lookup("b"),
        index.lookup("seq", 0),
    ]
    assert all(info.is_alias for info in refs)
    assert all(info.anchor == "t" for info in refs)
    # Distinct reference locations, all pointing at the same definition.
    reference_lines = [info.alias_reference.line for info in refs]
    assert len(set(reference_lines)) == 3
    definition_lines = {info.definition_location.line for info in refs}
    assert definition_lines == {index.lookup("tpl").value_location.line}
    # The anchor definition itself is not reported as an alias.
    assert index.lookup("tpl").is_alias is False
    assert index.lookup("tpl").anchor == "t"


def test_nested_value_through_alias_points_at_definition():
    data, index = safe_load_with_source(ALIAS_DOC)
    info = index.lookup("a", "nested", "x")
    assert info.value_location.line == 2  # line 3 in 1-based terms
    assert index.lookup("tpl", "nested", "x").value_location == \
        info.value_location


def test_sequence_null_and_typed_key_paths():
    data, index = safe_load_with_source(ALIAS_DOC)
    assert format_path(("seq", 2)) == "$.seq[2]"
    assert index.lookup("seq", 1).value_location is not None  # null entry
    assert format_path((1,)) == "$[1]"
    assert format_path((True,)) == "$[True]"
    assert format_path((None,)) == "$[null]"
    assert parse_path("$.seq[2]") == ("seq", 2)
    assert parse_path("$[null]") == (None,)
    assert parse_path("$['a b']") == ("a b",)


def test_equivalent_keys_report_only_effective_source():
    # int 1 and bool True hash equally; the later key wins, matching
    # plain PyYAML dict construction.
    data, index = safe_load_with_source(ALIAS_DOC)
    assert 1 in data and True in data and data[True] == "boolkey"
    assert index.lookup(1) is index.lookup(True)
    assert index.lookup(True).value_location.line + 1 == 12


MERGE_DOC = """\
defaults: &default_rule
  action: drop
  log: true

auth:
  rules:
    - <<: *default_rule
      resource: /admin
    - <<: *default_rule
      resource: /reports
      action: allow
    - <<: *default_rule
      resource: /public
"""


def test_merge_provenance_points_at_owner_and_reference():
    data, index = safe_load_with_source(MERGE_DOC)
    action = index.lookup("auth", "rules", 0, "action")
    assert data["auth"]["rules"][0]["action"] == "drop"
    assert isinstance(action.merge, MergeSource)
    assert action.merge.anchor == "default_rule"
    # Reference is the ``<<: *default_rule`` line; definition is the anchor.
    assert action.merge.reference.line + 1 == 7
    assert action.merge.definition.line + 1 == 1
    assert action.value_location.line + 1 == 2

def test_explicit_override_records_shadowed_merge_value():
    data, index = safe_load_with_source(MERGE_DOC)
    effective = index.lookup("auth", "rules", 1, "action")
    assert data["auth"]["rules"][1]["action"] == "allow"
    assert effective.value_location.line + 1 == 11
    assert effective.merge is None
    assert len(effective.overrides) == 1
    shadow = effective.overrides[0]
    assert shadow["anchor"] == "default_rule"
    assert shadow["value_location"].line + 1 == 2
    assert shadow["reference"].line + 1 == 9


def test_unoverridden_merge_has_no_shadows():
    data, index = safe_load_with_source(MERGE_DOC)
    inherited = index.lookup("auth", "rules", 2, "action")
    assert inherited.overrides == []
    assert inherited.merge.anchor == "default_rule"


def test_merge_sequence_precedence_records_all_losers():
    doc = """\
base_a: &a
  k: from_a
base_b: &b
  k: from_b
target:
  <<: [*a, *b]
  k: explicit
"""
    data, index = safe_load_with_source(doc)
    assert data["target"]["k"] == "explicit"
    info = index.lookup("target", "k")
    anchors = [shadow["anchor"] for shadow in info.overrides]
    assert anchors == ["a", "b"]


def test_source_location_does_not_retain_buffer():
    data, index = safe_load_with_source("x: 1\n")
    location = index.lookup("x").value_location
    assert isinstance(location, SourceLocation)
    assert not hasattr(location, "buffer")
    assert not hasattr(location, "pointer")


def test_empty_document():
    data, index = safe_load_with_source("")
    assert data is None
    assert len(index) == 0
    assert index.paths() == []


def test_safe_load_all_with_source():
    documents = list(safe_load_all_with_source("x: 1\n---\ny: 2\n"))
    assert len(documents) == 2
    assert documents[0][0] == {"x": 1}
    assert documents[1][0] == {"y": 2}
    assert documents[1][1].lookup("y").value_location.line + 1 == 3


def test_plain_safe_load_builds_no_index():
    data = safe_load("x: 1\n")
    assert data == {"x": 1}
    assert not hasattr(data, "__source_index__")


def test_loader_is_pure_python_safe_loader():
    assert issubclass(SourceIndexSafeLoader, yaml.SafeLoader)


def test_recursive_alias_terminates_and_keeps_reference():
    doc = "&a\n  x: 1\n  y: *a\n"
    data, index = safe_load_with_source(doc)
    # Avoid a whole-tree equality check: under pytest's deeper call stack the
    # self-referential dict can hit the recursion limit while printing or
    # comparing. Identity and scalar assertions cover the same contract.
    assert data["x"] == 1
    assert data["y"] is data
    back_ref = index.lookup("y")
    assert back_ref.is_alias is True
    assert back_ref.anchor == "a"
    # The cyclic path is recorded, and its contents remain queryable through
    # the non-cyclic definition path.
    assert index.lookup("x").value_location.line + 1 == 2


def test_shared_anchor_indexed_at_every_runtime_path():
    doc = "t: &t\n  k: 1\na: *t\nb: *t\n"
    data, index = safe_load_with_source(doc)
    assert data["a"] is data["b"] is data["t"]
    for path in (("t", "k"), ("a", "k"), ("b", "k")):
        info = index.lookup(*path)
        assert info is not None
        assert info.value_location.line + 1 == 2
    assert index.lookup("t").is_alias is False
    assert index.lookup("a").is_alias is True
    assert index.lookup("b").is_alias is True


def test_inline_merge_without_alias_reports_owner():
    doc = "target:\n  <<: {k: v}\n  extra: 2\n"
    data, index = safe_load_with_source(doc)
    assert data == safe_load(doc)
    info = index.lookup("target", "k")
    assert isinstance(info.merge, MergeSource)
    assert info.merge.anchor is None
    assert info.value_location.line + 1 == 2


def test_nested_merge_resolves_transitive_owner():
    doc = (
        "a: &a\n  x: 1\n"
        "b: &b\n  <<: *a\n  y: 2\n"
        "c:\n  <<: *b\n  z: 3\n"
    )
    data, index = safe_load_with_source(doc)
    assert data == safe_load(doc)
    assert data["c"]["x"] == 1
    info = index.lookup("c", "x")
    assert info.value_location.line + 1 == 2
