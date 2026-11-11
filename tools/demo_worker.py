"""Run the offline JSONL worker on a synthetic map and print its decision.

This demonstrates the deployment path without the Commander-II SDK:

    python tools/demo_worker.py

It starts `worker.py` exactly like an evaluation harness would, sends one
observation over stdin and decodes the reply.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = COLS = 24
BLANK, KING, FORT = 1, 2, 3

# A deliberately plain board: our King, one fort and one field stack, plus a
# visible enemy King. Terrain is encoded as the platform does it.
CELLS = [[BLANK, 0, 0] for _ in range(ROWS * COLS)]


def put(row, col, terrain, owner, units):
    CELLS[row * COLS + col] = [terrain, owner, units]


put(3, 11, KING, 1, 30)
put(4, 11, FORT, 1, 6)
put(5, 12, BLANK, 1, 4)
put(15, 5, KING, 2, 12)

OBSERVATION = {
    'rows': ROWS,
    'cols': COLS,
    'army': 1,
    'observer_seat': 1,
    'cells': CELLS,
    'hill_hints': [[0, 0], [0, 23]],
    'action_mask': [True] * (ROWS * COLS * 6 + 1),
    'action': 0,
}


def main():
    process = subprocess.Popen(
        [sys.executable, '-B', 'worker.py'],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',  # worker JSON is ASCII, but be tolerant of Windows paths
    )
    payload = json.dumps({'id': 1, 'observation': OBSERVATION}) + '\n'
    stdout, stderr = process.communicate(payload, timeout=180)
    if process.returncode != 0:
        print('worker failed:\n' + stderr)
        return 1

    lines = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    print('handshake   :', lines[0])
    reply = lines[1]
    print('action index:', reply['action'])
    print('order       :', reply['order'])
    report = reply.get('debug') or {}
    interesting = ('tick', 'mode', 'owned', 'units', 'home_keep', 'strategy_route',
                   'decision_ms', 'cpu_ms')
    print('report      :', {k: report.get(k) for k in interesting if k in report})
    return 0


if __name__ == '__main__':
    sys.exit(main())
