"""Bounded source coverage from current reserves and visible frontier cells."""
from math import ceil

from std_geometry import BLOCKED, BLANK, KING, FORT


def observe_progress(bot):
    """Reset the search clock only on first observations, never on orders.

    Memory retains every legally observed cell. Fog returning or a capture
    confirmation on an old cell is not a new observation for this clock.
    """
    count = len(bot.memory)
    if count != getattr(bot, '_frontier_seen_count', None):
        bot._frontier_last_progress = bot.tick
    bot._frontier_seen_count = count


def supplement_scope(bot):
    threshold = bot.config.get('frontier_drought_steps', 0)
    production_limit = bot.config.get('frontier_search_max_producers', 0)
    if not threshold and not production_limit:
        return True, None
    last = getattr(bot, '_frontier_last_progress', bot.tick)
    gap = max(0, bot.tick-last)
    known = bool(bot.kings)
    producers = (sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned)
                 if production_limit else None)
    production_allowed = not production_limit or producers <= production_limit
    allowed = (not threshold or gap >= threshold and not known) and production_allowed
    return allowed, dict(threshold=threshold, gap=gap, known_king=known,
                         allowed=allowed, clock='first legally observed cells',
                         production_limit=production_limit, owned_producers=producers,
                         production_scope_passed=production_allowed)


def direct_supplement(bot, movable, targets, existing, limit=2):
    """Add up to two funded one-hop proposals without removing old sources.

    The caller keeps every original source/path proposal. Each extra source is
    bound to the one direct target selected for its marginal information gain.
    It does not receive another owned-tree search or arbitrary transport jobs.
    """
    allowed, scope = supplement_scope(bot)
    if not allowed:
        return {}, dict(existing_source_count=len(existing), supplement_limit=limit,
            direct_only=True, mobile_packet=bot.config.get('frontier_mobile_packet',False),
            frontier_additions=[], drought=scope)
    opportunities=[]
    covered=set()
    existing=set(existing)
    for src in sorted(bot.owned):
        if movable.get(src,0)<1:
            continue
        for target in sorted(bot.neighbors[src]):
            if target not in targets:
                continue
            kind,owner,units=bot.cells[target]
            if kind in BLOCKED:
                continue
            defending=units+(1 if owner>0 and kind in (KING,FORT) else 0)
            margin=int(ceil(bot.counter(target)*bot.config.get('counter_margin',100)/100.0))
            tail=1 if (src not in existing and bot.config.get('frontier_mobile_packet',False)
                       and kind==BLANK) else 0
            if movable[src]<defending+max(1,margin+1)+tail:
                continue
            sight=bot.new_sight(target)
            if not sight:
                continue
            if src in existing:
                covered.update(sight)
            else:
                opportunities.append((src,target,sight))
    selected={}
    additions=[]
    for _ in range(limit):
        candidates=[(len(sight-covered),movable[src],src,target,sight)
                    for src,target,sight in opportunities if src not in selected and sight-covered]
        if not candidates:
            break
        gain,_,src,target,sight=max(candidates,key=lambda row:row[:4])
        selected[src]=target
        covered.update(sight)
        additions.append(dict(source=src,target=target,marginal_first_sight=gain))
    return selected,dict(existing_source_count=len(existing),supplement_limit=limit,
                         direct_only=True,mobile_packet=bot.config.get('frontier_mobile_packet',False),
                         frontier_additions=additions, drought=scope)


def select(bot, movable, targets):
    """Keep large columns and admit at most two marginal information sources.

    Eligibility precedes truncation. A frontier slot needs a currently funded
    direct capture and previously unobserved cells outside the large columns'
    direct opportunities. This is candidate coverage, not a future-path promise.
    """
    limit = bot.config.get('frontier_sources', 8)
    ranked = sorted((p for p in bot.owned if movable.get(p, 0) >= 1),
                    key=lambda p: (movable[p], p), reverse=True)
    slots = min(2, limit // 4)
    selected = ranked[:limit-slots]
    opportunities = {}
    for src in ranked:
        funded = []
        for target in sorted(bot.neighbors[src]):
            if target not in targets:
                continue
            kind, owner, units = bot.cells[target]
            if kind in BLOCKED:
                continue
            defending = units + (int(ceil(.5)) if owner > 0 and kind in (KING, FORT) else 0)
            counter = bot.counter(target)
            margin = int(ceil(counter * bot.config.get('counter_margin', 100) / 100.0))
            if movable[src] < defending + max(1, margin+1):
                continue
            sight = bot.new_sight(target)
            if sight:
                funded.append((target, sight))
        opportunities[src] = funded
    covered = set()
    for src in selected:
        for _, sight in opportunities[src]:
            covered.update(sight)
    additions = []
    for _ in range(slots):
        candidates = [(len(sight-covered), movable[src], src, target, sight)
                      for src in ranked if src not in selected
                      for target, sight in opportunities[src] if sight-covered]
        if not candidates:
            break
        gain, _, src, target, sight = max(candidates, key=lambda row: row[:4])
        selected.append(src)
        covered.update(sight)
        additions.append(dict(source=src, target=target, marginal_first_sight=gain))
    for src in ranked:
        if len(selected) >= limit:
            break
        if src not in selected:
            selected.append(src)
    # Preserve the established king's separate opportunity to use its surplus.
    if bot.home not in selected:
        selected.append(bot.home)
    return selected, dict(limit=limit, large_slots=limit-slots,
        eligible=len(ranked), selected=selected[:], frontier_additions=additions)


def plain_scout_packet(bot, src, target, steps, reserves):
    """One soldier may leave an already under-covered ordinary field tile.

    Keep its one garrison and every explicit reserve. The destination must be
    an adjacent visible empty neutral plain with zero visible counter budget.
    This is one original frontier proposal, never a transport or scout system.
    """
    # This exception recovers search mobility, not a new distraction
    # beside a legally known king. Existing funded frontier moves,
    # king approaches and immediate captures remain in the same arbiter.
    known_king = any(bot.tick-model['seen'] <= bot.KING_MAX_AGE
                     for model in getattr(bot, 'kings', {}).values())
    if (not bot.config.get('plain_scout_relief', False) or known_king or steps != 1
            or src == bot.home or bot.cells.get(src) != (BLANK, bot.army, 2)
            or bot.cells.get(target) != (BLANK, 0, 0)
            or target not in bot.neighbors[src]
            or reserves.get(src, 1) > 1 or src in bot.protected()
            or bot.counter(src, excluded=(target,)) < 2 or bot.counter(target) != 0):
        return 0
    remaining = bot.cells[src][2]-1
    # Do not enable a currently visible single-command capture of
    # this source that retaining its soldier would have prevented.
    for enemy in bot.neighbors[src]:
        cell = bot.cells.get(enemy)
        if (cell and cell[1] not in (0, bot.army)
                and remaining < cell[2]-1 <= bot.cells[src][2]):
            return 0
    return 1


def scout_relief_is_fallback(choices, first_frontier, relief_indices):
    """Do not displace an existing funded capture or its paid first edge."""
    return not any(index not in relief_indices and choice[4] in ('capture', 'advance')
                   and choice[3] > 0
                   for index, choice in enumerate(choices) if index >= first_frontier)
