"""Price a tiny home interception while a recently seen stack is in fog.

The remembered force only scopes evaluation. Current public cells and current
authorized stock still fund each order. This does not activate another policy
or assume the remembered army remains at its old position.
"""
from std_geometry import KING, FORT
from std_skirmish import search


def propose(bot, choices):
    if (not bot.config.get('opening_memory_exchange', False)
            or not getattr(bot, '_opening_contact', False)
            or sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) != 1
            or not bot.enemies
            or any(bot.cells[p][0] == KING or bot.cells[p][2] > 1
                   for p in bot.enemies)):
        return
    if not choices:
        return
    _, src, dst, amount, mode, _ = max(choices)
    if (mode != 'intercept' or src != bot.home or dst not in bot.cells
            or bot.cells[dst][0] == KING or bot.cells[dst][2] > 3
            or amount != bot.cells[dst][2]+1
            or bot.cells[bot.home][2]-amount >= bot.home_keep):
        return
    recent = [dict(position=p, units=c[2], age=bot.tick-c[3],
                   risk_distance=bot.risk_dist.get(p, 999))
              for p, c in sorted(bot.memory.items())
              if p not in bot.cells and c[1] > 0 and c[1] != bot.army
              and c[2] >= 3 and 0 < bot.tick-c[3] <= 8
              and bot.risk_dist.get(p, 999) <= 4]
    if not recent:
        return
    tactical = search(bot, choices)
    if tactical:
        choices.append(tactical)
        bot.last_report['opening_memory_exchange'] = dict(
            recent_unseen=recent, public_search=bot.last_report.pop('skirmish'),
            policy_handoff=False, future_growth_funds=False)
