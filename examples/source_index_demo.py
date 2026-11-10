"""Demo: jump from a validation error to the real YAML source of a value.

Run:  .venv/bin/python examples/source_index_demo.py

The configuration has one anchored default permission block, two plain
alias references, one merge-based reuse, and one local override. When
validation rejects ``auth.rules[2].action``, the source index reports both
the reference site (where the value is used) and the definition site (where
it is actually written), so a reviewer can decide whether to fix the shared
default or only the current usage point.
"""

import yaml
from yaml import safe_load_with_source, format_path


CONFIG = """\
defaults: &default_rule
  action: drop          # line 2: definition of the default action
  log: true

templates:
  readonly: *default_rule        # line 6: plain alias reference (1)

auth:
  rules:
    - <<: *default_rule          # line 10: merge reuse with local override
      resource: /admin
      action: allow
    - <<: *default_rule          # line 13: merge reuse, default kept
      resource: /reports
    - *default_rule              # line 15: plain alias reference (2)
"""

ALLOWED_ACTIONS = {"allow", "deny"}


def validate(config, index):
    errors = []
    for position, rule in enumerate(config["auth"]["rules"]):
        path = ("auth", "rules", position, "action")
        info = index.lookup(*path)
        if rule["action"] not in ALLOWED_ACTIONS:
            errors.append((path, rule["action"], info))
    return errors


def nearest_alias(index, path):
    """Walk up from ``path`` to the closest entry reached through an alias."""
    for depth in range(len(path), 0, -1):
        info = index.lookup(*path[:depth])
        if info is not None and info.is_alias:
            return info
    return None


def explain(path, value, info, index):
    print("validation error: %s = %r is not a legal action"
            % (format_path(path), value))
    print("  effective value written at line %d column %d"
            % (info.value_location.line + 1, info.value_location.column + 1))
    alias_info = nearest_alias(index, path)
    if alias_info is not None:
        print("  used via alias %r at line %d column %d"
                % (alias_info.anchor, alias_info.alias_reference.line + 1,
                   alias_info.alias_reference.column + 1))
        print("  anchor defined at line %d column %d"
                % (alias_info.definition_location.line + 1,
                   alias_info.definition_location.column + 1))
    if info.merge is not None:
        print("  inherited through merge of anchor %r" % info.merge.anchor)
        print("  merge reference at line %d column %d"
                % (info.merge.reference.line + 1,
                   info.merge.reference.column + 1))
        print("  merged mapping defined at line %d column %d"
                % (info.merge.definition.line + 1,
                   info.merge.definition.column + 1))
    for shadow in info.overrides:
        print("  shadowed candidate anchor=%r value at line %d"
                % (shadow["anchor"], shadow["value_location"].line + 1))
    print("  -> edit the anchor definition to change every reuse, or the")
    print("     reference/override site to change only this usage point.")


def main():
    config, index = safe_load_with_source(CONFIG)
    print("loaded config (identical to yaml.safe_load):")
    print(yaml.safe_dump(config, sort_keys=False), end="\n")
    for path, value, info in validate(config, index):
        explain(path, value, info, index)


if __name__ == "__main__":
    main()
