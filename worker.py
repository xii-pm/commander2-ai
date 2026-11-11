"""Observation-only JSONL adapter. Shares the exact SDK Agent and settings."""
import json
import sys
from time import perf_counter, process_time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bfs_agent import Agent
from std_geometry import OFFSETS


def main():
    agent = None
    print(json.dumps({'ready': 1}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        obs = request['observation']
        rows, cols, army = obs['rows'], obs['cols'], obs['army']
        if obs.get('observer_seat', army) != army or len(obs['cells']) != rows * cols:
            raise ValueError('Invalid observation identity or size')
        if agent is None:
            agent = Agent(army, rows, cols)
        if (agent.rows, agent.cols, agent.army) != (rows, cols, army):
            raise ValueError('Observation identity changed during an episode')
        cells = {divmod(i, cols): tuple(d) for i, d in enumerate(obs['cells'])
                 if d[0] != 0 and d[1] >= 0}
        # Only public hill silhouettes enter the policy. No king_hints/map truth.
        started, cpu = perf_counter(), process_time()
        order = agent.decide(cells, hill_hints={tuple(p) for p in obs.get('hill_hints', [])})
        agent.last_report['decision_ms'] = (perf_counter()-started)*1000
        agent.last_report['cpu_ms'] = (process_time()-cpu)*1000
        action, orders = 0, []
        if order:
            src, dst, amount = order
            direction = next(i for i, (dr, dc) in enumerate(OFFSETS[src[0] & 1])
                             if (src[0] + dr, src[1] + dc) == dst)
            action = 1 + (src[0] * cols + src[1]) * 6 + direction
            if not obs['action_mask'][action] or type(amount) is not int or amount <= 0:
                raise ValueError('Policy returned an illegal order')
            orders = [[army, src[0], src[1], dst[0], dst[1], amount]]
        print(json.dumps(dict(id=request['id'], action=action, orders=orders or None,
                              order=orders[0] if orders else None, debug=agent.last_report)), flush=True)


if __name__ == '__main__':
    main()
