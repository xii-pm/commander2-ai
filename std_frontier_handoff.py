"""One confirmed, interruptible frontier continuation from current observation.

Only a selected supplemental capture creates a task. Confirmation transfers its
carrier once; a second selected capture retires after confirmation. No task owns
a future command, assumes growth, or extends a route through unknown cells.
"""
from math import ceil

from std_geometry import BLANK, KING, FORT


def enabled(bot):
    return (bot.config.get('frontier_confirmed_handoff', False)
            and bot.config.get('frontier_direct_supplement', False))


def report(bot, event=None):
    events = getattr(bot, '_frontier_handoff_events', [])
    if event:
        events.append(event)
    bot._frontier_handoff_events = events
    task = getattr(bot, '_frontier_handoff', None)
    bot.last_report['frontier_handoff'] = dict(
        task=dict(task) if task else None, events=events[:],
        continuation=getattr(bot, '_frontier_handoff_proposal', None),
        continuation_options=getattr(bot, '_frontier_handoff_options', [])[:])


def retire(bot, reason):
    bot._frontier_handoff = None
    bot._frontier_handoff_proposal = None
    bot._frontier_handoff_options = []
    report(bot, reason)


def in_stage(bot):
    limit = bot.config.get('frontier_search_max_producers', 0)
    return (not bot.kings and (not limit or
        sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) <= limit))


def same_order(task, order):
    return bool(order and all(task[key] == order[key]
                             for key in ('src', 'dst', 'sent', 'role')))


def observe(bot):
    """Called after the ordinary FIFO observer; never confirms an order itself."""
    if not enabled(bot):
        return
    bot._frontier_handoff_events = []
    bot._frontier_handoff_proposal = None
    bot._frontier_handoff_options = []
    task = getattr(bot, '_frontier_handoff', None)
    if not task:
        report(bot)
        return
    if not in_stage(bot):
        retire(bot, 'known king or producer stage ended')
        return
    if bot.calls >= task['expires']:
        retire(bot, 'observation deadline')
        return
    if task['phase'] != 'ready':
        prior = getattr(bot, '_observed_pending', None)
        if (same_order(task, prior) and getattr(bot, '_last_order_confirmed', False)
                and bot.cells.get(task['dst'], (None, None, 0))[1] == bot.army):
            if task['phase'] == 'pending_continuation':
                retire(bot, 'continuation confirmed')
                return
            task.update(phase='ready', carrier=task['dst'], expires=bot.calls+3)
            report(bot, 'seed confirmed; carrier handed off')
        elif not same_order(task, bot.pending):
            retire(bot, 'seed or continuation unconfirmed')
            return
    if task['phase'] == 'ready' and task['carrier'] not in bot.owned:
        retire(bot, 'carrier lost')
        return
    report(bot)


def funded_options(bot, src, movable, frontier):
    """Current direct endpoints only; at most the carrier's six neighbors."""
    opportunities = []
    for dst in sorted(bot.neighbors[src]):
        if dst not in frontier or bot.cells[dst][0] != BLANK:
            continue
        units = bot.cells[dst][2]
        margin = int(ceil(bot.counter(dst)*bot.config.get('counter_margin', 100)/100.0))
        required = units+max(1, margin+1)
        sight = bot.new_sight(dst)
        if sight and movable.get(src, 0) >= required:
            opportunities.append(dict(source=src, target=dst, required=required,
                first_sight=len(sight), available=movable[src]))
    return opportunities


def target(bot, movable, targets):
    """Reprice one visible direct BLANK option; the old scoring ranks it later."""
    if not enabled(bot):
        return None
    task = getattr(bot, '_frontier_handoff', None)
    if not task or task['phase'] != 'ready' or bot.pending:
        return None
    src = task['carrier']
    opportunities = funded_options(bot, src, movable, targets)
    if not opportunities:
        retire(bot, 'no currently funded direct information opportunity')
        return None
    selected = max(opportunities, key=lambda p:(p['first_sight'],p['target'],p['required']))
    bot._frontier_handoff_proposal = selected
    bot._frontier_handoff_options = [selected]
    report(bot)
    return src, selected['target']


def targets(bot, movable, frontier):
    """Let the established scoring compare every funded endpoint on one source."""
    bound = target(bot, movable, frontier)
    if not bound:
        return []
    if not bot.config.get('frontier_handoff_all_targets', False):
        return [bound]
    options = funded_options(bot, bound[0], movable, frontier)
    bot._frontier_handoff_options = options
    report(bot)
    return [(p['source'],p['target']) for p in options]


def committed(bot, src, dst, mode):
    """Commit actual pending bytes only after the central action accepted them."""
    if not enabled(bot):
        return
    order = bot.pending
    if not order or order['src'] != src or order['dst'] != dst:
        return
    task = getattr(bot, '_frontier_handoff', None)
    proposal = getattr(bot, '_frontier_handoff_proposal', None)
    if bot.config.get('frontier_handoff_all_targets', False):
        proposal = next((p for p in getattr(bot, '_frontier_handoff_options', [])
                         if p['source'] == src and p['target'] == dst), None)
    if task:
        if (task['phase'] == 'ready' and proposal and mode == 'capture'
                and src == proposal['source'] and dst == proposal['target']
                and order['sent'] >= proposal['required']):
            task.update(phase='pending_continuation', expires=bot.calls+4,
                **{key:order[key] for key in ('src', 'dst', 'sent', 'role')})
            bot._frontier_handoff_proposal = proposal
            report(bot, 'continuation selected')
        elif mode in ('defend', 'intercept', 'finish_king', 'rescue_convoy'):
            retire(bot, 'urgent selected action')
        elif task['phase'] == 'ready' and src == task['carrier']:
            retire(bot, 'carrier used by another selected action')
        return
    additions = bot.last_report.get('frontier_direct_supplement', {}).get('frontier_additions', [])
    if (mode != 'capture' or bot.cells[dst][0] != BLANK or not in_stage(bot)
            or not any(src == tuple(row['source']) and dst == tuple(row['target'])
                       for row in additions)):
        return
    bot._frontier_handoff = dict(phase='pending_seed', expires=bot.calls+4,
        **{key:order[key] for key in ('src', 'dst', 'sent', 'role')})
    report(bot, 'selected supplemental seed')
