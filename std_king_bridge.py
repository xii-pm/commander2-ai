"""A narrow two-command king duel on a fully observed local board.

The kings have a unique passable common neighbor, already owned by us. A
packet larger than the enemy king plus four fills that bridge. If the rival
attacks the bridge, its garrison and our packet decrease together; otherwise
the packet still exceeds the next king garrison. The unique bridge blocks a
two-command counterattack on our king. All other visible hostiles invalidate
this pattern, as does an unknown cell within three passable steps of home or
two passable steps of the target (which could hide a last-minute reinforcement).

This is a conditional public-board argument. It does not certify arbitrary
fog positions, general two-step minimax, or unobserved long-range game rules.
"""
from collections import deque

from std_geometry import KING, MARSH, BLOCKED


def plan(bot):
    if not bot.config.get('king_bridge',False) or len(bot.enemies) != 1:
        return None
    target=bot.enemies[0]
    if bot.cells[target][0] != KING or target in bot.neighbors[bot.home]:
        return None
    # Unknown terrain may conceal another approach, so require the entire
    # local passable ball, not just the two cells in the proposed command.
    for origin,radius in ((bot.home,3),(target,2)):
        distance={origin:0}
        queue=deque([origin])
        while queue:
            p=queue.popleft()
            if distance[p] == radius:
                continue
            for n in bot.neighbors[p]:
                if n in distance:
                    continue
                if n not in bot.cells:
                    return None
                if bot.cells[n][0] in BLOCKED:
                    continue
                distance[n]=distance[p]+1
                queue.append(n)
    common=set(bot.neighbors[bot.home]) & set(bot.neighbors[target])
    common={p for p in common if p in bot.cells and bot.cells[p][0] not in BLOCKED}
    if len(common) != 1:
        return None
    stage=next(iter(common))
    if bot.cells[stage][1] != bot.army or bot.cells[stage][0] == MARSH:
        return None
    required=bot.cells[target][2]+5-bot.cells[stage][2]
    guard=max(2,bot.config.get('king_bridge_guard',8))
    if required <= 0 or required > bot.cells[bot.home][2]-guard:
        return None
    return dict(target=target,route=[bot.home,stage,target],packet=required,
        guard=guard,funded=True,enemy=bot.cells[target][2],
        bridge_force=bot.cells[stage][2]+required,
        model='isolated king; unique bridge; observed home radius3 and target radius2')


def propose(bot,choices,bridge):
    if bridge:
        choices.append((1000000,bot.home,bridge['route'][1],bridge['packet'],
                        'bridge_king',bridge['target']))
