"""Strict duplicate-key checking for the pure-Python SafeLoader.

Run with:  python examples/strict-duplicate-keys/demo.py

It walks three short permission configs in this directory:
  1. an explicit duplicate key is rejected with both source locations,
  2. an explicit key legally overrides a merged default,
  3. competing merge sources resolve in convention order.

Strict mode is opt-in: safe_load() keeps its historical behaviour unless
strict_duplicate_keys=True (or yaml.StrictSafeLoader is used).
"""
import pathlib

import yaml
from yaml.constructor import ConstructorError

HERE = pathlib.Path(__file__).parent


def show(title, value):
    print(title)
    print("-" * len(title))
    print(str(value).rstrip())
    print()


def load_strict(filename):
    with (HERE / filename).open() as stream:
        return yaml.safe_load(stream, strict_duplicate_keys=True)


def main():
    # 1. Explicit conflict: error names the config file and both source lines.
    try:
        load_strict("01-conflict.yaml")
    except ConstructorError as error:
        show("1. Explicit conflict (strict)", error)
    else:
        raise AssertionError("expected a duplicate-key ConstructorError")

    # 2. Legal override: the explicit key wins over the merged default.
    show("2. Legal override of a merged default",
         load_strict("02-override.yaml")["role"])

    # 3. Competing sources: the earlier source wins the shared `write` key.
    show("3. Competing merge sources, earlier source wins",
         load_strict("03-competing-sources.yaml")["role"])

    # Default mode stays compatible and silently keeps the last occurrence.
    with (HERE / "01-conflict.yaml").open() as stream:
        show("Default mode stays compatible (last occurrence wins)",
             yaml.safe_load(stream)["role"])


if __name__ == "__main__":
    main()
