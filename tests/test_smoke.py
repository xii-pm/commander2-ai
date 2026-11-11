"""End-to-end smoke tests that need no Commander-II SDK.

The agent is driven exactly like the platform does it: a full board of cells
with visibility already applied by the caller, plus the public HILL hints.
`worker.py` is additionally exercised over its JSONL protocol.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bfs_agent import Agent  # noqa: E402
from std_geometry import BLANK, FORT, KING, hex_distance  # noqa: E402

ROWS = COLS = 24
SPAWN = (3, 11)
ENEMY_SPAWN = (15, 5)


def empty_board():
    return {(row, col): (BLANK, 0, 0)
            for row in range(ROWS) for col in range(COLS)}


def observation(cells, hints=()):
    """Build one JSONL observation in the platform's encoding."""
    flat = [list(cells[(row, col)]) for row in range(ROWS) for col in range(COLS)]
    return {
        'rows': ROWS,
        'cols': COLS,
        'army': 1,
        'observer_seat': 1,
        'cells': flat,
        'hill_hints': [list(h) for h in hints],
        'action_mask': [True] * (ROWS * COLS * 6 + 1),
        'action': 0,
    }


class DecideTest(unittest.TestCase):
    def setUp(self):
        board = empty_board()
        board[SPAWN] = (KING, 1, 30)
        board[(4, 11)] = (FORT, 1, 6)
        board[(5, 12)] = (BLANK, 1, 4)
        board[ENEMY_SPAWN] = (KING, 2, 12)
        self.board = board

    def test_decide_returns_one_legal_order(self):
        agent = Agent(1, ROWS, COLS)
        move = agent.decide(dict(self.board), hill_hints=set())
        self.assertIsNotNone(move)
        src, dst, amount = move
        self.assertIn(src, self.board)
        self.assertIn(dst, self.board)
        self.assertEqual(hex_distance(src, dst), 1)
        self.assertIs(type(amount), int)
        self.assertGreaterEqual(amount, 1)
        self.assertEqual(self.board[src][1], 1)

    def test_decide_is_deterministic_for_the_same_observation(self):
        first = Agent(1, ROWS, COLS).decide(dict(self.board), hill_hints=set())
        second = Agent(1, ROWS, COLS).decide(dict(self.board), hill_hints=set())
        self.assertEqual(first, second)

    def test_report_is_json_serialisable(self):
        agent = Agent(1, ROWS, COLS)
        agent.decide(dict(self.board), hill_hints={(0, 0)})
        json.dumps(agent.last_report, ensure_ascii=False)

    def test_agent_does_not_import_the_platform_sdk(self):
        source = (ROOT / 'bfs_agent.py').read_text(encoding='utf-8')
        self.assertNotIn('import Commander', source)
        self.assertNotIn('from Commander', source)


class WorkerProtocolTest(unittest.TestCase):
    """Drive worker.py through its stdin/stdout JSONL contract."""

    def run_worker(self, payloads, timeout=120):
        process = subprocess.Popen(
            [sys.executable, '-B', 'worker.py'],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',  # tracebacks may carry a non-UTF-8 path on Windows
        )
        stdout, stderr = process.communicate(
            '\n'.join(json.dumps(p) for p in payloads) + '\n', timeout=timeout)
        self.assertEqual(process.returncode, 0, stderr)
        return [json.loads(line) for line in stdout.splitlines() if line.strip()]

    def test_ready_then_one_decision(self):
        board = empty_board()
        board[SPAWN] = (KING, 1, 30)
        board[(4, 11)] = (FORT, 1, 6)
        board[ENEMY_SPAWN] = (KING, 2, 12)
        # The worker announces readiness by itself; stdin only carries requests.
        payloads = [{'id': 7, 'observation': observation(board)}]
        replies = self.run_worker(payloads)
        self.assertEqual(replies[0], {'ready': 1})
        decision = replies[1]
        self.assertEqual(decision['id'], 7)
        self.assertIsInstance(decision['action'], int)
        self.assertGreaterEqual(decision['action'], 0)
        if decision['order'] is not None:
            self.assertEqual(len(decision['order']), 6)

    def test_invalid_observation_size_is_rejected(self):
        payloads = [{'id': 1, 'observation': {'rows': 2, 'cols': 2, 'army': 1,
                                             'observer_seat': 1, 'cells': [[1, 0, 0]],
                                             'hill_hints': [],
                                             'action_mask': [True] * 25}}]
        process = subprocess.Popen(
            [sys.executable, '-B', 'worker.py'], cwd=str(ROOT),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace')
        stdout, stderr = process.communicate(
            '\n'.join(json.dumps(p) for p in payloads) + '\n', timeout=120)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('ValueError', stderr)


if __name__ == '__main__':
    unittest.main()
