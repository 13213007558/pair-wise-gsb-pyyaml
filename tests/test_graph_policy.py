import pytest

import yaml
from yaml.graphpolicy import GraphAdmissionPolicy, GraphPolicyError


def load_with_policy(source, max_expanded_nodes, multi=False):
    policy = GraphAdmissionPolicy(max_expanded_nodes)
    loader = yaml.SafeLoader(source, graph_policy=policy)
    try:
        if multi:
            data = []
            while loader.check_data():
                data.append(loader.get_data())
        else:
            data = loader.get_single_data()
    finally:
        loader.dispose()
    return data, policy


def test_policy_requires_positive_limit():
    with pytest.raises(ValueError):
        GraphAdmissionPolicy(0)
    with pytest.raises(ValueError):
        GraphAdmissionPolicy("100")


def test_diamond_sharing_is_admitted_and_structure_preserved():
    data, policy = load_with_policy("""
shared: &s [1, 2, 3]
first: *s
second: *s
""", max_expanded_nodes=16)

    assert data["first"] is data["shared"]
    assert data["second"] is data["shared"]

    report = policy.last_report
    assert report.source_nodes == 8
    assert report.alias_references == 2
    assert report.shared_nodes == 8
    assert report.expanded_nodes == 16


def test_diamond_sharing_over_limit_is_rejected():
    with pytest.raises(GraphPolicyError):
        load_with_policy("""
shared: &s [1, 2, 3]
first: *s
second: *s
""", max_expanded_nodes=15)


def test_report_explains_why_sharing_stays_within_limit():
    _, policy = load_with_policy("""
shared: &s [1, 2, 3]
first: *s
second: *s
""", max_expanded_nodes=100)

    explanation = policy.last_report.explain()
    assert "8 source node(s)" in explanation
    assert "2 alias reference(s)" in explanation
    assert "16 node(s)" in explanation
    assert "limit is 100" in explanation


def test_direct_cycle_is_rejected():
    with pytest.raises(GraphPolicyError, match="cycle"):
        load_with_policy("a: &a [*a]\n", max_expanded_nodes=100)


def test_indirect_cycle_is_rejected():
    with pytest.raises(GraphPolicyError, match="cycle"):
        load_with_policy("a: &a {k: &b [1, *a]}\n", max_expanded_nodes=100)


def test_merge_references_are_counted():
    data, policy = load_with_policy("""
base: &base {x: 1, y: 2}
derived:
  <<: *base
  z: 3
""", max_expanded_nodes=17)

    assert data["derived"] == {"x": 1, "y": 2, "z": 3}
    report = policy.last_report
    assert report.source_nodes == 12
    assert report.alias_references == 1
    assert report.shared_nodes == 5
    assert report.expanded_nodes == 17


def test_merge_references_over_limit_are_rejected():
    with pytest.raises(GraphPolicyError):
        load_with_policy("""
base: &base {x: 1, y: 2}
derived:
  <<: *base
  z: 3
""", max_expanded_nodes=16)


def test_nested_sequences_accumulate_expansion_cost():
    data, policy = load_with_policy("""
a: &a [1, 2]
b: &b [*a, *a]
c: [*b, *b]
""", max_expanded_nodes=29)

    assert data["c"][0] is data["b"]
    assert data["b"][0] is data["a"]
    report = policy.last_report
    assert report.source_nodes == 9
    assert report.alias_references == 4
    assert report.shared_nodes == 20
    assert report.expanded_nodes == 29


def test_nested_sequences_over_limit_are_rejected():
    with pytest.raises(GraphPolicyError):
        load_with_policy("""
a: &a [1, 2]
b: &b [*a, *a]
c: [*b, *b]
""", max_expanded_nodes=28)


def test_graph_state_resets_between_documents():
    data, policy = load_with_policy(
        "root: &x [1, 2]\n"
        "---\n"
        "root: &x 5\n"
        "again: *x\n",
        max_expanded_nodes=10,
        multi=True,
    )

    assert data == [{"root": [1, 2]}, {"root": 5, "again": 5}]
    assert len(policy.reports) == 2
    first, second = policy.reports
    assert first.document_index == 1
    assert first.source_nodes == 5
    assert first.expanded_nodes == 5
    assert second.document_index == 2
    assert second.source_nodes == 4
    assert second.alias_references == 1
    assert second.expanded_nodes == 5


def test_failed_document_does_not_leak_state_into_next_load():
    policy = GraphAdmissionPolicy(10)

    loader = yaml.SafeLoader("a: &a [*a]\n", graph_policy=policy)
    try:
        with pytest.raises(GraphPolicyError):
            loader.get_single_data()
    finally:
        loader.dispose()

    loader = yaml.SafeLoader("ok: true\n", graph_policy=policy)
    try:
        assert loader.get_single_data() == {"ok": True}
    finally:
        loader.dispose()
    assert policy.last_report.source_nodes == 3


def test_rejection_happens_before_constructors_run():
    calls = []

    class SideEffectLoader(yaml.SafeLoader):
        pass

    def construct_side_effect(loader, node):
        calls.append(node.value)
        return node.value

    SideEffectLoader.add_constructor("!sideeffect", construct_side_effect)

    policy = GraphAdmissionPolicy(10)
    loader = SideEffectLoader("""
a: &a [1, 2, 3]
b: [*a, *a, *a]
marker: !sideeffect boom
""", graph_policy=policy)
    try:
        with pytest.raises(GraphPolicyError):
            loader.get_single_data()
    finally:
        loader.dispose()

    assert calls == []


def doubling_chain_source(levels):
    lines = ["l0: &l0 [x]"]
    for level in range(1, levels+1):
        lines.append("l%d: &l%d [*l%d, *l%d]"
                % (level, level, level-1, level-1))
    lines.append("root: *l%d" % levels)
    return "\n".join(lines)


def test_expansion_is_estimated_without_materializing_it():
    levels = 30
    data, policy = load_with_policy(
        doubling_chain_source(levels), max_expanded_nodes=10**12)

    costs = [2]
    for _ in range(levels):
        costs.append(2*costs[-1]+1)
    expected_shared = sum(2*costs[level-1] for level in range(1, levels+1))
    expected_shared += costs[levels]

    report = policy.last_report
    assert report.source_nodes == 2*(levels+1) + 3
    assert report.alias_references == 2*levels + 1
    assert report.shared_nodes == expected_shared
    assert report.expanded_nodes == report.source_nodes + expected_shared
    assert data["root"] is data["l%d" % levels]


def test_doubling_chain_over_limit_is_stopped_early():
    with pytest.raises(GraphPolicyError, match="exceeds the limit"):
        load_with_policy(doubling_chain_source(30), max_expanded_nodes=1000)


def test_loader_without_policy_is_unchanged():
    loader = yaml.SafeLoader("a: &a [*a]\n")
    try:
        data = loader.get_single_data()
    finally:
        loader.dispose()
    assert data["a"][0] is data["a"]
