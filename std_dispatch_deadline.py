"""Resolve confirmed ordinary dispatch / long-horizon recall disagreements.

A latch needs two confirmed transfers on the same edge and the same public
threat curve at confirmation. The confirmed reserve cannot grow. Only ordinary planning
stock changes; tactical rescue and immediate king elimination remain intact.
"""


def floor(curve):
    return max([1]+[force-(h-1)//2 for h,force in enumerate(curve) if h])


def observe(bot):
    pending = getattr(bot, '_observed_pending', None)
    if not pending or not getattr(bot, '_last_order_confirmed', False):
        return
    latch = pending.get('deadline_return')
    if latch and tuple(bot.threat_curve(12)) == latch['curve']:
        bot._dispatch_deadline_latch = dict(latch)


def reserve(bot):
    latch = getattr(bot, '_dispatch_deadline_latch', None)
    if not latch:
        return 1
    curve = tuple(bot.threat_curve(12))
    if floor(curve) <= bot.home_keep:
        bot._dispatch_deadline_latch = None
        return 1
    keep = min(latch['keep'], floor(curve))
    bot.last_report['dispatch_deadline'] = dict(horizon=12, keep=keep,
        previous_keep=bot.home_keep, evidence='confirmed outflow and reverse rescue',
        first_conflict=latch['tick'])
    return keep


def committed(bot, src, dst, amount, mode):
    pending = bot.pending
    if not pending:
        return
    curve = tuple(bot.threat_curve(12))
    required = floor(curve)
    if (src == bot.home and bot.cells.get(dst, (0,0,0))[1] == bot.army
            and mode not in ('defend','intercept','finish_king','tactical','skirmish')
            and required > bot.home_keep
            and bot.cells[src][2]-amount < required):
        pending['deadline_departure'] = dict(curve=curve, keep=required, tick=bot.tick)
    previous = getattr(bot, '_observed_pending', None)
    if (mode != 'defend' or dst != bot.home or not previous
            or not getattr(bot, '_last_order_confirmed', False)
            or previous['src'] != bot.home or previous['dst'] != src):
        return
    departure = previous.get('deadline_departure')
    if (departure and curve == departure['curve']
            and not any(h <= 6 for h,_ in bot.last_report.get('defense_shortages', ()))):
        pending['deadline_return'] = dict(departure)
