PyYAML
======

A full-featured YAML processing framework for Python

## Installation

To install, type `python setup.py install`.

By default, the `setup.py` script checks whether LibYAML is installed and if
so, builds and installs LibYAML bindings.
To skip the check and force installation of LibYAML bindings, use the option
`--with-libyaml`: `python setup.py --with-libyaml install`.
To disable the check and skip building and installing LibYAML bindings, use
`--without-libyaml`: `python setup.py --without-libyaml install`.

When LibYAML bindings are installed, you may use fast LibYAML-based parser and
emitter as follows:

    >>> yaml.load(stream, Loader=yaml.CLoader)
    >>> yaml.dump(data, Dumper=yaml.CDumper)

If you don't trust the input YAML stream, you should use:

    >>> yaml.safe_load(stream)

## Source index

The pure-Python safe loader can additionally return a source index that maps
each runtime path of the loaded value back to the YAML text it came from. The
loaded object is unchanged (including shared identity for aliases); the index
is kept separate and never embedded in the data, and no full copy of the
source text is retained.

    >>> data, index = yaml.safe_load_with_source(stream)
    >>> info = index.lookup("auth", "rules", 2, "action")
    >>> info.value_location.line          # where the effective value is written
    >>> info.alias_reference              # where an alias referenced it
    >>> info.definition_location          # where the anchor was defined
    >>> info.merge                        # provenance for `<<` merges
    >>> info.overrides                    # candidates shadowed by the winner

`info.is_alias` and `info.anchor` describe alias references, while
`yaml.format_path` / `yaml.parse_path` render and parse runtime paths
(including sequence indices, non-string keys, and null keys). See
`examples/source_index_demo.py` for a validation-error walkthrough.

## Testing

PyYAML includes a comprehensive test suite.

To run the complete local test suite, type:

    make test

This creates a local Python environment, runs the pure Python tests, builds a
local copy of LibYAML, and then runs the LibYAML extension tests. The local
LibYAML build is pinned by `LIBYAML-REF`, which defaults to `0.2.5`.

To run only one test mode:

    make test-python
    make test-libyaml

To test with a specific Python version:

    make test PYTHON-VERSION=3.13.5

## Further Information

* For more information, check the
  [PyYAML homepage](https://github.com/yaml/pyyaml).

* [PyYAML tutorial and reference](http://pyyaml.org/wiki/PyYAMLDocumentation).

* Discuss PyYAML with the maintainers on
  Matrix at https://matrix.to/#/#pyyaml:yaml.io or
  IRC #pyyaml irc.libera.chat

* Submit bug reports and feature requests to the
  [PyYAML bug tracker](https://github.com/yaml/pyyaml/issues).

## License

The PyYAML module was written by Kirill Simonov <xi@resolvent.net>.
It is currently maintained by the YAML and Python communities.

PyYAML is released under the MIT license.

See the file LICENSE for more details.
