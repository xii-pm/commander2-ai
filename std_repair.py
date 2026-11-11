"""Bounded repair of a thin king after a confirmed, costly interception.

This preserves the useful insurance hypothesis behind old mobile warnings
without inventing a surviving hostile packet. It reuses current-stock merge
plans, proposes one ordinary transfer and leaves all orders to the arbiter.
"""
from std_geometry import KING, MARSH
from std_merge import merge_schedule


def prepare(bot):
    if not bot.config.get('post_intercept_repair', False):
        bot._post_intercept_repair = None
        return
    active = getattr(bot, '_post_intercept_repair', None)
    if active and (bot.calls-active['born'] >= 6 or active['home'] != bot.home
                   or bot.cells[bot.home][2] >= active['target']):
        active = None
    order = getattr(bot, '_observed_pending', None)
    if (order and getattr(bot, '_last_order_confirmed', False)
            and order['src'] == bot.home and order['role'] == 'intercept'
            and order['before_dst'][0] != KING
            and order['before_dst'][1] > 0 and order['before_dst'][1] != bot.army
            and bot.cells.get(order['dst'], (0, 0, 0))[1] == bot.army
            and not getattr(bot, '_opening_contact', False)):
        held = bot.cells[bot.home][2]
        target = max(2, (bot.home_keep+1)//2)
        signature = order['tick'], order['src'], order['dst'], order['sent']
        if (signature != getattr(bot, '_repair_last_interception', None)
                and held < target and order['sent'] >= held):
            active = dict(home=bot.home, born=bot.calls, target=target,
                interception=signature, residual_king=held, dispatch=order['sent'])
            bot._repair_last_interception = signature
    bot._post_intercept_repair = active


def trim_delivery(cells, army, root, keeps, moves, need):
    """Trim a funded sequence backwards, then verify every actual prefix.

    Only observed friendly stock is counted. Each retained source keeps its
    current hold; no future income, presumed combat or duplicated pickup pays
    for any transfer. Excess force remains in its original or transit cell.
    """
    if need <= 0:
        return ()
    stocks = {p: d[2] for p, d in cells.items() if d[1] == army}
    initial = dict(stocks)
    before = []
    for src, dst, amount in moves:
        if (src == root or src not in stocks or dst not in stocks
                or cells[src][0] == MARSH or cells[dst][0] == MARSH
                or amount <= 0 or amount > stocks[src]-keeps.get(src, 1)):
            return None
        before.append(stocks[dst])
        stocks[src] -= amount
        stocks[dst] += amount
    if stocks[root]-initial[root] < need:
        return None
    required = {root: initial[root]+need}
    reduced = []
    for (src, dst, amount), prior_destination in reversed(list(zip(moves, before))):
        packet = min(amount, max(0, required.get(dst, 0)-prior_destination))
        required[dst] = max(0, required.get(dst, 0)-packet)
        if packet:
            required[src] = max(required.get(src, 0), keeps.get(src, 1))+packet
            reduced.append((src, dst, packet))
    reduced.reverse()
    stocks = dict(initial)
    for src, dst, amount in reduced:
        if amount > stocks[src]-keeps.get(src, 1):
            return None
        stocks[src] -= amount
        stocks[dst] += amount
    return tuple(reduced) if stocks[root]-initial[root] == need else None


def affordable_interception(bot, choices, reserves, moves, need):
    """Defer staging insurance only while the existing king stock is safe.

    This returns an existing proposal, never creates or issues an attack.
    Actual observed friendly stock pays the capture and its source reserve.
    """
    if (not bot.config.get('repair_preserve_interception', False)
            or not moves or moves[0][1] == bot.home):
        return None
    held = bot.cells[bot.home][2]
    if any(force >= held for force in bot.threat_curve(len(moves))[1:]):
        return None
    eligible = []
    for choice in choices:
        score, src, dst, amount, role, target = choice
        cell = bot.cells.get(dst)
        source = bot.cells.get(src)
        if (role != 'intercept' or src == bot.home or not cell or not source
                or source[1] != bot.army or cell[0] == KING
                or cell[1] <= 0 or cell[1] == bot.army
                or bot.risk_dist.get(dst, 999) > 2
                or amount <= cell[2] or amount > need
                or source[2]-amount < max(1, reserves.get(src, 1), bot.counter(src, excluded=(dst,))+1)):
            continue
        if bot.config.get('patient_home_intercept', False):
            from std_patience import allowed
            if not allowed(bot, (src, dst, amount)):
                continue
        eligible.append(choice)
    return max(eligible) if eligible else None


def propose(bot, choices, reserves):
    active = getattr(bot, '_post_intercept_repair', None)
    if not active:
        return
    held = bot.cells[bot.home][2]
    need = active['target']-held
    if need <= 0:
        return
    keeps = {p: max(1, reserves.get(p, 1), bot.counter(p)+1) for p in bot.owned}
    options = []
    for force, cost, moves in merge_schedule(bot.neighbors, bot.cells, bot.army,
                                            bot.home, keeps, 6):
        if force < need:
            continue
        trimmed = trim_delivery(bot.cells, bot.army, bot.home, keeps, moves, need)
        if trimmed:
            options.append(trimmed)
    report = dict(held=held, target=active['target'], need=need,
        observations_since_interception=bot.calls-active['born'],
        interception=active['interception'], funded_options=len(options),
        trigger='confirmed home interception spent at least the residual king stock; king below half its existing reserve',
        model='current friendly stock and at most six commands; no surviving enemy packet is assumed')
    if options:
        moves = min(options, key=lambda m: (len(m), sum(p[2] for p in m), m))
        src, dst, amount = moves[0]
        report.update(commands=len(moves), moves=moves, delivered=need)
        interception = affordable_interception(bot, choices, reserves, moves, need)
        if interception is not None:
            report['deferred_for_interception'] = dict(source=interception[1],
                target=interception[2], amount=interception[3], score=interception[0],
                reason='existing affordable non-king interception within two moves; current king stock covers the staging horizon')
        else:
            choices.append((9000+need/float(len(moves)), src, dst, amount, 'guard_supply', bot.home))
    bot.last_report['post_intercept_repair'] = report
