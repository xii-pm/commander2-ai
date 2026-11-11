"""Transactional, observation-triggered transfer of the pinned Probe policy.

BFS still evaluates its domains every observation. Only the selected policy's
decision state is retained. Both observers receive the actual committed order.
The activation and exit rules use current legal observations and own history.
"""
from std_recon import search_evidence_active
from copy import deepcopy
import math

from std_geometry import BLANK, KING, FORT, BLOCKED, hex_distance
from std_probe_policy import Agent as Probe
from std_objectives import FUNDED_STRIKE, fort_packet


class CappedScout(Probe):
    """The transferred scout cannot spend another domain's reserved stock."""
    def available(self, src, keep=None):
        ordinary = super().available(src, keep)
        caps = getattr(self, 'dispatch_caps', None)
        return min(ordinary, caps.get(src, 0)) if caps is not None else ordinary


def visible_king_duel(bot):
    """Return a current visible king linked by at most two known legal edges.

    This scopes policy ownership, not attack timing or a survival proof. No
    memory-only cell, unknown transit, future movement or hidden king is used.
    """
    paths = {bot.home: [bot.home]}
    front = [bot.home]
    for _ in range(2):
        following = []
        for pos in front:
            for nxt in bot.neighbors[pos]:
                if nxt in paths or nxt not in bot.cells or bot.cells[nxt][0] in BLOCKED:
                    continue
                paths[nxt] = paths[pos]+[nxt]
                cell = bot.cells[nxt]
                if cell[0] == KING and cell[1] not in (0, bot.army):
                    return dict(home=bot.home, enemy_king=nxt, route=paths[nxt],
                                edges=len(paths[nxt])-1, visible_king_units=cell[2])
                following.append(nxt)
        front = following
    return None


def visible_near_contact(bot):
    """Geometric entry veto, not a traversable route or incoming-force claim."""
    enemies = [(pos, cell[2]) for pos, cell in sorted(bot.cells.items())
               if cell[1] > 0 and cell[1] != bot.army and hex_distance(bot.home, pos) <= 2]
    return (dict(home=bot.home, radius=2, visible_enemies=enemies,
                 basis='current visible geometric proximity; not a travel-time claim')
            if enemies else None)


class OpeningCoordinator:
    def __init__(self, army, rows, cols, scout_only=False, release_scout=False):
        self.policy = (CappedScout if scout_only else Probe)(army, rows, cols)
        self.policy.EVERY_STEP = True
        self.policy.SCOUT_INTERVAL = 1
        self.started = None
        self.finished = False
        self.exit_reason = None
        self.release_scout = scout_only and release_scout
        self.last_scout_release = None
        self.last_bfs_mode = None
        self.last_bfs_wait = False
        self.last_bfs_search = False
        self.king_duel = None
        self.activation_evidence = None
        self.current_entry_veto = None

    def observe(self, bot):
        self.current_entry_veto = None
        order = self.policy.pending
        visits = self.policy.visits.get(order['dst'], 0) if order else 0
        self.last_scout_release = None
        self.policy.dispatch_caps = None
        self.policy.update(bot.cells, hill_hints=bot.hill_hints)
        if search_evidence_active(bot):
            self.policy._search_evidence = {p:d for p,d in bot.search_memory().items()
                                            if d[1] not in bot.eliminated}
        if (not self.release_scout or not order or order['role'] != 'external'
                or self.policy.pending is not None
                or self.policy.visits.get(order['dst'], 0) <= visits
                or order['sent'] != order['src_units']-1):
            return
        # A confirmed destination alone need not prove this particular packet
        # moved. Require the observed source depletion to fit the actual order,
        # allowing only the same bounded natural growth used by the observer.
        source = self.policy.cells.get(order['src'])
        age = max(1, self.policy.tick-order['time'])
        period = 2 if order['src_kind'] in (KING, FORT) else 50
        growth = source[2]-(order['src_units']-order['sent']) if source else -1
        if (source is None or source[1] != self.policy.army
                or not age//period <= growth <= int(math.ceil(age/float(period)))):
            return
        released = []
        for name in ('scout', 'scout_rear'):
            if getattr(self.policy, name) == order['src']:
                setattr(self.policy, name, None)
                released.append(name)
        if released:
            self.last_scout_release = dict(src=order['src'], dst=order['dst'],
                sent=order['sent'], released=released,
                reason='confirmed external order consumed full movable source')

    def active(self, bot):
        producers = sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned)
        if bot.config.get('opening_policy_duel_exit', False) and not self.finished:
            self.king_duel = visible_king_duel(bot)
            if self.king_duel:
                self.finished, self.exit_reason = True, 'visible_two_hop_king_duel'
        if self.started is not None and not self.finished:
            if producers >= 2:
                self.finished, self.exit_reason = True, 'second_producer'
            elif bot.calls-self.started >= bot.config['opening_policy_steps']:
                self.finished, self.exit_reason = True, 'observation_limit'
        signal = (self.last_bfs_search if bot.config.get('opening_policy_search_trigger', False)
                  else self.last_bfs_wait)
        wait_fallback = (bot.config.get('opening_policy_near_contact_fallback', False)
                         and bot.config.get('opening_policy_current_trigger', False)
                         and self.last_bfs_wait)
        if (self.can_enter(bot)
                and (not bot.config.get('opening_policy_wait_trigger', False)
                     or not bot.config.get('opening_policy_current_trigger', False) and signal
                     or wait_fallback)):
            self.started = bot.calls
            self.activation_evidence = ('current_exposure' if not bot.config.get('opening_policy_wait_trigger', False)
                else 'previous_actual_bfs_wait_fallback' if wait_fallback
                else 'previous_actual_bfs_search' if bot.config.get('opening_policy_search_trigger', False)
                else 'previous_actual_bfs_wait')
        return self.started is not None and not self.finished

    def can_enter(self, bot):
        return (self.started is None and not self.finished
                and getattr(bot, '_opening_contact', False)
                and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) == 1)

    def enter_from_preview(self, bot, move, report):
        """A current preview is explicitly different from an actual BFS order."""
        if report.get('opening_memory_exchange'):
            return False
        if (not bot.config.get('opening_policy_wait_trigger', False)
                or not bot.config.get('opening_policy_current_trigger', False)
                or not self.can_enter(bot)):
            return False
        searching = bot.config.get('opening_policy_search_trigger', False)
        signal = ('skirmish' in report if searching else
                  move is None and report.get('mode') == 'skirmish_wait')
        if not signal:
            return False
        if bot.config.get('opening_policy_near_contact_fallback', False):
            self.current_entry_veto = visible_near_contact(bot)
            if self.current_entry_veto:
                return False
        self.started = bot.calls
        self.activation_evidence = 'current_bfs_search_preview' if searching else 'current_bfs_wait_preview'
        return True

    def record_bfs(self, bot, move, report):
        """Only a selected real BFS wait may activate the next observation."""
        self.last_bfs_mode = report.get('mode')
        local_exchange = bool(report.get('opening_memory_exchange'))
        self.last_bfs_wait = (not local_exchange and move is None and self.last_bfs_mode == 'skirmish_wait'
            and getattr(bot, '_opening_contact', False)
            and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) == 1)
        self.last_bfs_search = (not local_exchange and 'skirmish' in report
            and getattr(bot, '_opening_contact', False)
            and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) == 1)

    def record_external(self, move):
        # Observation confirmation, visits and growth witnesses see the actual
        # order. An external action cannot advance a Probe scout/assault task.
        if not move:
            return
        src, dst, sent = move
        source, target = self.policy.cells[src], self.policy.cells[dst]
        self.policy.pending = dict(src=src, dst=dst, old_owner=target[1],
            old_units=target[2], src_units=source[2], src_kind=source[0],
            dst_kind=target[0], sent=sent, time=self.policy.tick, role='external')


def legal(bot, move):
    if move is None:
        return True
    src, dst, amount = move
    return (src in bot.cells and dst in bot.cells
            and bot.cells[src][1] == bot.army and dst in bot.neighbors[src]
            and bot.cells[dst][0] not in BLOCKED and type(amount) is int
            and 0 < amount < bot.cells[src][2]
            and (bot.cells[dst][1] == bot.army or amount > bot.cells[dst][2])
            and fort_packet(bot, src, dst, amount, 'opening_policy') == amount)


def scout_preview(bot, preview, status):
    """Replan a persistent scout using only an otherwise idle BFS command."""
    if preview.pending:
        status['preview_rejected'] = 'previous_scout_order_unconfirmed'
        return None
    curve = bot.last_report.get('threat_curve', [0]*7)[:7]
    required = max(curve[1:] or [0])
    held = bot.cells[bot.home][2]
    if held < required:
        status['preview_rejected'] = 'home_current_stock_below_six_step_observed_threat'
        return None
    protected = bot.protected()
    caps = {pos: 0 if pos in protected else min(48, bot.available(pos)) for pos in bot.owned}
    caps[bot.home] = min(caps[bot.home], max(0, held-required-1))
    preview.dispatch_caps = caps
    preview.select_rally()
    move = preview.scout_action(force=True)
    if not move:
        status['preview_rejected'] = 'no_funded_scout'
        return None
    if not legal(bot, move):
        status['preview_rejected'] = 'illegal_current_order'
        return None
    src, dst, count = move
    if count > caps.get(src, 0):
        status['preview_rejected'] = 'selected_count_exceeds_authorized_stock'
        return None
    target = bot.cells[dst]
    residual = count+target[2] if target[1] == bot.army else count-target[2]
    counter = bot.counter(dst)
    if residual <= counter:
        status['preview_rejected'] = 'first_hop_not_above_visible_counter'
        return None
    status['scout_authorization'] = dict(source_cap=caps[src], dispatched=count,
        home_current=held, six_step_observed_threat=required,
        first_hop_residual=residual, first_hop_visible_counter=counter,
        budget_limit=48, future_growth_funds=False)
    return move


def decide(bot):
    scout_only = bot.config.get('opening_policy_scout_only', False)
    if not hasattr(bot, '_opening_coordinator'):
        bot._opening_coordinator = OpeningCoordinator(bot.army, bot.rows, bot.cols, scout_only,
            bot.config.get('opening_policy_release_scout', False))
    coordinator = bot._opening_coordinator
    coordinator.observe(bot)
    enabled = coordinator.active(bot)
    possible_preview_entry = (bot.config.get('opening_policy_wait_trigger', False)
        and bot.config.get('opening_policy_current_trigger', False) and coordinator.can_enter(bot))
    # An observation checkpoint excludes the independent policy to avoid
    # recursive copies. Shared immutable geometry is never changed here.
    checkpoint = (deepcopy({key: value for key, value in bot.__dict__.items()
                           if key not in ('_opening_coordinator', 'neighbors')})
                  if enabled or possible_preview_entry else None)
    main_move = bot.decide_observed()
    main_report = dict(bot.last_report)
    if possible_preview_entry:
        enabled = coordinator.enter_from_preview(bot, main_move, main_report)
    status = dict(active=enabled, started=coordinator.started,
                  elapsed=(bot.calls-coordinator.started if coordinator.started is not None else 0),
                  limit=bot.config['opening_policy_steps'], exit=coordinator.exit_reason,
                  bfs_mode=main_report.get('mode'), selected='bfs', scout_only=scout_only)
    status.update(wait_trigger=bot.config.get('opening_policy_wait_trigger', False),
                  previous_bfs_mode=coordinator.last_bfs_mode,
                  previous_bfs_wait=coordinator.last_bfs_wait,
                  previous_bfs_search=coordinator.last_bfs_search,
                  activation_evidence=coordinator.activation_evidence,
                  current_trigger=bot.config.get('opening_policy_current_trigger', False),
                  search_trigger=bot.config.get('opening_policy_search_trigger', False),
                  near_contact_fallback=bot.config.get('opening_policy_near_contact_fallback', False))
    if coordinator.current_entry_veto:
        status['current_entry_veto'] = coordinator.current_entry_veto
    if coordinator.king_duel:
        status['king_duel'] = coordinator.king_duel
    if coordinator.last_scout_release:
        status['confirmed_scout_release'] = coordinator.last_scout_release
    # An immediate finishing move and a real unconfirmed order keep their
    # priority. A rejected preview never changes pending or mission state.
    scout_transport = (scout_only and bot.config.get('opening_policy_scout_priority', False)
        and main_move is not None and main_report.get('mode') in ('advance', 'supply')
        and main_move[0] == coordinator.policy.scout
        and bot.cells[main_move[1]][1] == bot.army)
    scout_claim = (scout_only and bot.config.get('opening_policy_scout_claim_priority', False)
        and main_move is not None and main_report.get('mode') == 'capture'
        and coordinator.policy.scout is not None
        and bot.cells[main_move[1]][0] == BLANK
        and bot.cells[main_move[1]][1] == 0 and bot.cells[main_move[1]][2] <= 1)
    continuing_scout = scout_transport or scout_claim
    mode = main_report.get('mode')
    king_priority = (
        bot.config.get('king_forward_pressure', False) and mode in ('king_advance', 'assault')
        or bot.config.get('king_two_command_strike', False) and mode == 'tempo_king'
        or mode == 'king_advance' and (bot.config.get('king_idle_field_approach', False)
                                     or bot.config.get('king_merge_approach', False))
        or bot.config.get('objective_priority', False)
        and main_report.get('score', 0) >= FUNDED_STRIKE)
    if (enabled and not king_priority and main_report.get('mode') not in ('finish_king', 'await_action', 'home_clear', 'home_sortie', 'home_dispatch')
            and (not scout_only or main_move is None or continuing_scout)):
        preview = deepcopy(coordinator.policy, {id(coordinator.policy.neighbors): coordinator.policy.neighbors})
        move = scout_preview(bot, preview, status) if scout_only else preview.decide_observed()
        if continuing_scout and move and move[0] != coordinator.policy.scout:
            status['preview_rejected'] = 'active_scout_did_not_continue'
            move = None
        from std_reversal_recovery import blocked as blocked_cycle_move
        cycle_blocked = bool(move and blocked_cycle_move(bot,move[0],move[1],'opening_policy'))
        if cycle_blocked:
            status['preview_rejected'] = 'confirmed_friendly_command_cycle'
            bot.last_report['opening_cycle_rejected'] = dict(src=move[0],dst=move[1],send=move[2])
        if not cycle_blocked and legal(bot, move) and (not scout_only or move is not None):
            geometry = bot.neighbors
            bot.__dict__.clear()
            bot.__dict__.update(checkpoint)
            bot.neighbors = geometry
            bot._opening_coordinator = coordinator
            # BFS tasks stop on the first actual handoff. Only observed moves
            # can create progress while another policy owns the commands.
            bot.mission = None
            coordinator.policy = preview
            report = dict(bot.last_report)
            if 'repeated_cycle_recovery' in main_report:
                report['repeated_cycle_recovery'] = main_report['repeated_cycle_recovery']
            status.update(selected='probe', source_mode=preview.last_report.get('mode'))
            if scout_transport:
                status['preempted_ordinary_scout_transport'] = True
            if scout_claim:
                status['preempted_neutral_plain_claim'] = True
            report.update(mode='opening_policy', opening_policy=status,
                          opening_policy_report=dict(preview.last_report),
                          opening_policy_bfs_preview=main_report,
                          reason='bounded fragile-opening policy coordination')
            for key in ('src', 'dst', 'send', 'score', 'target', 'wait_reason'):
                report.pop(key, None)
            if move:
                src, dst, amount = move
                bot.pending = dict(src=src, dst=dst, sent=amount, role='opening_policy',
                    tick=bot.tick, before_src=bot.cells[src], before_dst=bot.cells[dst], advance=False)
                bot._committed_edge, bot._committed_target = (src, dst), dst
                report.update(src=src, dst=dst, send=amount)
            else:
                report['wait_reason'] = preview.last_report.get('mode', 'hold')
            bot.last_report = report
            return bot.finish(move)
        if 'preview_rejected' not in status:
            status['preview_rejected'] = 'illegal_current_order'
    coordinator.record_bfs(bot, main_move, main_report)
    coordinator.record_external(main_move)
    bot.last_report['opening_policy'] = status
    return main_move
