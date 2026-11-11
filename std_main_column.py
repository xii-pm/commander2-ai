"""Recover whole-army movement after thin contact or stalled production.

Ordinary openings already have their own field-column expansion. This
supplement covers contact mode and a bounded post-elimination production stall.
Routes use current owned roads and signed stock after every reserve. Every
observation replans the proposal; no future growth or hidden road funds it.
"""
from collections import deque
from heapq import nlargest
from math import sqrt
from std_geometry import KING, FORT, MARSH, BLOCKED
from std_objectives import fort_packet

MIN_PRODUCERS = 4
MIN_DISPATCH = 32
LARGE_DISPATCH = 128
SOURCE_LIMIT = 3
ROUTE_LIMIT = 18
HOME_BUFFER = 8
STALLED_START = 300
STALLED_TERRITORY = 64
PRODUCTION_WAIT = 64
MAX_STALLED_PRODUCERS = 16
MAIN_PRIORITY = 1800
SUPPLEMENT_PRIORITY = 900
IMPASSABLE = BLOCKED+(MARSH,)


def has_funded_fort_capture(bot, choices):
    """A funded frontline capture has no need for a competing rear convoy."""
    for _, src, dst, amount, mode, target in choices:
        data = bot.cells.get(dst)
        if (mode not in ('capture', 'assault') or dst != target or not data
                or data[0] != FORT or data[1] == bot.army or amount <= data[2]):
            continue
        packet = fort_packet(bot, src, dst, amount, mode)
        if packet is not None and packet <= bot.available(src):
            return True
    return False


def propose(bot, choices, reserves):
    state = bot.last_report.get('objective_state', {})
    producers = state.get('owned_producers', 0)
    sites = frozenset(p for p in bot.owned if bot.cells[p][0] in (KING, FORT))
    previous = getattr(bot, '_column_producer_sites', frozenset())
    if sites-previous:
        bot._column_producer_gain_at = bot.calls
    bot._column_producer_sites = sites
    contact = (bot.config.get('contact_field_column', False)
               and getattr(bot, '_opening_contact', False))
    stalled = (bot.config.get('stalled_field_column', False)
        and not getattr(bot, '_opening_contact', False)
        and bot.calls >= STALLED_START and len(bot.owned) >= STALLED_TERRITORY
        and bool(bot.eliminated) and producers <= MAX_STALLED_PRODUCERS
        and bot.calls-getattr(bot, '_column_producer_gain_at', bot.calls) >= PRODUCTION_WAIT)
    if not (contact or stalled):
        return
    convoy = getattr(bot, '_rear_convoy', None)
    if (stalled and convoy and convoy['phase'] == 'ready'
            and any(choice[4] == 'rear_supply' and choice[1] == convoy['current']
                    for choice in choices)):
        return
    cells = bot.cells
    if (cells[bot.home][2] < bot.home_keep
            or state.get('owned_producers', 0) < MIN_PRODUCERS
            or any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', ()))
            or any(bot.tick-m['seen'] <= bot.KING_MAX_AGE for m in bot.kings.values())):
        return
    if has_funded_fort_capture(bot, choices):
        return
    owned = {p for p in bot.owned if cells[p][0] != MARSH}
    home_hold = max(bot.last_report.get('threat_curve') or [0])+HOME_BUFFER
    spare = {}
    for pos in owned:
        hold = max(1, reserves.get(pos, 1), bot.fort_reserves.get(pos, 1))
        if cells[pos][0] == FORT:
            hold = max(hold, bot.counter(pos)+1)
        if pos == bot.home:
            hold = max(hold, home_hold)
        spare[pos] = cells[pos][2]-hold
    sources = nlargest(SOURCE_LIMIT, owned, key=lambda pos: (spare[pos], pos))
    best = None
    for src in sources:
        amount = spare[src]
        if amount < MIN_DISPATCH:
            continue
        paths, force = {src: (src,)}, {src: amount}
        distance, queue = {src: 0}, deque([src])
        while queue:
            pos = queue.popleft()
            depth = distance[pos]+1
            if depth > ROUTE_LIMIT:
                continue
            for dst in bot.neighbors[pos]:
                cell = cells.get(dst)
                if not cell or cell[0] in IMPASSABLE:
                    continue
                if dst in owned:
                    if dst == bot.home and dst != src:
                        continue
                    # A depleted protected road consumes stock immediately.
                    power = force[pos]+spare[dst]
                    if power <= 0:
                        continue
                    if dst not in distance:
                        distance[dst], force[dst] = depth, power
                        paths[dst] = paths[pos]+(dst,)
                        queue.append(dst)
                    elif distance[dst] == depth and power > force[dst]:
                        force[dst], paths[dst] = power, paths[pos]+(dst,)
                    continue
                if cell[0] == KING:
                    continue
                need = cell[2]+bot.counter(dst)+2
                if cell[0] == FORT and cell[1] > 0:
                    need += depth//2
                if force[pos] < need:
                    continue
                route = paths[pos]+(dst,)
                first = route[1]
                first_cell = cells[first]
                arrival = (amount+first_cell[2] if first_cell[1] == bot.army
                           else amount-first_cell[2])
                if arrival <= bot.counter(first)+1:
                    continue
                value = (300 if cell[0] == FORT else 50)+10*len(bot.new_sight(dst))
                if cell[1] > 0:
                    value += 20
                rank = value/(depth+2.0)+sqrt(force[pos])/depth
                decisive = (amount >= LARGE_DISPATCH or bool(bot.eliminated)
                            and cell[0] == FORT and amount >= need)
                base = MAIN_PRIORITY if decisive else SUPPLEMENT_PRIORITY
                plan = (base+rank, rank, src, first, amount, dst, route, force[pos], need)
                # Preserve the complete tuple tie rule without a list of plans.
                if best is None or plan > best:
                    best = plan
    if best is not None:
        score, rank, src, dst, amount, target, route, power, need = best
        choices.append((score, src, dst, amount, 'main_column', target))
        bot.last_report['main_column'] = dict(route=route, dispatch=amount,
            funded_arrival=power, required=need, rank=rank)
