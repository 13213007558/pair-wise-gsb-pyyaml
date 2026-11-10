
__all__ = [
    'SourceLocation',
    'MergeSource',
    'SourceInfo',
    'SourceIndex',
    'SourceIndexSafeLoader',
    'safe_load_with_source',
    'safe_load_all_with_source',
    'format_path',
    'parse_path',
]

import collections.abc

from .nodes import *
from .loader import SafeLoader
from .events import AliasEvent


class SourceLocation(object):
    """A buffer-independent pointer into the source stream.

    Only the stream name and numeric position are retained; the full source
    text is never copied, so enabling the index does not keep the stream
    alive.
    """

    __slots__ = ('name', 'index', 'line', 'column')

    def __init__(self, mark):
        self.name = mark.name
        self.index = mark.index
        self.line = mark.line
        self.column = mark.column

    def __repr__(self):
        return 'SourceLocation(name=%r, line=%d, column=%d)' % (
            self.name, self.line + 1, self.column + 1)

    def __eq__(self, other):
        return (
            isinstance(other, SourceLocation)
            and self.name == other.name
            and self.index == other.index
            and self.line == other.line
            and self.column == other.column
        )

    def __hash__(self):
        return hash((self.name, self.index, self.line, self.column))


class MergeSource(object):
    """Where a mapping entry came from through a YAML ``<<`` merge.

    ``anchor`` is set when the merged mapping was referenced through an
    alias. ``reference`` points at the merge/alias usage and ``definition``
    at the merged mapping itself.
    """

    __slots__ = ('anchor', 'reference', 'definition')

    def __init__(self, anchor, reference, definition):
        self.anchor = anchor
        self.reference = reference
        self.definition = definition

    def __repr__(self):
        return 'MergeSource(anchor=%r, reference=%r, definition=%r)' % (
            self.anchor, self.reference, self.definition)


class SourceInfo(object):
    """Provenance of the effective value at one runtime path."""

    __slots__ = (
        'path', 'key_location', 'value_location', 'definition_location',
        'is_alias', 'anchor', 'alias_reference', 'merge', 'overrides',
    )

    def __init__(self, path, key_location, value_location, definition_location,
            is_alias=False, anchor=None, alias_reference=None, merge=None,
            overrides=None):
        self.path = tuple(path)
        self.key_location = key_location
        self.value_location = value_location
        self.definition_location = definition_location
        self.is_alias = is_alias
        self.anchor = anchor
        self.alias_reference = alias_reference
        self.merge = merge
        self.overrides = overrides if overrides is not None else []

    def __repr__(self):
        return 'SourceInfo(path=%s, anchor=%r, is_alias=%r, line=%d)' % (
            format_path(self.path), self.anchor, self.is_alias,
            self.value_location.line + 1)


def format_path(path):
    """Render a runtime path as a stable human-readable string."""
    text = '$'
    for element in path:
        if isinstance(element, bool):
            text += '[%r]' % element
        elif isinstance(element, str):
            if element and all(
                    char.isalnum() or char in '_-' for char in element):
                text += '.' + element
            else:
                text += '[' + repr(element) + ']'
        elif isinstance(element, int):
            text += '[%d]' % element
        elif element is None:
            text += '[null]'
        else:
            text += '[' + repr(element) + ']'
    return text


def parse_path(text):
    """Parse the output of :func:`format_path` back into a path tuple.

    Accepted forms are ``$.a.b``, ``['a b']``, ``[0]`` and ``[null]``.
    """
    if not text or text[0] != '$':
        raise ValueError('path must start with $: %r' % text)
    path = []
    index = 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == '.':
            index += 1
            start = index
            while index < length and text[index] not in '.[ ':
                index += 1
            path.append(text[start:index])
        elif char == '[':
            index += 1
            if index < length and text[index] in ("'", '"'):
                quote = text[index]
                index += 1
                start = index
                while index < length and text[index] != quote:
                    index += 1
                path.append(text[start:index])
                index += 1
            elif text[index:index + 4] == 'null':
                path.append(None)
                index += 4
            else:
                start = index
                while index < length and text[index] != ']':
                    index += 1
                path.append(int(text[start:index]))
            if index >= length or text[index] != ']':
                raise ValueError('unterminated path segment: %r' % text)
            index += 1
        else:
            raise ValueError('unexpected character %r in path %r'
                    % (char, text))
    return tuple(path)


class SourceIndex(object):
    """Maps every runtime path of a loaded document to its source info."""

    def __init__(self, stream_name, entries):
        self.stream_name = stream_name
        self._entries = entries

    def lookup(self, *path):
        """Return :class:`SourceInfo` for a runtime path, or ``None``."""
        return self._entries.get(tuple(path))

    def paths(self):
        """All indexed runtime paths, in construction order."""
        return list(self._entries)

    def __len__(self):
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def __contains__(self, path):
        return tuple(path) in self._entries


_MERGE_TAG = 'tag:yaml.org,2002:merge'
_VALUE_TAG = 'tag:yaml.org,2002:value'
_STR_TAG = 'tag:yaml.org,2002:str'


class SourceIndexSafeLoader(SafeLoader):
    """Pure-Python ``SafeLoader`` that also builds a source index.

    The constructed Python object is identical to a normal
    :class:`SafeLoader` result, including shared object identity for
    aliases; the index is kept entirely outside of user data.
    """

    def __init__(self, stream):
        super().__init__(stream)
        # Alias reference sites keyed by the syntactic parent edge that
        # contains them: (parent node id, target node id) -> FIFO of alias
        # records. An anchor definition and its aliases resolve to the same
        # node object; definition edges are tracked separately so the
        # definition walk never consumes an alias record, while each alias
        # edge resolves to its own reference site.
        self._source_alias_edges = collections.defaultdict(collections.deque)
        self._source_definition_edges = set()
        # Subset of the alias edges used as ``<<`` merge sources.
        self._source_merge_edges = collections.defaultdict(collections.deque)
        self._source_anchor_names = {}

    def compose_document(self):
        # Snapshot anchor names before Composer.compose_document clears
        # self.anchors at the end of the document.
        anchors = dict(self.anchors)
        document = super().compose_document()
        for anchor, anchored_node in anchors.items():
            self._source_anchor_names[id(anchored_node)] = anchor
        return document

    def compose_node(self, parent, index):
        if not self.check_event(AliasEvent):
            # Peek once so a plain node costs only the override frame itself.
            anchor = self.peek_event().anchor
            node = super().compose_node(parent, index)
            if anchor is not None:
                self._source_anchor_names[id(node)] = anchor
                if parent is not None:
                    self._source_definition_edges.add(
                        (id(parent), id(node)))
            return node
        event = self.peek_event()
        node = super().compose_node(parent, index)
        if parent is not None:
            record = (
                event.anchor,
                SourceLocation(event.start_mark),
                SourceLocation(node.start_mark),
            )
            edge = (id(parent), id(node))
            self._source_alias_edges[edge].append(record)
            self._source_merge_edges[edge].append(record)
        return node

    def get_single_data(self):
        node = self.get_single_node()
        if node is None:
            return None, SourceIndex(self.name, {})
        index = self._build_source_index(node)
        data = self.construct_document(node)
        return data, index

    def get_data(self):
        if not self.check_node():
            return None
        node = self.get_node()
        index = self._build_source_index(node)
        data = self.construct_document(node)
        return data, index

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------
    def _build_source_index(self, root):
        entries = collections.OrderedDict()
        # Explicit work stack instead of Python recursion so deeply nested or
        # self-referential documents cannot blow the call stack. Each frame
        # carries the ancestor node ids on its own branch, which terminates
        # recursive aliases while still indexing a node reached through
        # several non-cyclic references at every runtime path.
        stack = [(root, (), None, None, None, None, frozenset())]
        while stack:
            (node, path, parent, key_location, merge, overrides,
                    ancestors) = stack.pop()
            self._index_value(
                node, path, parent, key_location, merge, overrides,
                ancestors, entries, stack)
        return SourceIndex(self.name, entries)

    def _take_edge_alias(self, parent, node):
        edge = (id(parent), id(node))
        if edge in self._source_definition_edges:
            # The anchor definition on this edge is not an alias; consume the
            # definition marker once and leave alias queues untouched.
            self._source_definition_edges.discard(edge)
            return None
        queue = self._source_alias_edges.get(edge)
        if queue:
            return queue.popleft()
        return None

    def _take_merge_alias(self, parent, node):
        queue = self._source_merge_edges.get((id(parent), id(node)))
        if queue:
            return queue.popleft()
        return None

    def _peek_merge_alias(self, parent, node):
        queue = self._source_merge_edges.get((id(parent), id(node)))
        if queue:
            return queue[0]
        return None

    def _anchor_name(self, node):
        return self._source_anchor_names.get(id(node))

    def _index_value(self, node, path, parent, key_location, merge,
            overrides, ancestors, entries, stack):
        node_id = id(node)
        cyclic = node_id in ancestors
        # Values inherited through a merge are covered by the merge
        # provenance rather than reported as direct alias references. A
        # recursive alias is still resolved so its reference site is known;
        # only the re-expansion of its contents is skipped below.
        alias = None
        if merge is None and parent is not None:
            alias = self._take_edge_alias(parent, node)
        is_alias = alias is not None
        anchor = alias[0] if is_alias else self._anchor_name(node)
        value_location = SourceLocation(node.start_mark)
        definition_location = alias[2] if is_alias else value_location
        entries[path] = SourceInfo(
            path, key_location, value_location, definition_location,
            is_alias=is_alias, anchor=anchor,
            alias_reference=alias[1] if is_alias else None, merge=merge,
            overrides=overrides if overrides is not None else [])
        if cyclic:
            # A recursive alias points back at an ancestor; record the path
            # but do not expand its contents again.
            return
        child_ancestors = ancestors | {node_id}
        if isinstance(node, SequenceNode):
            for position in range(len(node.value) - 1, -1, -1):
                stack.append((
                    node.value[position], path + (position,), node, None,
                    None, None, child_ancestors))
        elif isinstance(node, MappingNode):
            self._enqueue_mapping(node, path, child_ancestors, entries, stack)

    def _enqueue_mapping(self, node, path, ancestors, entries, stack):
        effective, shadows = self._resolve_mapping(node)
        # Reverse so popping restores construction order.
        for key in reversed(list(effective)):
            key_node, value_node, merge, key_location, owner = effective[key]
            stack.append((
                value_node, path + (key,), owner, key_location, merge,
                shadows.get(key), ancestors))

    def _resolve_mapping(self, node):
        explicit = []
        merge_specs = []
        for key_node, value_node in node.value:
            if key_node.tag == _MERGE_TAG:
                merge_specs.append((key_node, value_node))
            else:
                explicit.append((key_node, value_node))

        effective = collections.OrderedDict()
        shadows = collections.defaultdict(list)

        for merge_key_node, merge_value_node in merge_specs:
            merge_alias = self._take_merge_alias(node, merge_value_node)
            for owner, pair, candidate_alias in self._collect_merge_pairs(
                    merge_value_node, merge_alias):
                key_node, value_node = pair
                key = self._construct_key(key_node)
                if not isinstance(key, collections.abc.Hashable):
                    continue
                if key in effective:
                    shadows[key].append(self._shadow_record(
                        owner, value_node, candidate_alias))
                    continue
                effective[key] = (
                    key_node, value_node,
                    self._merge_source(owner, candidate_alias),
                    SourceLocation(key_node.start_mark), owner)

        for key_node, value_node in explicit:
            key = self._construct_key(key_node)
            if not isinstance(key, collections.abc.Hashable):
                continue
            if key in effective:
                prev = effective.pop(key)
                shadows[key].insert(0, self._shadow_from_merge(
                    prev[1], prev[2]))
            effective[key] = (
                key_node, value_node, None,
                SourceLocation(key_node.start_mark), node)
        return effective, shadows

    def _collect_merge_pairs(self, merge_value_node, merge_alias):
        """Yield (owner mapping node, (key node, value node), alias) tuples."""
        if isinstance(merge_value_node, MappingNode):
            for pair in merge_value_node.value:
                if pair[0].tag == _MERGE_TAG:
                    nested_alias = self._take_merge_alias(
                        merge_value_node, pair[1])
                    for item in self._collect_merge_pairs(
                            pair[1], nested_alias):
                        yield item
                else:
                    yield merge_value_node, pair, merge_alias
        elif isinstance(merge_value_node, SequenceNode):
            for subnode in merge_value_node.value:
                sub_alias = self._take_merge_alias(merge_value_node, subnode)
                if isinstance(subnode, MappingNode):
                    for pair in subnode.value:
                        if pair[0].tag == _MERGE_TAG:
                            nested_alias = self._take_merge_alias(
                                subnode, pair[1])
                            for item in self._collect_merge_pairs(
                                    pair[1], nested_alias):
                                yield item
                        else:
                            yield subnode, pair, sub_alias

    def _merge_source(self, owner, alias):
        anchor = alias[0] if alias is not None else self._anchor_name(owner)
        reference = alias[1] if alias is not None else SourceLocation(
            owner.start_mark)
        return MergeSource(anchor, reference,
                SourceLocation(owner.start_mark))

    def _shadow_from_merge(self, value_node, merge_source):
        if merge_source is not None:
            return {
                'anchor': merge_source.anchor,
                'reference': merge_source.reference,
                'value_location': SourceLocation(value_node.start_mark),
            }
        return {
            'anchor': None,
            'reference': None,
            'value_location': SourceLocation(value_node.start_mark),
        }

    def _shadow_record(self, owner, value_node, alias):
        if alias is None and owner is not None:
            alias = self._peek_merge_alias(owner, value_node)
        if alias is not None:
            return {
                'anchor': alias[0],
                'reference': alias[1],
                'value_location': SourceLocation(value_node.start_mark),
            }
        return {
            'anchor': self._anchor_name(owner),
            'reference': SourceLocation(owner.start_mark),
            'value_location': SourceLocation(value_node.start_mark),
        }
    def _construct_key(self, key_node):
        # Resolve a mapping key without driving the document constructor:
        # calling construct_object here would populate constructed_objects
        # ahead of construct_document and deepen the call stack for recursive
        # aliases. Scalar keys cover every hashable safe-load key; complex
        # keys fall back to their raw value and remain uniquely identifiable.
        if not isinstance(key_node, ScalarNode):
            return ('__node__', id(key_node))
        tag = key_node.tag
        if tag == _VALUE_TAG:
            return key_node.value
        resolver = self.yaml_implicit_resolvers
        constructor = self.yaml_constructors.get(tag)
        if constructor is not None and tag.startswith('tag:yaml.org,2002:'):
            try:
                return constructor(self, key_node)
            except Exception:
                return key_node.value
        return key_node.value


def safe_load_with_source(stream):
    """Safely load one document and return ``(data, source_index)``."""
    loader = SourceIndexSafeLoader(stream)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def safe_load_all_with_source(stream):
    """Yield ``(data, source_index)`` for every document in the stream."""
    loader = SourceIndexSafeLoader(stream)
    try:
        while loader.check_data():
            yield loader.get_data()
    finally:
        loader.dispose()
