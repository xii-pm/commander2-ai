"""Contact-opening reserves, discovery packets, and bounded duel continuation."""
from math import ceil
from std_geometry import BLANK, KING, FORT

KING_MEMORY_STEPS = 12
MATERIAL_KING_FORCE = 8
DUEL_START_CALLS = 48
DUEL_STALL_STEPS = 24
DEPARTURE_HORIZON = 12


def interception_keep(bot, target, sent):
    """Return a residual guard only for a minimal zero-mobile raid removal.

    This removes the zero-mobile uncertainty surcharge from the residual
    forecast only. Any positive hostile force retains its ordinary margin.
    Replanning next observation is required; hidden reinforcement is uncertain.
    """
    if (not bot.config.get('zero_intercept_relief', False)
            or not bot.config.get('opening_zero_mobile', False)
            or not getattr(bot, '_opening_contact', False)
            or bot.home_keep > 6 or bot.cells[target][0] != BLANK
            or bot.cells[target][2] > 1 or sent != bot.cells[target][2]+1):
        return None
    remaining = bot.threat_curve(6, exclude=(target,), zero_uncertainty=False)
    return max([2]+[force-(h-1)//2 for h,force in enumerate(remaining) if h])


def discovery_keep(bot, keep):
    """Build a current-stock exploration packet only at narrow initial exits.

    A useful broad branch retains its initial policy even after it is explored.
    Seeing any fort ends this phase. King attacks and defense retain their
    ordinary arbitration; no unseen road, growth or future pickup is credited.
    """
    packet = bot.config.get('opening_discovery_packet', 0)
    if (not packet or bot.kings or len(bot.owned) < 4
            or getattr(bot, '_opening_contact', False)
            or bot.last_report.get('objective_state', {}).get('owned_producers') != 1
            or any(cell[0] == FORT for cell in bot.memory.values())):
        return keep
    if not hasattr(bot, '_opening_discovery_batch'):
        exits = [p for p in bot.neighbors[bot.home]
                 if bot.cells.get(p, (0, -1, 0))[:2] == (BLANK, 0)
                 and bot.cells[p][2] <= 1]
        bot._opening_discovery_batch = bool(exits) and all(
            len(bot.new_sight(p)) <= 1 for p in exits)
    stock = bot.cells[bot.home][2]
    if bot._opening_discovery_batch and stock-keep < packet:
        return max(keep, stock)
    return keep


def remembered_king_force(bot, pos, age):
    """Retain a recent close king threat after the ordinary mobile memory ends.

    Only a material observed king army and a production estimate fund this warning.
    A tiny old guard does not acquire a new six-soldier opening surcharge.
    It expires after twelve observations and is removed with its owner.
    """
    owner = bot.memory[pos][1]
    record = bot.kings.get(owner)
    if (not bot.config.get('contact_king_memory', False)
            or bot.memory[pos][0] != KING or not record
            or tuple(record['pos']) != pos or age > KING_MEMORY_STEPS or record['units'] < MATERIAL_KING_FORCE
            or not getattr(bot, '_opening_contact', False)
            or bot.risk_dist.get(pos, 999) > 2):
        return None
    return record['units']+int(ceil(age*.52))


def continuation_allowed(bot, selected):
    """Price only a stalled visible duel beyond the ordinary waiting leaf.

    The existing two-exchange search is a bounded public-board estimate.
    Unresolved departures require an additional current-stock guard below.
    """
    return (selected is not None and selected[4] == 'skirmish_wait'
        and bot.config.get('close_duel_continuation', False)
        and getattr(bot, '_opening_contact', False)
        and bot.calls >= DUEL_START_CALLS
        and bot.tick-getattr(bot, '_frontier_last_progress', bot.tick) >= DUEL_STALL_STEPS
        and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) == 1
        and any(bot.risk_dist.get(pos, 999) <= 2
                and bot.cells[pos][0] == KING for pos in bot.enemies))


def continuation_funded(bot, selected):
    """Keep the ordinary departure warning funded after the exact first move.

    Visible responses are priced by the local search. Its board cannot see an
    unexplained departure, so that separate warning receives current king
    soldiers, without borrowing growth or a later friendly return command.
    """
    if selected is None or selected[4] != 'tactical':
        return False
    warning = getattr(bot, '_departure_warning', None)
    if warning is None or not warning.records:
        return True
    curve, _ = warning.curve(bot, DEPARTURE_HORIZON, bot.config.get('threat_margin', 2))
    _, src, dst, amount, _, _ = selected
    held = bot.cells[bot.home][2]
    held += amount if dst == bot.home else -amount if src == bot.home else 0
    return held >= max(curve)+1
