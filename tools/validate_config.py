"""Validate a Commander-II strategy configuration file.

Usage:
    python tools/validate_config.py [path/to/parameters.json]

Exits with status 1 (and a readable message) on any invalid configuration.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from std_config import DEFAULTS, validate  # noqa: E402


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else ROOT / 'parameters.json'
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        print('missing configuration file: {}'.format(path))
        return 1
    except ValueError as exc:
        print('{}: not valid JSON: {}'.format(path, exc))
        return 1

    if not isinstance(raw, dict):
        print('{}: top level must be a JSON object'.format(path))
        return 1

    try:
        resolved = validate(raw)
    except ValueError as exc:
        print('{}: INVALID - {}'.format(path, exc))
        return 1

    changed = [k for k in sorted(DEFAULTS) if resolved[k] != DEFAULTS[k]]
    print('{}: OK'.format(path))
    print('  known settings : {}'.format(len(DEFAULTS)))
    print('  overrides      : {}'.format(len(changed)))
    print('  enabled flags  : {}'.format(
        sum(1 for k in changed if isinstance(DEFAULTS[k], bool) and resolved[k])))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
