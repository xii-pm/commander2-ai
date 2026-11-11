"""Shared production timing and objective priorities from legal observations.

One callback still commits one order. Enemy ownership is tracked separately:
eliminating one player does not erase another player's threat.
"""
from std_recon import first_contact_search_active
from std_geometry import BLANK, KING, FORT, hex_distance
from std_recon import search_memory
from math import sqrt
from collections import deque

EMERGENCY = 4000000.0
ELIMINATION = 3000000.0
FUNDED_STRIKE = 2000000.0
RECOVERY = 1000000.0


def investment_guard_active(bot):
    """Insure a sunk first-fort army when one road cut delays its return."""
    task = getattr(bot, '_first_fort_investment', None)
    if not task or bot.calls > task['expires']:
        return False
    if 'fragile' not in task:
        if bot.cells.get(task['target'], (0,0,0))[1] != bot.army:
            return False
        parent, distance = bot.owned_tree(bot.home)
        target = task['target']
        task['fragile'] = target not in distance
        if target in distance:
            route = bot.path(parent, target)
            owned = set(bot.owned)
            for cut in route[1:-1]:
                reached = {bot.home:0}
                queue = deque([bot.home])
                limit = distance[target]+2
                while queue and target not in reached:
                    pos = queue.popleft()
                    if reached[pos] >= limit:
                        continue
                    for nxt in bot.neighbors[pos]:
                        if nxt in owned and nxt != cut and nxt not in reached:
                            reached[nxt] = reached[pos]+1
                            queue.append(nxt)
                if target not in reached:
                    task['fragile'] = True
                    break
    return task['fragile']


def observe(bot, previous, order):
    """Witness alternating growth; lose confidence on skipped/ambiguous updates."""
    patrol = getattr(bot, '_recon_patrol', None)
    observed = getattr(bot, '_observed_pending', None)
    if patrol and observed and observed['src'] == patrol['position']:
        patrol = None
    if (observed and observed['role'] == 'frontier_recon'
            and bot._last_order_confirmed):
        patrol = dict(position=observed['dst'], expires=bot.calls+24)
    if patrol and (patrol['position'] not in bot.owned or bot.calls > patrol['expires']):
        patrol = None
    bot._recon_patrol = patrol
    touched = {order['src'], order['dst']} if order else set()
    gains = set()
    for pos in bot.owned:
        old, new = previous.get(pos), bot.cells[pos]
        if (pos in touched or not old or old[:2] != new[:2]
                or new[0] not in (KING, FORT)):
            continue
        if any(previous.get(n, (0, -1, 0))[1] not in (0, bot.army)
               or bot.cells.get(n, (0, -1, 0))[1] not in (0, bot.army)
               for n in bot.neighbors[pos]):
            continue
        gains.add(new[2]-old[2])
    last = getattr(bot, '_producer_gain', None)
    gain = next(iter(gains)) if len(gains) == 1 else None
    alternating = gain in (0, 1) and last in (0, 1) and gain != last
    bot._producer_phase_samples = (getattr(bot, '_producer_phase_samples', 0)+1
                                  if alternating else 0)
    bot._producer_gain = gain if gain in (0, 1) else None
    bot._producer_growth_next = (gain == 0 if bot._producer_phase_samples >= 2 else None)
    contested = getattr(bot, '_contested_forts', {})
    for pos, new in bot.cells.items():
        old = previous.get(pos)
        if (new[0] == FORT and old and old[0] == FORT
                and new[1] != old[1] and old[1] > 0 and new[1] > 0):
            contested[pos] = bot.calls
    bot._contested_forts = {p: call for p, call in contested.items() if bot.calls-call <= 24}
    friendly = sum(bot.cells[p][2] for p in bot.owned)
    enemies = sum(bot.cells[p][2] for p in bot.enemies)
    producers = sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned)
    bot._advantage = producers >= 3 and friendly >= max(40, enemies*1.25)
    bot.last_report['objective_state'] = dict(advantage_proxy=bot._advantage,
        owned_producers=producers, visible_friendly_units=friendly,
        visible_enemy_units=enemies, producer_growth_next=bot._producer_growth_next,
        alternating_witnesses=bot._producer_phase_samples,
        contested_forts=len(bot._contested_forts))


def neutral_fort_tail(bot, target):
    """Price an unseen approach before spending the first field army."""
    data = bot.cells.get(target)
    if (not bot.config.get('neutral_fort_insurance', False) or not data
            or data[0] != FORT or data[1] != 0 or data[2] < 12
            or sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) != 1
            or not any(p not in bot.memory for p in bot.neighbors[target])):
        return 1
    return max(8, (data[2]+1)//2)


def fort_packet(bot, src, dst, amount, mode):
    """Fund a hold unless capture precedes the next producer increment."""
    data = bot.cells.get(dst)
    tail = neutral_fort_tail(bot, dst)
    if tail > 1 and mode not in ('defend', 'finish_king'):
        required = data[2]+max(tail, bot.counter(dst)+1)
        return max(amount, required) if required <= bot.available(src) else None
    if (not bot.config.get('phase_aware_forts', False) or not data
            or data[0] != FORT or data[1] in (0, bot.army)
            or mode in ('defend', 'finish_king')):
        return amount
    counter = bot.counter(dst)
    # Native ticks grow producers before resolving queued combat. A small
    # trade earns our growth only when capture is on a non-growth tick:
    # the next response tick then grows our fort before enemy recapture.
    if not counter or getattr(bot, '_producer_growth_next', None) is False:
        return amount
    required = data[2]+counter+2
    if amount >= required:
        return amount
    cap = bot.available(src)
    # Emergency interception may release a home reserve already evaluated by
    # deadline_defense; preserve that concrete rescue even without a fort hold.
    if (mode == 'intercept' and bot.risk_dist.get(dst, 999) == 1
            and bot.last_report.get('defense_shortages')):
        return amount
    return max(amount, required) if required <= cap else None


def immediate_kings(bot, choices):
    """A captured king is eliminated; its neighboring army is not a hold cost."""
    if not bot.config.get('finish_king', False):
        return
    if not bot.config.get('objective_priority', False):
        # Keep historical ablations behind the same proposal entry point.
        for target in bot.enemies:
            if bot.cells[target][0] != KING:
                continue
            required = bot.cells[target][2]+1+bot.counter(target)
            for src in bot.neighbors[target]:
                if src in bot.owned and bot.cells[src][2]-1 > required:
                    choices.append((2000000, src, target, bot.cells[src][2]-1,
                                    'finish_king', target))
        return
    for target in bot.enemies:
        if bot.cells[target][0] != KING:
            continue
        units = bot.cells[target][2]
        # One production allowance covers the update before order resolution.
        required = units+2
        for src in bot.neighbors[target]:
            cell = bot.cells.get(src)
            if not cell or cell[1] != bot.army:
                continue
            amount = cell[2]-1
            if src == bot.home:
                owner = bot.cells[target][1]
                excluded = tuple(p for p, data in bot.memory.items() if data[1] == owner)
                curve = bot.threat_curve(6, exclude=excluded, zero_uncertainty=False)
                keep = max([1]+[max(0, force-(h-1)//2) for h, force in enumerate(curve) if h])
                amount = max(0, cell[2]-keep)
            if amount >= required:
                choices.append((ELIMINATION+amount-units, src, target, amount,
                                'finish_king', target))


def urgent(bot):
    return any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', ()))


def priority_score(tier, score):
    """Keep domain priorities separate without flattening funded route ranks."""
    return tier+100000.0*score/(100000.0+abs(score))


def prioritize(bot, choices):
    """Emergency king rescue, elimination, funded king march, then economy."""
    emergency = urgent(bot)
    known_kings = {m['pos'] for owner, m in bot.kings.items()
                   if owner not in bot.eliminated and bot.tick-m['seen'] <= bot.KING_MAX_AGE}
    funded_forts = (bot.config.get('prefer_producers', False) and any(
        mode in ('capture', 'advance', 'intercept', 'road_mobilize')
        and bot.cells.get(target, (0, bot.army, 0))[0] == FORT
        and bot.cells[target][1] != bot.army
        and fort_packet(bot, src, dst, amount, mode) is not None
        for _, src, dst, amount, mode, target in choices))
    result = []
    for score, src, dst, amount, mode, target in choices:
        capital = getattr(bot,'_producer_investment',None)
        if (capital and not capital['funded'] and not emergency
                and src == bot.home and mode == 'intercept'):
            # A nonurgent raid must not bypass the current first-fort
            # savings ledger through the interception escape hatch.
            bot.last_report['capital_intercept_deferred'] = (
                bot.last_report.get('capital_intercept_deferred',0)+1)
            continue
        destination = bot.cells.get(dst)
        if (mode != 'finish_king' and destination and destination[0] == KING
                and destination[1] not in (0, bot.army)):
            # All direct king captures share the one growth/third-player
            # check above. Ordinary interception must not bypass that check.
            continue
        adjusted = fort_packet(bot, src, dst, amount, mode)
        if adjusted is None:
            continue
        amount = adjusted
        data = bot.cells.get(target)
        king_target = target in known_kings
        from std_deadline_strike import promote as promote_deadline_strike
        if emergency and promote_deadline_strike(bot,(score,src,dst,amount,mode,target)):
            score = priority_score(EMERGENCY+80000,score)
        elif emergency and (mode == 'defend' or mode == 'intercept'
                          and bot.risk_dist.get(dst, 999) <= 6):
            score = priority_score(EMERGENCY, score)
        elif mode == 'finish_king':
            tier = ELIMINATION
            if emergency:
                owner = bot.cells[dst][1]
                excluded = tuple(p for p, data in bot.memory.items() if data[1] == owner)
                remaining = bot.threat_curve(6, exclude=excluded, zero_uncertainty=False)
                full = bot.threat_curve(6, zero_uncertainty=False)
                held = bot.cells[bot.home][2]-(amount if src == bot.home else 0)
                safe = all(held+(h-1)//2 >= force
                           for h, force in enumerate(remaining) if h)
                relieved = any(full[h] > held+(h-1)//2 and full[h] > remaining[h]
                               for h in range(1, 7))
                if safe and relieved:
                    # Elimination removes this owner's attack as well. Other
                    # players retain independent command and growth budgets.
                    tier = EMERGENCY+100000
            score = priority_score(tier, score)
        elif king_target and mode in ('assault', 'tempo_king', 'bridge_king'):
            score = priority_score(FUNDED_STRIKE, score)
        elif mode == 'king_recovery':
            score = priority_score(RECOVERY, score)
        elif (getattr(bot, '_advantage', False) and data and data[0] == FORT
              and data[1] not in (0, bot.army)
              and target in getattr(bot, '_contested_forts', {})
              and mode != 'defend'):
            score *= .70
            if mode == 'intercept':
                # A harmless repeated fort trade is an economic action even
                # beside home. A real six-step rescue was classified above.
                score = min(score, 550.0+sqrt(amount))
        elif (funded_forts and data
              and data[0] == BLANK and data[1] not in (0, bot.army)
              and mode in ('capture', 'advance', 'intercept', 'road_mobilize')
              and not bot.new_sight(target)):
            # A harmless already-seen plain must not inherit defensive urgency
            # merely because deadline_defense generated its capture proposal.
            score *= .45
            if mode == 'intercept':
                score = min(score, 180.0+2*sqrt(amount))
        result.append((score, src, dst, amount, mode, target))
    bot.last_report['emergency_priority'] = emergency
    return result


def reconnaissance(bot, choices, movable):
    """An overdue cheap frontier scout competes in the existing command pool."""
    proactive = bot.config.get('proactive_exploration', False)
    early = (len(getattr(bot,'known_owners',())) >= 2 and bot.calls >= 48
        and sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned) == 1)
    mature = (early or getattr(bot, '_advantage', False)
              or proactive and bot.calls > 100
              and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) >= 2)
    if (not bot.config.get('active_reconnaissance', False) or urgent(bot) or not mature):
        return
    patrol = getattr(bot, '_recon_patrol', None)
    carrier = patrol['position'] if patrol else None
    interval = (2 if carrier else 3) if proactive else 6
    age = bot.calls-getattr(bot, '_active_recon_last', 0)
    if age < interval or not proactive and not bot.enemies and not any(
            c[1] > 0 and c[1] != bot.army for c in bot.memory.values()):
        return
    fresh_owners = {owner for owner, model in bot.kings.items()
                    if bot.tick-model['seen'] <= bot.KING_MAX_AGE}
    unknown_owners = bot.known_owners-fresh_owners-bot.eliminated
    if not proactive and bot.kings and not unknown_owners:
        return
    opportunities = []
    enemy_focus = [pos for pos, cell in search_memory(bot).items()
                   if cell[1] in unknown_owners
                   and (first_contact_search_active(bot) or bot.tick-cell[3] <= 100)]
    regions = []
    state = bot.last_report.get('objective_state', {})
    if (bot.config.get('rearward_recon', False) and not fresh_owners and getattr(bot, '_advantage', False) and bot.calls >= 600
            and state.get('owned_producers', 0) >= 6
            and state.get('visible_friendly_units', 0) >= 2*state.get('visible_enemy_units', 0)):
        for owner in sorted(unknown_owners):
            territory = [p for p in enemy_focus if search_memory(bot)[p][1] == owner]
            if territory:
                territory.sort(key=lambda p: (hex_distance(bot.home, p), p), reverse=True)
                territory = territory[:max(1, (len(territory)+1)//2)]
                row = sum(p[0] for p in territory)/float(len(territory))
                col = sum(p[1] for p in territory)/float(len(territory))
                regions.append((max(0,min(bot.rows-1,int(row+(row-bot.home[0])*.4))),
                                max(0,min(bot.cols-1,int(col+(col-bot.home[1])*.4)))))
    for src in bot.owned:
        if movable.get(src, 0) < 2:
            continue
        focus_ready = False
        for dst in bot.neighbors[src]:
            data = bot.cells.get(dst)
            if (not data or data[1] == bot.army
                    or data[0] not in (BLANK,FORT)
                    or data[0] == FORT and data[1] == 0):
                continue
            gain = len(bot.new_sight(dst))
            stale = sum(n not in bot.cells and n in bot.memory
                        and bot.memory[n][1] not in (0, bot.army)
                        and bot.tick-bot.memory[n][3] >= 10 for n in bot.neighbors[dst])
            if not gain and not stale:
                continue
            if data[0] == FORT and not gain:
                continue
            required = max(3, data[2]+bot.counter(dst)+2)
            source_counter = bot.counter(src)
            packet_cap = max(128, required+16) if proactive else 128
            cap = min(packet_cap, movable[src], bot.cells[src][2]-source_counter-1)
            if proactive and cap < required:
                # Release the target's duplicate guard cost only when it
                # prevents a funded crossing; keep an adequate scout's tail.
                source_counter = bot.counter(src, excluded=(dst,))
                cap = min(packet_cap, movable[src], bot.cells[src][2]-source_counter-1)
            if cap < required or src != carrier and cap < (required if early else 8):
                continue
            # A visible defended border needs a real penetrating army. A tiny
            # fixed scout cap could leave an overwhelming economy blind.
            amount = min(cap, max(required, 48 if src != carrier else cap))
            # The scout may not fund itself by draining an exposed producer.
            if bot.cells[src][0] in (KING, FORT) and bot.cells[src][2]-amount <= source_counter:
                continue
            if not focus_ready:
                # Interior or unfunded sources need no enemy-territory scan.
                # Resolve the original distance/coordinate tie only once a
                # source has a usable reconnaissance crossing.
                focus = (min(enemy_focus, key=lambda p: (hex_distance(src, p), p))
                         if enemy_focus else getattr(bot, '_information_focus', None))
                if regions:
                    focus = min(regions,key=lambda p:(hex_distance(src,p),p))
                source_distance = hex_distance(src, focus) if focus else 0
                focus_ready = True
            toward = (source_distance-hex_distance(dst, focus)) if focus else 0
            if enemy_focus and toward <= 0 and not stale:
                # Once an opponent is located, lateral probes should search
                # its nearby flanks. Remote rear fog can wait for ordinary
                # expansion instead of consuming the front's command budget.
                near_front = regions and any(hex_distance(dst,p) <= 3 for p in enemy_focus)
                if not proactive or hex_distance(dst, focus) > 6 and not near_front:
                    continue
            value = gain+stale*2+max(0, toward)*2
            if src == carrier:
                value += 3
            if value:
                # A funded approach to an unlocated enemy king takes priority
                # over a side excursion. Flanks remain eligible when no such
                # crossing can be paid, instead of being vetoed outright.
                directed = bool(enemy_focus) and toward > 0
                opportunities.append((proactive and gain > 0,
                                      value if regions else int(directed),
                                      directed if regions else value,
                                      -amount, src, dst, amount))
    if opportunities:
        _, first, second, _, src, dst, amount = max(opportunities)
        value, directed = (first, second) if regions else (second, first)
        if (proactive and enemy_focus and not directed and not regions
                and any(choice[4] == 'rear_supply' for choice in choices)):
            # Early contact still funds the front first. The late overwhelming
            # economy above can afford side probes while searching for a king;
            # an available transport must not veto every such probe forever.
            return
        score = (1250.0 if proactive else 1100.0)+min(age, 30)+value
        # Do not let local economic waiting starve safe information indefinitely.
        if getattr(bot, '_advantage', False) and choices and max(choices)[4] in ('skirmish_wait','tactical_wait','bank'):
            score = max(score, 500100.0+value)
        choices.append((score, src, dst, amount, 'frontier_recon', dst))
        bot.last_report['active_recon'] = dict(due_age=age, interval=interval,
                                               marginal_information=value, packet=amount)


def committed(bot, mode):
    if mode == 'frontier_recon':
        bot._active_recon_last = bot.calls
    order = bot.pending
    if bot.config.get('contact_home_insurance', False) and order:
        before = order['before_dst']
        if (before[0] == FORT and before[1] == 0 and before[2] >= 12
                and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) == 1):
            # The first fort consumes the field army. Keep its investment
            # covered until that fort could naturally replace the cost.
            bot._first_fort_investment = dict(target=order['dst'],
                expires=bot.calls+2*before[2], cost=before[2])
