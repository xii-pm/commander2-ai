"""Recover confirmed defensive and ordinary friendly-edge reversals.

Three ordinary alternating transfers establish repeated command conflict.
Keep the last direction for a short interval; new goals alone must not make
the same carrier immediately undo its delivery. Emergency defense and combat
remain eligible, and ownership changes invalidate this transport evidence.
"""

TRANSFERS = frozenset(('king_advance', 'tempo_king', 'advance', 'merge',
                       'opening_policy', 'supply', 'rear_supply'))
ORDINARY = frozenset(('advance', 'merge', 'supply', 'rear_supply'))


def observe(bot):
    if getattr(bot, '_cycle_observed_call', None) == bot.calls:
        return
    bot._cycle_observed_call = bot.calls
    pending = getattr(bot, '_observed_pending', None)
    history = list(getattr(bot, '_confirmed_transfer_history', ()))
    if (pending and getattr(bot, '_last_order_confirmed', False)
            and all(bot.cells.get(pending.get(key), (0, 0, 0))[1] == bot.army
                    for key in ('src', 'dst'))):
        history.append(dict(src=pending['src'], dst=pending['dst'],
                            mode=pending.get('role'), call=bot.calls))
    else:
        history = []
    history = history[-4:]
    bot._confirmed_transfer_history = history
    hold = getattr(bot, '_repeated_cycle_hold', None)
    if hold and bot.calls > hold['until']:
        hold = None
    if len(history) == 4:
        consecutive = all(y['call'] == x['call']+1 for x, y in zip(history, history[1:]))
        reversing = all((x['src'], x['dst']) == (y['dst'], y['src'])
                        for x, y in zip(history, history[1:]))
        defense = [r for r in history if r['mode'] == 'defend']
        offense = [r for r in history if r['mode'] in TRANSFERS]
        if consecutive and reversing and defense and offense:
            row = offense[-1]
            hold = dict(src=row['src'], dst=row['dst'], until=bot.calls+12,
                        mode=row['mode'], evidence=[dict(r) for r in history])
    bot._repeated_cycle_hold = hold
    transport = getattr(bot, '_transport_cycle_hold', None)
    if transport and (bot.calls > transport['until'] or any(
            bot.cells.get(transport[k], (0, 0, 0))[1] != bot.army for k in ('src', 'dst'))):
        transport = None
    recent = history[-3:]
    if (len(recent) == 3 and all(r['mode'] in ORDINARY for r in recent)
            and all(y['call'] == x['call']+1 and
                    (x['src'], x['dst']) == (y['dst'], y['src'])
                    for x, y in zip(recent, recent[1:]))):
        last = recent[-1]
        # The next reverse would be the fourth consecutive traversal.
        transport = dict(src=last['dst'], dst=last['src'],
                         until=bot.calls+12, evidence=[dict(r) for r in recent])
    bot._transport_cycle_hold = transport


def transport_blocked(bot, src, dst, mode):
    hold = getattr(bot, '_transport_cycle_hold', None)
    return bool(hold and bot.calls <= hold['until']
        and mode in TRANSFERS and mode not in ('king_advance', 'tempo_king')
        and (src, dst) == (hold['src'], hold['dst'])
        and all(bot.cells.get(p, (0, 0, 0))[1] == bot.army for p in (src, dst))
        and not any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', ())))


def blocked(bot, src, dst, mode):
    if transport_blocked(bot, src, dst, mode):
        return True
    hold = getattr(bot, '_repeated_cycle_hold', None)
    if (not hold or bot.calls > hold['until'] or mode not in TRANSFERS
            or bot.cells.get(dst, (0, 0, 0))[1] != bot.army):
        return False
    return ((mode == 'king_advance' and hold['mode'] == 'king_advance')
            or (src, dst) == (hold['src'], hold['dst']))


def filter_choices(bot, choices):
    observe(bot)
    result, rejected = [], []
    for proposal in choices:
        _, src, dst, amount, mode, target = proposal
        (rejected if blocked(bot, src, dst, mode) else result).append(proposal)
    bot.last_report['repeated_cycle_recovery'] = dict(
        hold=getattr(bot, '_repeated_cycle_hold', None), rejected=rejected,
        transport_hold=getattr(bot, '_transport_cycle_hold', None),
        trigger='four defense/transport alternations or three ordinary friendly alternations')
    return result
