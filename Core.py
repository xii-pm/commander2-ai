"""您说得队 / BFS统御: visible SDK adapter, Python 3.6 standard library only.

Deploy this entire folder. SDK and JSONL worker share bfs_agent.Agent.
"""
import json
import os
import time
from pathlib import Path
from Commander import AI_SDK, GameMap, Verification, NODE_TYPE
from bfs_agent import Agent, move_number

agent = None
trace = None


def Load():
    global agent, trace
    rows, cols = GameMap.GetSize()
    agent = Agent(Verification.GetArmyID(), rows, cols)
    if trace:
        trace.close()
    trace = None
    if os.environ.get('COMMANDER_BFS_TRACE') == '1':
        trace = Path(__file__).with_name('bfs-trace.jsonl').open('w', encoding='utf-8', buffering=1)


def Main():
    if agent is None:
        raise RuntimeError('Load must initialize Agent')
    started = time.perf_counter()
    kinds = (NODE_TYPE.BLANK, NODE_TYPE.KING, NODE_TYPE.FORT,
             NODE_TYPE.HILL, NODE_TYPE.OBSTACLE, NODE_TYPE.MARSH)
    cells, hints = {}, set()
    for x in range(agent.rows):
        for y in range(agent.cols):
            visible = GameMap.IsViewable(x, y)
            terrain = GameMap.GetType(x, y)
            if visible:
                cells[(x, y)] = (kinds.index(terrain) + 1,
                                 GameMap.GetBelong(x, y), GameMap.GetUnitNum(x, y))
            elif terrain == NODE_TYPE.HILL:
                hints.add((x, y))
    order = agent.decide(cells, hill_hints=hints)
    if order:
        src, dst, sent = order
        direction = next(d for d in range(6) if AI_SDK.DirectionToDestination(src[0], src[1], d) == dst)
        AI_SDK.MoveByDirection(src[0], src[1], move_number(cells[src][2], sent), direction)
    if trace:
        report = dict(agent.last_report)
        report['ms'] = round((time.perf_counter() - started) * 1000, 3)
        report['king_units'] = cells.get(agent.home, (0, 0, 0))[2]
        trace.write(json.dumps(report, ensure_ascii=False) + '\n')
