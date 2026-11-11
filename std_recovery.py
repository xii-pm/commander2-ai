"""Short, fully funded king recovery after an observed large interception.

This bounded task repays a specific exchange, rather than continuously chasing
a growing fraction of the whole army. Routes are recomputed on each observation.
"""
from math import ceil

from std_reinforcement import select_cover
from std_geometry import KING, FORT


def observe(bot):
    limit = bot.config.get('recovery_max_producers',0)
    if limit and sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned) > limit:
        bot._exchange_recovery = None
        return
    previous = getattr(bot, '_observed_pending', None)
    active = getattr(bot, '_exchange_recovery', None)
    if active and bot.tick > active['until']:
        bot._exchange_recovery = None
    if (not previous or previous['src'] != bot.home
            or previous['role'] != 'intercept' or previous['sent'] < 8
            or getattr(bot, '_opening_contact', True) is not False):
        return
    key = previous['tick'], previous['src'], previous['dst']
    if key == getattr(bot, '_recovery_exchange_key', None):
        return
    # Only an actually observed capture starts a recovery window.
    if previous['dst'] not in bot.cells or bot.cells[previous['dst']][1] != bot.army:
        return
    bot._recovery_exchange_key = key
    share = int(ceil(sum(bot.cells[p][2] for p in bot.owned)
                     *bot.config.get('guard_share',18)/100.0))
    target = min(previous['before_src'][2], max(8, share))
    bot._exchange_recovery = dict(target=target, until=bot.tick+5,
                                 exchange=key, sent=previous['sent'])


def propose(bot, choices):
    active = getattr(bot, '_exchange_recovery', None)
    if not active or bot.tick > active['until']:
        return
    gap = active['target']-bot.cells[bot.home][2]
    if gap <= 0:
        return
    parent, distance = bot.owned_tree(bot.home)
    budget = min(4, active['until']-bot.tick+1)
    donors = []
    for src in bot.owned:
        steps = distance.get(src,999)
        if src == bot.home or steps > budget:
            continue
        amount = max(0,bot.cells[src][2]-max(1,bot.counter(src)+1))
        route = list(reversed(bot.path(parent,src)))
        empty = sum(bot.cells[p][2] == 0 for p in route[1:-1])
        payload = amount-empty
        if payload > 0:
            donors.append((src,steps,amount,payload,empty))
    selected, force, commands = select_cover([(d[1],d[3]) for d in donors],budget,gap)
    bot.last_report['exchange_recovery'] = dict(target=active['target'],gap=gap,
        until=active['until'],budget=budget,delivered=force,commands=commands,
        funded=force >= gap)
    if force < gap or not selected:
        return
    src,steps,amount,payload,empty = max((donors[i] for i in selected),
                                      key=lambda d:(d[3]/float(d[1]),-d[1],d[0]))
    amount = min(amount,gap+empty)
    choices.append((13100+gap/float(max(1,commands)),src,parent[src],amount,
                    'defend',bot.home))
