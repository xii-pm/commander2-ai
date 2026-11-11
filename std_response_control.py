"""Bound repeated ambiguous-evidence decisions and abstain on unpriced plans.

This does not resolve the hidden enemy's intent. It controls when an incomplete
one-exchange valuation is allowed to replace an existing admitted proposal.
"""
from std_geometry import FORT, MARSH, BLOCKED
from std_joint_response import rerank as joint_rerank, WAIT_MODES


def identity(bot, record):
    return (record['owner'], tuple(record['origin']), bot.calls-record['age'])


def state(bot):
    if not hasattr(bot, '_response_control'):
        bot._response_control = dict(consumed=set(), inflight=None, proposal=None)
    return bot._response_control


def observe(bot):
    s = state(bot)
    # Keys use observation age, never pretend callbacks are game ticks.
    s['consumed'] = {key for key in s['consumed'] if bot.calls-key[2] <= 32}
    s['proposal'] = None
    pending = s['inflight']
    if pending is None:
        return
    old = getattr(bot, '_observed_pending', None)
    exact = old and (old['src'],old['dst'],old['sent'],old['role']) == pending['order']
    if exact and getattr(bot, '_last_order_confirmed', False):
        s['consumed'].update(pending['keys'])
        bot.last_report['response_confirmation'] = dict(status='confirmed_by_public_pending_resolver',
            keys=sorted(pending['keys']), order=pending['order'])
        s['inflight'] = None
    elif not bot.pending or not exact:
        # Cancellation/time-out is not execution; evidence remains unspent.
        bot.last_report['response_confirmation'] = dict(status='unconfirmed_released',
            keys=sorted(pending['keys']), order=pending['order'])
        s['inflight'] = None


def funded_plan(bot, original):
    """Validate a concrete no-growth schedule; no guessed future reserves."""
    report = bot.last_report.get('fort_assembly', {})
    cert = report.get('certificate')
    # Objective prioritization reprices a proposal without changing its order.
    # The priority score is not the identity of the funded continuation.
    if not cert or tuple(report.get('proposal', ()))[1:] != original[1:]:
        return None
    orders = [(tuple(src),tuple(dst),amount) for src,dst,amount in cert['orders']]
    if len(orders) <= 1 or orders[0] != tuple(original[1:4]) or len(orders) > 25:
        return None
    target = tuple(cert['target'])
    board = dict(bot.cells)
    if target not in board or board[target][0] != FORT or board[target][1] == bot.army:
        return None
    holds = {tuple(pos):keep for pos,keep in cert['holds']}
    for i,(src,dst,amount) in enumerate(orders):
        a,b = board.get(src),board.get(dst)
        if (not a or not b or a[1] != bot.army or type(amount) is not int
                or amount <= 0 or amount > a[2]-holds.get(src,1)
                or dst not in bot.neighbors[src] or a[0] == MARSH or b[0] in BLOCKED+(MARSH,)):
            return None
        if i < len(orders)-1 and b[1] != bot.army:
            return None
        if i == len(orders)-1 and (dst != target or amount <= b[2]):
            return None
        board[src] = a[0],bot.army,a[2]-amount
        board[dst] = (b[0],bot.army,b[2]+amount if b[1]==bot.army else amount-b[2])
    return dict(commands=len(orders), target=target, current_stock_only=True,
        future_opponent_responses='unpriced', future_growth_funds=False)


def rerank(bot, choices, enabled=True, evidence=True, plans=True):
    s = state(bot)
    s['proposal'] = None
    joint_rerank(bot,choices,enabled=False)
    q = bot.last_report.get('joint_response')
    if not q or not q['would_change']:
        return choices
    original = max(choices)
    selected = tuple(tuple(v) if isinstance(v,list) else v for v in q['selected'])
    baseline = q['evaluations'][0]
    best = next(r for r in q['evaluations'] if r['choice'] == q['selected'])
    # Existing model only: this exception is not a real-time survival proof.
    emergency = bool(baseline['losing_leaves'] and not best['losing_leaves'])
    keys = {identity(bot,r) for r in q['records']}
    fresh = keys-s['consumed']
    plan = funded_plan(bot,original) if plans else None
    reason = None
    if evidence and keys and not fresh and not emergency:
        reason = 'same ambiguous evidence already used for a confirmed intervention'
    elif plan and not emergency:
        reason = 'one-exchange model does not price this concrete funded continuation'
    accepted = reason is None
    q['changed'] = bool(accepted and enabled)
    bot.last_report['response_control'] = dict(accepted=accepted, applied=bool(accepted and enabled),
        reason=reason, evidence_keys=sorted(keys), fresh_keys=sorted(fresh),
        consumed_keys=sorted(s['consumed']), funded_plan=plan, modeled_emergency=emergency,
        evidence_control=evidence, plan_control=plans)
    if not accepted or not enabled:
        return choices
    s['proposal'] = dict(keys=keys, selected=selected)
    promoted = (max(r[0] for r in choices)+.001,)+selected[1:]
    return [r for r in choices if r!=selected]+[promoted]


def returned(bot, move):
    """Track only the exact returned command, then await public confirmation."""
    s = state(bot)
    proposal = s['proposal']
    if not proposal:
        return
    s['proposal'] = None
    row,keys = proposal['selected'],proposal['keys']
    report = bot.last_report['response_control']
    if row[4] in WAIT_MODES:
        if move is None and bot.last_report.get('mode') == row[4]:
            # Waiting has no execution acknowledgement. Spend a decision, not
            # a claim of successful enemy contact; no tick-dependent cooldown.
            s['consumed'].update(keys)
            report['submission'] = 'wait_decision_spent_without_execution_claim'
        return
    expected = tuple(row[1:4])
    if move is None or tuple(move) != expected:
        report['submission'] = 'different_or_rejected_order_unspent'
        return
    order = (row[1],row[2],row[3],row[4])
    p = bot.pending
    if not p or (p['src'],p['dst'],p['sent'],p['role']) != order:
        report['submission'] = 'no_matching_pending_unspent'
        return
    s['inflight'] = dict(keys=keys, order=order)
    report['submission'] = 'exact_order_returned_awaiting_confirmation'
