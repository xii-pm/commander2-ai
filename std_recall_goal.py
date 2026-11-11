"""Anchor economic insurance to a confirmed goal; tactical defense stays independent."""


def observe(bot):
    if not bot.config.get('recall_goal_hysteresis', False):
        return
    pending = getattr(bot, '_observed_pending', None)
    if not getattr(bot, '_last_order_confirmed', False) or not pending:
        return
    corridor = (bot.config.get('corridor_recall_goal', False)
                and pending.get('role') == 'guard_supply' and pending['dst'] == bot.home)
    if (pending.get('role') != 'economic_recall' and not corridor) or 'recall_goal' not in pending:
        return
    bot._economic_recall_goal = max(getattr(bot, '_economic_recall_goal', 0), pending['recall_goal'])


def target(bot, nominal):
    if not bot.config.get('recall_goal_hysteresis', False):
        return nominal
    goal = getattr(bot, '_economic_recall_goal', None)
    # Use the same six-observation threat requirement as reserve_home. This
    # can raise insurance for a newly observed threat, without treating passive
    # growth of the proportional reserve as another confirmed delivery need.
    curve = bot.threat_curve(6)
    threat = max([max(2, bot.config.get('base_guard', 2))] +
        [max(0, force-(h-1)//2) for h, force in enumerate(curve) if h])
    half_floor = (goal is not None and bot.config.get('recall_goal_half_floor', False)
        and 2*bot.cells[bot.home][2] < nominal)
    # Reopen in discrete funded batches when a growing empire has left
    # the confirmed insurance target behind. Tactical rescue is independent.
    # At least two legally observed opponents establish multi-party
    # contact. Keep the single-opponent insurance policy unchanged.
    ratio = bot.config.get('growing_insurance', 0) if len(getattr(bot,'known_owners',())) >= 2 else 0
    growth_reopen = (goal is not None and ratio > 0
        and 100*bot.cells[bot.home][2] < ratio*nominal)
    effective = nominal if goal is None or half_floor or growth_reopen else min(nominal, max(goal, threat))
    bot.last_report['insurance_growth_reopened'] = growth_reopen
    bot.last_report['recall_goal_hysteresis'] = dict(nominal=nominal,
        confirmed_goal=goal, threat_requirement=threat, goal=effective,
        held=bot.cells[bot.home][2], half_floor_reopened=half_floor)
    return effective


def committed(bot, mode):
    if not bot.config.get('recall_goal_hysteresis', False) or mode != 'economic_recall':
        return
    if bot.pending and bot.pending.get('role') == mode:
        bot.pending['recall_goal'] = bot.last_report['recall_goal_hysteresis']['goal']
