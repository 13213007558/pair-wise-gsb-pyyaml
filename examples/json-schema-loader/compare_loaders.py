"""
Compare SafeLoader (YAML 1.1 implicit resolution) against JSONSafeLoader
(YAML 1.2 JSON schema) on a realistic permissions configuration.

Run with the in-tree package:

    PYTHONPATH=lib python examples/json-schema-loader/compare_loaders.py
"""

import os

import yaml
from yaml import JSONSafeLoader, SafeLoader

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "permissions.yaml")


def typed(value):
    """Render a value together with its concrete Python type."""
    return f"{value!r}  [{type(value).__name__}]"


def walk(prefix, old, new, rows):
    if isinstance(old, dict) and isinstance(new, dict):
        # Match children positionally: keys may have different Python types
        # (e.g. octal int under SafeLoader vs. str under JSONSafeLoader).
        for (old_key, old_value), (new_key, new_value) in zip(
                old.items(), new.items()):
            path = f"{prefix}.{old_key}" if prefix else str(old_key)
            walk(path, old_value, new_value, rows)
    else:
        rows.append((prefix, old, new))


def main():
    with open(CONFIG, "r", encoding="utf-8") as stream:
        text = stream.read()

    old = yaml.load(text, Loader=SafeLoader)
    new = yaml.load(text, Loader=JSONSafeLoader)

    print("=== scalar value comparison ===")
    print(f"{'path':<34}{'SafeLoader (YAML 1.1)':<28}{'JSONSafeLoader (1.2)'}")
    print("-" * 92)
    rows = []
    walk("", old, new, rows)
    for path, old_value, new_value in rows:
        flag = "" if type(old_value) is type(new_value) and old_value == new_value else "  <-- changed"
        print(f"{path:<34}{typed(old_value):<28}{typed(new_value)}{flag}")

    print("\n=== mapping key comparison ===")
    print("quotas keys (SafeLoader):  ",
          [(k, type(k).__name__) for k in old["quotas"]])
    print("quotas keys (JSONSafe):    ",
          [(k, type(k).__name__) for k in new["quotas"]])

    print("\n=== nested key + explicit tag check ===")
    probe = yaml.load(
        "nested:\n"
        "  017:\n"
        "    on: 1.5\n"
        "forced_int: !!int '017'\n"
        "forced_str: !!str on\n",
        Loader=JSONSafeLoader,
    )
    nested_key = next(iter(probe["nested"]))
    print("nested key 017 ->", typed(nested_key))
    print("nested value on ->", typed(probe["nested"][nested_key]["on"]))
    print("!!int '017' ->", typed(probe["forced_int"]))
    print("!!str on ->", typed(probe["forced_str"]))

    print("\n=== explicit python tag stays rejected ===")
    try:
        yaml.load("!!python/object/apply:os.system ['echo no']",
                  Loader=JSONSafeLoader)
    except yaml.constructor.ConstructorError:
        print("!!python/object/apply rejected by the safe constructor")


if __name__ == "__main__":
    main()
