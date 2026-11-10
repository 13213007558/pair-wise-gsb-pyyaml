
__all__ = ['GraphAdmissionPolicy', 'GraphReport', 'GraphPolicyError']

from .error import MarkedYAMLError

class GraphPolicyError(MarkedYAMLError):
    pass

class GraphReport:
    """Per-document accounting produced by a GraphAdmissionPolicy.

    ``source_nodes`` counts the nodes written in the document source.
    ``alias_references`` counts alias events and ``shared_nodes`` is the
    sum of the expansion costs of their targets, i.e. how many extra
    nodes the final tree expansion gains from sharing.  ``expanded_nodes``
    is the total size of that expansion; it is computed arithmetically,
    the expansion itself is never materialized.
    """

    def __init__(self, document_index, max_expanded_nodes):
        self.document_index = document_index
        self.max_expanded_nodes = max_expanded_nodes
        self.source_nodes = 0
        self.alias_references = 0
        self.shared_nodes = 0

    @property
    def expanded_nodes(self):
        return self.source_nodes + self.shared_nodes

    def explain(self):
        return ("document %d: %d source node(s); %d alias reference(s) "
                "account for %d shared node(s), so the final expansion "
                "holds %d node(s); the agreed limit is %d, therefore the "
                "shared structure is admitted without being materialized"
                % (self.document_index, self.source_nodes,
                   self.alias_references, self.shared_nodes,
                   self.expanded_nodes, self.max_expanded_nodes))

    def __repr__(self):
        return ("GraphReport(document_index=%r, source_nodes=%r, "
                "alias_references=%r, shared_nodes=%r, "
                "max_expanded_nodes=%r)"
                % (self.document_index, self.source_nodes,
                   self.alias_references, self.shared_nodes,
                   self.max_expanded_nodes))

class GraphAdmissionPolicy:
    """Optional admission policy for the node graph of a YAML document.

    Anchors and aliases let a small document describe a large object
    graph, and downstream consumers frequently expand the shared graph
    into a plain tree.  This policy estimates the size of that expansion
    while the graph is composed -- before any constructor runs -- and
    rejects documents whose expansion exceeds ``max_expanded_nodes``.

    An alias that refers to a fully composed node is legal sharing: the
    target's expansion cost is added to the document total once per
    reference, which matches the final expansion semantics exactly
    (expanded = source + sum of alias target costs) without copying the
    shared subgraph.  An alias that refers to a node still being composed
    is a cycle: its expansion would be infinite, so the document is
    rejected.  Seeing an anchor for the second time is therefore not, by
    itself, treated as a cycle.

    Merge keys need no special handling: ``flatten_mapping`` only
    re-references nodes that are already reachable through ordinary
    containment or alias edges, so the compose-time estimate is an upper
    bound for the post-merge expansion as well.  Nested sequences and
    mappings are covered by the same accounting.

    Graph state is reset for every document of a stream, including after
    a rejected document, so anchors and costs never leak into the next
    document.  The limit applies to each document individually.
    """

    def __init__(self, max_expanded_nodes):
        if not isinstance(max_expanded_nodes, int) \
                or isinstance(max_expanded_nodes, bool) \
                or max_expanded_nodes < 1:
            raise ValueError("max_expanded_nodes must be a positive integer")
        self.max_expanded_nodes = max_expanded_nodes
        self.reports = []
        self._reset_document_state()

    @property
    def last_report(self):
        if self.reports:
            return self.reports[-1]
        return None

    def _reset_document_state(self):
        self._report = None
        self._costs = {}
        self._open = set()
        self._stack = []

    def begin_document(self):
        self._reset_document_state()
        self._report = GraphReport(len(self.reports)+1,
                self.max_expanded_nodes)

    def end_document(self):
        if self._report is not None:
            self.reports.append(self._report)
        self._reset_document_state()

    def add_scalar(self, node):
        self._register_node(node, 1)

    def open_collection(self, node):
        self._open.add(node)
        self._stack.append([node, 1])

    def close_collection(self, node):
        entry = self._stack.pop()
        self._open.discard(entry[0])
        self._register_node(entry[0], entry[1])

    def alias(self, node, mark):
        if node in self._open:
            raise GraphPolicyError(None, None,
                    "found a cycle: alias refers to a node that is still "
                    "being composed", mark)
        cost = self._costs[node]
        report = self._report
        report.alias_references += 1
        report.shared_nodes += cost
        if self._stack:
            self._stack[-1][1] += cost
        self._check_limit(mark)

    def _register_node(self, node, cost):
        self._report.source_nodes += 1
        self._costs[node] = cost
        if self._stack:
            self._stack[-1][1] += cost
        self._check_limit(node.start_mark)

    def _check_limit(self, mark):
        report = self._report
        if report is not None \
                and report.expanded_nodes > self.max_expanded_nodes:
            raise GraphPolicyError(None, None,
                    "YAML graph expansion cost %d exceeds the limit of %d "
                    "node(s) (%d source node(s), %d shared node(s) from %d "
                    "alias reference(s))"
                    % (report.expanded_nodes, self.max_expanded_nodes,
                       report.source_nodes, report.shared_nodes,
                       report.alias_references),
                    mark)
