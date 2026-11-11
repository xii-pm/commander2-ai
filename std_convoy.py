"""Finite current-stock rescue when the earliest deficit is already unfunded.

Adapted from the shared-road collection model. This is a best-effort fallback,
not a survival certificate: a currently lethal opponent may attack before the
convoy arrives. A concrete sequence prevents replanning from postponing arrival
forever. Every transfer must be observed and its remaining suffix funded anew.
"""
from std_geometry import MARSH
from std_merge import merge_schedule


def signature(order):
    return order['src'], order['dst'], order['sent']


def prepare(bot):
    bot._convoy_options = {}
    active = getattr(bot, '_rescue_convoy', None)
    if not bot.config.get('infeasible_convoy', False):
        bot._rescue_convoy = None
        return
    if active and active.get('awaiting'):
        observed = getattr(bot, '_observed_pending', None)
        if (observed and signature(observed) == active['moves'][0]
                and getattr(bot, '_last_order_confirmed', False)):
            active['moves'] = active['moves'][1:]
            active['awaiting'] = False
        elif bot.pending:
            return
        else:
            active = None
    if active and (not active['moves'] or bot.tick >= active['expires']):
        active = None
    bot._rescue_convoy = active


def funded(bot, moves):
    units = {p: bot.cells[p][2] for p in bot.owned}
    for src, dst, amount in moves:
        if (src == bot.home or src not in units or dst not in units
                or dst not in bot.neighbors[src]
                or bot.cells[src][0] == MARSH or bot.cells[dst][0] == MARSH
                or amount <= 0 or amount > units[src]-1):
            return False
        units[src] -= amount
        units[dst] += amount
    return True


def propose(bot, choices):
    if (not bot.config.get('infeasible_convoy', False)
            or getattr(bot, '_opening_contact', False)):
        return
    shortages = bot.last_report.get('defense_shortages', [])
    if not shortages or shortages[0][0] > 2:
        bot._rescue_convoy = None
        return
    horizon, shortage = shortages[0]
    _, distance = bot.owned_tree(bot.home)
    stock = sum(max(0, bot.cells[p][2]-1) for p in bot.owned
                if p != bot.home and distance.get(p, 999) <= horizon)
    # Even this optimistic stock ignores competition between donor commands.
    # If it could cover the imminent gap, preserve the ordinary rescue policy.
    if stock >= shortage:
        bot._rescue_convoy = None
        return
    budget = bot.config.get('convoy_budget', 6)
    active = getattr(bot, '_rescue_convoy', None)
    if bot.config.get('sparse_rescue_convoy', False) and not active:
        # Allow one extra command of near rescue before abandoning a useful
        # current sequence. This optimistic stock is a severity heuristic,
        # not a feasible schedule or a survival certificate. Once a convoy is
        # started, moving its payload closer must not itself cancel its suffix.
        near_stock = sum(max(0, bot.cells[p][2]-1) for p in bot.owned
                         if p != bot.home and distance.get(p, 999) <= horizon+1)
        bot.last_report['rescue_convoy_severity'] = dict(
            deadline=horizon, shortage=shortage, near_stock=near_stock,
            near_window=horizon+1, coverage_denominator=4,
            permits_new_convoy=4*near_stock < shortage)
        if 4*near_stock >= shortage:
            return
    if active and (active.get('awaiting') or not funded(bot, active['moves'])):
        if active.get('awaiting'):
            return
        active = None
        bot._rescue_convoy = None
    if active:
        moves = active['moves']
        force = sum(n for _, dst, n in moves if dst == bot.home)
        cost = len(moves)
    else:
        reserves = {p: 1 for p in bot.owned}
        plans = [(force, cost, tuple(moves)) for force, cost, moves in
                 merge_schedule(bot.neighbors, bot.cells, bot.army,
                                bot.home, reserves, budget)
                 if funded(bot, moves)]
        # A tiny nearby packet is still preferable to a transport with no
        # meaningful payload. This gate is an efficiency heuristic only.
        near = max([0]+[max(0, bot.cells[p][2]-1) for p in bot.owned
                       if p != bot.home and distance.get(p, 999) == 1])
        plans = [p for p in plans if p[0] >= max(8, 3*near)]
        if not plans:
            return
        covered = [p for p in plans if p[0] >= shortage]
        force, cost, moves = (min(covered, key=lambda p: (p[1], -p[0], p[2]))
                              if covered else max(plans, key=lambda p: (p[0], -p[1], p[2])))
    first = moves[0]
    bot._convoy_options[first] = dict(moves=moves,
        expires=active['expires'] if active else bot.tick+2*budget+2,
        awaiting=False)
    choices.append((14000+min(shortage, force)/float(cost),
                    first[0], first[1], first[2], 'defend', bot.home))
    bot.last_report['rescue_convoy'] = dict(earliest_deadline=horizon,
        shortage=shortage, optimistic_near_stock=stock, delivered=force,
        commands=cost, moves=moves, continuing=bool(active),
        limitation='Earliest deficit unfunded; opponent can attack before arrival.')


def committed(bot, src, dst, amount, mode):
    active = getattr(bot, '_rescue_convoy', None)
    move = (src, dst, amount)
    option = getattr(bot, '_convoy_options', {}).get(move) if mode == 'defend' else None
    if option:
        bot._rescue_convoy = dict(option, awaiting=True)
    elif active:
        # An interruption must not silently advance or reuse the old schedule.
        bot._rescue_convoy = None
