"""Every-observation pure proposals; exactly one proposal is committed.

Generators do not call action(), mutate missions, or reserve a future command.
All tactical and economic domains are compared on every callback.
"""
from std_recon import first_contact_search_active
from std_maneuver import observe as observe_maneuver, committed as commit_maneuver
from std_maneuver import propose as maneuver_proposals
from collections import deque
from math import ceil, sqrt
from heapq import heappop, heappush

from std_geometry import BLANK, KING, FORT, MARSH, BLOCKED, hex_distance
from std_merge import merge_schedule
from std_stage_value import collection_departure_allowed
from std_skirmish import search as skirmish_search
from std_reserve import ArmyLedger
from std_reinforcement import select_cover
from std_security import arbitrate as deadline_arbitrate
from std_threat import shared_curve
from std_tactical import search as tactical_search
from std_recovery import observe as observe_recovery, propose as recovery_proposals
from std_producer import interception_keep, propose as producer_proposals
from std_investment import plan as investment_plan, propose as investment_proposals
from std_king_bridge import plan as king_bridge_plan, propose as king_bridge_proposals
from std_commitment import prepare as prepare_commitment, retain_funded, committed as commit_producer
from std_opening import interception_keep as opening_interception_keep, discovery_keep as opening_discovery_keep
from std_opening import remembered_king_force, continuation_allowed, continuation_funded
from std_mobility import MobileWarning
from std_departure_warning import DepartureWarning
from std_convoy import prepare as prepare_convoy, propose as convoy_proposals, committed as commit_convoy
from std_packets import minimum_dispatch, dispatch_with_tail, fort_expedition
from std_patience import allowed as patient_intercept_allowed
from std_colonize import prepare as prepare_colonize, propose as colonize_proposals, committed as commit_colonize
from std_reconnaissance import propose as recon_wait_proposals, propose_stalled_contact
from std_king_pressure import propose as king_pressure_proposals
from std_king_pressure import propose_idle_field as king_idle_field_proposals
from std_king_pressure import propose_merge as king_merge_proposals
from std_king_tempo import plan as king_tempo_plan, propose as king_tempo_proposals
from std_opening_exchange import propose as opening_exchange_proposals
from std_repair import prepare as prepare_repair, propose as repair_proposals
from std_search_value import active as search_reveal_active, bonus as search_reveal_bonus
import std_objectives as objectives
from std_corridor import propose as corridor_proposals, committed as commit_corridor
from std_rear_supply import propose as rear_supply_proposals
from std_rear_supply import observe as observe_rear_supply, committed as commit_rear_supply
from std_search_column import propose as search_column_proposals, committed as commit_search_column
from std_king_recovery import observe as observe_king_recovery, propose as king_recovery_proposals
from std_main_column import propose as main_column_proposals


def frontier_target_value(bot, target):
    """Observation-only endpoint value, shared by all routes this turn."""
    kind, owner, _ = bot.cells[target]
    sight = bot.new_sight(target)
    value = 240 if kind == FORT else 95 if owner > 0 else 58
    if kind == FORT:
        value = bot.config.get('production_value', 240)
        if owner > 0:
            value *= 1.3
    if kind == MARSH:
        value = 12
    value += 4 * len(sight) + 8 * len(sight & bot.hill_hints)
    value += search_reveal_bonus(bot, sight)
    if bot.config.get('information', False):
        warning = sum(bot.risk_dist.get(p, 999) <= 4 for p in sight)
        value += 18 * warning
    return value


class Continuous:
    def resolve_pending(self):
        self._observed_pending = dict(self.pending) if self.pending else None
        self._pending_replanned = False
        prior_visits = (self.visits.get(self.pending['dst'], 0) if self.pending else 0)
        super().resolve_pending()
        self._last_order_confirmed = bool(self._observed_pending and
            self.visits.get(self._observed_pending['dst'], 0) > prior_visits)
        from std_recall_goal import observe as observe_recall_goal
        observe_recall_goal(self)
        if self.config.get('fresh_replan', False) and self.pending:
            pending = self.pending
            # A contested endpoint can invalidate exact troop conservation.
            # Replan after its observation changes; never claim the old capture
            # succeeded, advance a mission, or resend on an identical snapshot.
            changed = (self.cells.get(pending['src']) != pending['before_src'] or
                       self.cells.get(pending['dst']) != pending['before_dst'])
            if changed:
                self.pending = None
                self._pending_replanned = True

    def available(self, src, keep=None):
        if not self.config.get('deadline_defense', False):
            return super().available(src, keep)
        if src not in self.cells or self.cells[src][1] != self.army:
            return 0
        reserve = self.home_keep if src == self.home else 1
        reserve = max(reserve, getattr(self, '_active_reserves', {}).get(src, 1))
        return max(0, self.cells[src][2] - max(1, reserve, keep or 0))

    def action(self, src, dst, count, role, reason, advance=False):
        if role == 'relief_capital':
            from std_adjacent_threat_relief import execute as execute_relief_capital
            return execute_relief_capital(self,src,dst,count,role,
                lambda: super(Continuous,self).action(src,dst,count,role,reason,advance))
        if role == 'adjacent_income':
            from std_adjacent_income import execute as execute_adjacent_income
            return execute_adjacent_income(self,src,dst,count,role,
                lambda: super(Continuous,self).action(src,dst,count,role,reason,advance))
        if role == 'nearby_capital':
            from std_nearby_capital import execute as execute_nearby_capital
            return execute_nearby_capital(self,src,dst,count,role,
                lambda: super(Continuous,self).action(src,dst,count,role,reason,advance))
        if not patient_intercept_allowed(self, (src, dst, count)):
            return None
        investment = (getattr(self, '_producer_investment', None) if role == 'investment'
                      else getattr(self, '_king_bridge', None) if role == 'bridge_king'
                      else getattr(self, '_king_tempo', None) if role == 'tempo_king' else None)
        if (investment and investment['funded']
                and src == self.home and dst == investment['route'][1]
                and count == investment['packet']):
            saved_keep = self.home_keep
            saved_reserve = self._active_reserves.get(src,1)
            self.home_keep = investment['guard']
            self._active_reserves[src] = investment['guard']
            try:
                return super().action(src,dst,count,role,reason,advance)
            finally:
                self.home_keep = saved_keep
                self._active_reserves[src] = saved_reserve
        if (src,dst,count,role) in getattr(self,'_home_scoped_auth',{}):
            from std_home_watch import execute as home_execute
            return home_execute(self,src,dst,count,role,
                lambda: super(Continuous,self).action(src,dst,count,role,reason,advance))
        keep = interception_keep(self,src,dst) if role == 'intercept' else None
        if (keep is not None and count > self.cells[dst][2]
                and count <= self.cells[src][2]-keep):
            saved = self._active_reserves.get(src,1)
            self._active_reserves[src] = keep
            try:
                return super().action(src,dst,count,role,reason,advance)
            finally:
                self._active_reserves[src] = saved
        if (role == 'tactical' and (self.config.get('tactical_depth2', False)
                    or self.last_report.get('close_duel_continuation', False))
                or role == 'skirmish' and src == self.home
                and self.config.get('skirmish_home_stock',False)):
            # A local search evaluates its exact first dispatch. Do not
            # silently clamp the chosen amount to a different command.
            if (not self.pending and src in self.cells and dst in self.cells
                    and self.cells[src][1] == self.army
                    and dst in self.neighbors[src] and self.cells[dst][0] not in BLOCKED
                    and type(count) is int and 0 < count < self.cells[src][2]
                    and (self.cells[dst][1] == self.army or count > self.cells[dst][2])):
                self.pending = dict(src=src, dst=dst, sent=count, role=role, tick=self.tick,
                    before_src=self.cells[src], before_dst=self.cells[dst], advance=advance)
                self.last_report.update(mode=role,src=src,dst=dst,send=count,reason=reason)
                return src,dst,count
            return None
        if (self.config.get('response_pool', False) and role in ('defend', 'intercept')
                and src != self.home and src in getattr(self, '_active_reserves', {})):
            saved = self._active_reserves[src]
            self._active_reserves[src] = 1
            try:
                return super().action(src, dst, count, role, reason, advance)
            finally:
                self._active_reserves[src] = saved
        if (self.config.get('deadline_defense', False)
                and (role == 'intercept' and src == self.home or role == 'finish_king')
                and src in self.cells and self.cells[src][1] == self.army
                and not self.pending and dst in self.cells
                and dst in self.neighbors[src] and self.cells[dst][0] not in BLOCKED):
            count = int(min(count, self.cells[src][2] - 1))
            if count > self.cells[dst][2]:
                self.pending = dict(src=src, dst=dst, sent=count, role=role, tick=self.tick,
                    before_src=self.cells[src], before_dst=self.cells[dst], advance=advance)
                self.last_report.update(mode=role, src=src, dst=dst, send=count, reason=reason)
                return src, dst, count
            return None
        return super().action(src, dst, count, role, reason, advance)

    def home_guard_hold(self):
        if self.config.get('deadline_defense', False):
            return 0
        return super().home_guard_hold()

    def home_contact_floor(self, force):
        if self.config.get('deadline_defense', False):
            return max(2, force + 2)
        return super().home_contact_floor(force)

    def threat_curve(self, horizon=12, exclude=(), zero_uncertainty=True):
        cache = getattr(self, '_threat_projection_cache', None)
        excluded = tuple(sorted(exclude))
        key = horizon, excluded, bool(zero_uncertainty)
        if cache is not None and key in cache:
            return list(cache[key])
        curve = self._project_threat(horizon, excluded, zero_uncertainty)
        if cache is not None:
            cache[key] = tuple(curve)
        return curve

    def _project_threat(self, horizon, exclude, zero_uncertainty):
        curve = [0] * (horizon + 1)
        threats = []
        by_owner = {}
        margin = self.config.get('threat_margin', 2)
        for p, data in self.memory.items():
            if p in exclude:
                continue
            kind, owner, units, seen = data
            age = self.tick - seen
            if owner <= 0 or owner == self.army or owner in self.eliminated:
                continue
            if age > 4:
                remembered = remembered_king_force(self, p, age)
                if remembered is None:
                    continue
                units = max(units, remembered)
            if p in self.cells:
                kind, owner, units = self.cells[p]
                age = 0
            distance = max(1, self.risk_dist.get(p, 999) - age)
            if distance <= horizon:
                threats.append((distance, units, kind))
                by_owner.setdefault(owner, []).append((distance, units, kind))
        for h in range(1, horizon + 1):
            # Independent-route approximation under one command per step.
            # Shared trunks can make several stacks arrive sooner than the
            # sum of their distances, so this is not a general upper bound.
            incoming = 0
            # Each rival has its own command every step. A shared budget
            # would undercount simultaneous approaches in multiplayer games.
            for arrivals in by_owner.values():
                budget = [0] * (h + 1)
                for distance, units, kind in arrivals:
                    if distance > h:
                        continue
                    force = max(0, units - distance) + (int(ceil(h * .5)) if kind in (KING, FORT) else 0)
                    for t in range(h, distance - 1, -1):
                        budget[t] = max(budget[t], budget[t-distance] + force)
                incoming += max(budget)
            margin = self.config.get('threat_margin', 2)
            if self.config.get('opening_defense', False):
                # Contact before building an economy leaves no funded second
                # line. Keep a larger uncertainty margin for that exposed king.
                if (not hasattr(self, '_opening_contact')
                        and any(self.risk_dist.get(p, 999) <= 6 for p in self.enemies)):
                    self._opening_contact = (len(self.owned) <= 8
                        and sum(self.cells[p][2] for p in self.owned) <= 12)
                margin = 6 if getattr(self, '_opening_contact', False) else 2
            opening_uncertainty = (zero_uncertainty and self.config.get('opening_zero_mobile',False)
                and getattr(self,'_opening_contact',False)
                and any(distance <= min(h,self.config.get('opening_zero_radius',12))
                        for distance,_,_ in threats))
            curve[h] = incoming + (margin if threats and (incoming or opening_uncertainty) else 0)
        if (self.config.get('shared_threat', False)
                and getattr(self, '_opening_contact', True) is False):
            if getattr(self, '_shared_threat_tick', None) != self.tick:
                self._shared_threat_tick = self.tick
                self._shared_threat_cache = {}
            key = tuple(sorted(exclude))
            if key not in self._shared_threat_cache:
                self._shared_threat_cache[key] = shared_curve(self.neighbors,self.cells,
                    self.home,self.army,self.risk_dist,12,exclude)
            projection = self._shared_threat_cache[key]
            curve = [max(force,projection[h]+(margin if projection[h] else 0))
                     for h,force in enumerate(curve)]
        if self.config.get('mobile_memory', 0):
            if not hasattr(self, '_mobile_warning'):
                self._mobile_warning = MobileWarning()
            projected, _ = self._mobile_warning.curve(self, horizon, margin, exclude)
            curve = [max(force, warning) for force, warning in zip(curve, projected)]
        if self.config.get('mobile_departure_steps', 0):
            if not hasattr(self, '_departure_warning'):
                self._departure_warning = DepartureWarning()
            projected, _ = self._departure_warning.curve(self, horizon, margin)
            # Capturing a visible remnant does not erase a packet already
            # missing in fog; exclude applies only to ordinary visible cells.
            curve = [max(force, warning) for force, warning in zip(curve, projected)]
        from std_force_belief import augment as belief_augment
        base = belief_augment(self,curve,horizon,margin)
        if not getattr(self,'map314',0):
            from std_rival_pressure import augment as observe_pressure
            observe_pressure(self,base,horizon,exclude,zero_uncertainty)
            if 'rival_pressure' in self.last_report:
                self.last_report['rival_pressure']['hard_applied'] = False
        return base

    def reserve_home(self, horizon, exclude_owner=None):
        if not self.home:
            self.last_home_reserve_by_owner = {}
            return 0
        if not self.config.get('deadline_defense', False):
            return super().reserve_home(horizon, exclude_owner)
        adaptive = self.config.get('adaptive_home_reserve', False)
        projection = self.threat_curve(8 if adaptive else 6)
        curve = projection[:7]
        self.last_home_reserve_by_owner = {}
        base = max(2, self.config.get('base_guard', 2))
        exposure_release = self.config.get('king_exposure_release', False)
        if exposure_release:
            # The SDK exposes no enemy vision. The user's observable proxy
            # latches permanently after an enemy enters the king's one ring.
            exposed = getattr(self, '_king_exposed', False)
            adjacent = [p for p in self.enemies if hex_distance(self.home,p) <= 1]
            if adjacent and not exposed:
                self._king_exposure_first = dict(tick=self.tick,positions=adjacent)
            self._king_exposed = exposed or bool(adjacent)
            if not self._king_exposed:
                base = 1
        if (self.config.get('precontact_guard_one', False)
                and not hasattr(self, '_opening_contact')):
            # ProbeFort's native opening can dispatch at two total soldiers.
            # This changes only the pre-contact minimum; observed threats and
            # the proportional economic reserve still apply without a cap.
            base = 1
        reserve = max([base] + [max(0, force - (h-1)//2) for h, force in enumerate(curve) if h])
        invested = (self.config.get('contact_home_insurance', False)
                    and objectives.investment_guard_active(self))
        if (self.config.get('stable_commitment', False)
                and (not exposure_release or self._king_exposed
                     or self.config.get('contact_home_insurance', False)
                        and invested and getattr(self, '_contact_seen', False))):
            # The king is the only irreversible objective. A proportional
            # reserve also covers a large stack entering sight late.
            share = self.config.get('guard_share', 18)/100.0
            insurance = int(ceil(sum(self.cells[p][2] for p in self.owned) * share))
            released = False
            if adaptive:
                ring = set(self.neighbors[self.home])
                ring.update(n for p in tuple(ring) for n in self.neighbors[p])
                clear = all(p in self.cells and self.cells[p][1] in (0, self.army)
                            for p in ring)
                producers = sum(self.cells[p][0] in (KING,FORT) for p in self.owned)
                dominant = (producers >= 20 and
                    sum(self.cells[p][2] for p in self.owned) >=
                    2*sum(self.cells[p][2] for p in self.enemies))
                observed_ring = dominant and all(p in self.cells for p in ring)
                if observed_ring:
                    # Visible intruders are already priced by the full forecast.
                    # Their presence alone must not trap a growing share of
                    # the entire empire in an otherwise observed home area.
                    insurance = min(insurance,max(self.threat_curve(12))+32)
                    released = insurance < int(ceil(sum(self.cells[p][2] for p in self.owned)*share))
                if clear:
                    # The former permanent 18% latch grew with every remote
                    # field army even after the home area was fully cleared.
                    forecast = max([12]+[max(0, force-(h-1)//2)
                                         for h, force in enumerate(projection) if h])
                    reduced = min(insurance, forecast)
                    if exposure_release and not self._king_exposed and not invested:
                        reduced = min(reduced, reserve)
                    released = reduced < insurance
                    insurance = reduced
            self._home_reserve_release = dict(released=released, insurance=insurance,
                                              threat_keep=reserve, horizon=len(projection)-1)
            reserve = max(reserve, insurance)
        if any(self.risk_dist.get(p, 999) <= 6 for p in self.enemies):
            self._contact_seen = True
        if getattr(self, '_contact_seen', False):
            reserve = max(reserve, self.config.get('contact_guard', 0))
        if any(self.risk_dist.get(p, 999) <= 3 for p in self.enemies):
            local = sum(self.cells[p][2] for p in self.owned
                        if self.risk_dist.get(p, 999) <= 6)
            reserve = max(reserve, int(ceil(local * self.config.get('contact_share', 0)/100.0)))
        window = self.config.get('fog_memory', 0)
        if window:
            seen = max([0]+[max(0, self.cells[p][2]-self.risk_dist.get(p, 999)+2)
                                for p in self.enemies if self.risk_dist.get(p, 999) <= 6])
            history = [(t, force) for t, force in getattr(self, '_fog_history', [])
                       if self.tick-t <= window]
            if seen:
                history.append((self.tick, seen))
            self._fog_history = history
            self._fog_guard = max([0]+[max(0, force-(self.tick-t)//8) for t, force in history])
            reserve = max(reserve, self._fog_guard)
        if self.config.get('conservation_guard', False):
            if not hasattr(self, '_army_ledger'):
                self._army_ledger = ArmyLedger()
            self._army_estimate = self._army_ledger.observe(self)
            self._conservation_keep = 0
            if any(self.risk_dist.get(p, 999) <= 6 for p in self.enemies):
                self._conservation_keep = self._army_estimate['mobile']+self.config.get('ledger_margin', 3)
                reserve = max(reserve, self._conservation_keep)
        from std_home_watch import release as home_watch_release
        from std_blind_opening import reserve as blind_reserve
        reserve = blind_reserve(self,reserve,75,0,True)
        return home_watch_release(self, reserve)

    def decide(self, cells, hill_hints=None):
        if not self.config.get('continuous', False):
            return super().decide(cells, hill_hints)
        # Only one public observation owns these results. Different deadlines,
        # exclusions and uncertainty rules stay separate; callers own copies.
        self._threat_projection_cache = {}
        try:
            result = self._continuous_decide(cells, hill_hints)
            from std_response_control import returned as response_returned
            response_returned(self,result)
            return result
        finally:
            self._threat_projection_cache = None

    def _continuous_decide(self, cells, hill_hints):
        prior_cells, prior_order = self.cells, self.pending
        self._active_reserves = {}
        self.update(cells, hill_hints)
        from std_response_control import observe as observe_response
        observe_response(self)
        if not self.home or not self.owned:
            self.last_report['mode'] = 'eliminated'
            return None
        objectives.observe(self, prior_cells, prior_order)
        observe_king_recovery(self, prior_cells, prior_order)
        from std_home_watch import observe_export
        observe_export(self)
        from std_reversal_recovery import observe as observe_command_cycle
        observe_command_cycle(self)
        from std_transport_path_guard import observe as observe_transport_path
        observe_transport_path(self)
        if self.config.get('consistent_dispatch_deadline', False):
            from std_dispatch_deadline import observe as observe_dispatch_deadline
            observe_dispatch_deadline(self)
        observe_rear_supply(self)
        observe_maneuver(self)
        if self.config.get('frontier_drought_steps', 0):
            from std_frontier_sources import observe_progress
            observe_progress(self)
        if self.config.get('frontier_confirmed_handoff', False):
            from std_frontier_handoff import observe as observe_frontier_handoff
            observe_frontier_handoff(self)
        if self.config.get('exchange_recovery', False):
            observe_recovery(self)
        if self.config.get('stagnation_recovery', False):
            self.update_economic_progress()
        self.last_report['pending_replanned'] = self._pending_replanned
        self.last_report['opening_contact'] = getattr(self, '_opening_contact', False)
        if self.config.get('mobile_memory', 0):
            if not hasattr(self, '_mobile_warning'):
                self._mobile_warning = MobileWarning()
            _, records = self._mobile_warning.curve(self, 12,
                6 if getattr(self, '_opening_contact', False) else self.config.get('threat_margin', 2))
            self.last_report['mobile_uncertainty'] = records
        if self.config.get('conservation_guard', False):
            self.last_report['army_estimate'] = self._army_estimate
        if self.config.get('mobile_departure_steps', 0):
            _, records = self._departure_warning.curve(self, 12,
                6 if getattr(self, '_opening_contact', False) else self.config.get('threat_margin', 2))
            self.last_report['departure_warning'] = dict(records=records,
                events=list(self._departure_warning.events),clock='legal observations')
        self.last_report['evaluated'] = ['king', 'defense', 'production', 'frontier', 'supply', 'recon']
        if self.config.get('opening_policy', False):
            from std_opening_policy import decide as opening_policy_decide
            return opening_policy_decide(self)
        return self.decide_observed()

    def decide_observed(self):
        """Evaluate and commit one main-policy decision after observation."""
        if self.config.get('king_exposure_release', False):
            self.last_report['king_exposure'] = dict(exposed=getattr(self,'_king_exposed',False),
                first=getattr(self,'_king_exposure_first',None),
                proxy='ever observed an enemy within one hex of our king',
                proportional_insurance=getattr(self,'_king_exposed',False))
        if self.config.get('adaptive_home_reserve', False):
            self.last_report['home_reserve_release'] = getattr(self, '_home_reserve_release', None)
        from std_investment_execution import prepare as prepare_investment_column
        prepare_investment_column(self)
        from std_nearby_capital import prepare as prepare_nearby_capital
        prepare_nearby_capital(self)
        prepare_convoy(self)
        prepare_repair(self)
        prepare_colonize(self)
        prepare_commitment(self)
        self._producer_investment = investment_plan(self)
        self._king_bridge = king_bridge_plan(self)
        if self._producer_investment:
            self.last_report['producer_investment'] = self._producer_investment
        if self._king_bridge:
            self.last_report['king_bridge'] = self._king_bridge
        choices = []
        self._unfunded_neutral_collections = set()
        self._continuation_cache = {}
        self._information_focus = self.information_focus()
        self.last_report['information_focus'] = self._information_focus
        reserves = {p: self.cells[p][2] - self.available(p) for p in self.owned}
        if self.config.get('deadline_defense', False):
            reserves = {p: self.home_keep if p == self.home else 1 for p in self.owned}
        reserves[self.home] = opening_discovery_keep(self,reserves[self.home])
        from std_post_capital_guard import reserve as post_capital_reserve
        reserves[self.home] = max(reserves[self.home],post_capital_reserve(self))
        if self.config.get('consistent_dispatch_deadline', False):
            from std_dispatch_deadline import reserve as dispatch_deadline_reserve
            reserves[self.home] = max(reserves[self.home], dispatch_deadline_reserve(self))
            if (len(getattr(self,'known_owners',())) >= 2
                    and sum(self.cells[p][0] in (KING,FORT) for p in self.owned) >= 2):
                from std_dispatch_deadline import floor as dispatch_floor
                keep = dispatch_floor(self.threat_curve(12))
                reserves[self.home] = max(reserves[self.home],keep)
                self.last_report['uniform_dispatch'] = dict(horizon=12,keep=keep,
                    ordinary_reserve=reserves[self.home],forecast_only=True)
        if self._producer_investment:
            reserves[self.home] = max(reserves[self.home],self._producer_investment['goal'])
        if (self.config.get('producer_reserve', False)
                and getattr(self, '_opening_contact', True) is False):
            # Reserve before transport/capture planning so each proposal uses
            # the actual surplus of an exposed producer. Timed king rescue
            # and immediate elimination retain their existing escape paths.
            guarded = []
            for p in self.owned:
                if self.cells[p][0] == FORT and self.counter(p):
                    reserves[p] = max(reserves[p], self.counter(p)+1)
                    guarded.append((p,reserves[p]))
            self.last_report['producer_reserves'] = guarded
        if self.config.get('topology', False):
            critical = self.articulations()
            for p in self.owned:
                if p in critical or self.cells[p][0] == FORT:
                    danger = self.counter(p)
                    if danger:
                        reserves[p] = max(reserves[p], danger+1)
            self.last_report['critical_roads'] = len(critical)
        if (self.config.get('response_pool', False)
                and getattr(self, '_opening_contact', True) is False):
            self.protect_response_pool(reserves)
        from std_single_capital_fortress import prepare as prepare_single_fortress
        prepare_single_fortress(self,reserves)
        from std_nearby_retention import prepare as prepare_nearby_retention
        prepare_nearby_retention(self,reserves)
        self._active_reserves = reserves
        if self.config.get('packet_budget', False):
            for p in self.owned:
                reserves[p] = max(reserves[p], 4 if p == self.home else 2 if self.cells[p][0] == FORT else 1)
        movable = {p: max(0, self.cells[p][2] - reserves[p]) for p in self.owned}
        self._king_tempo = king_tempo_plan(self)
        if self._king_tempo:
            self.last_report['king_tempo'] = self._king_tempo
        king_tempo_proposals(choices, self._king_tempo)
        objectives.immediate_kings(self, choices)
        from std_king_opportunity import propose as propose_king_opportunity
        propose_king_opportunity(self,choices,movable,reserves)
        self.continuous_defense(choices, movable)
        from std_home_watch import propose as home_watch_proposals
        home_watch_proposals(self, choices, reserves)
        if self.config.get('home_corridor_delivery', False):
            corridor_proposals(self, choices)
        king_recovery_proposals(self, choices, reserves)
        convoy_proposals(self, choices)
        colonize_proposals(self, choices, reserves)
        investment_proposals(self,choices,self._producer_investment)
        from std_investment_execution import propose as investment_column_proposals
        investment_column_proposals(self,choices,reserves)
        king_bridge_proposals(self,choices,self._king_bridge)
        if self.config.get('producer_counterstrike',False):
            producer_proposals(self,choices)
        if self.config.get('exchange_recovery', False):
            recovery_proposals(self,choices)
        self.frontier_proposals(choices, movable, reserves)
        if self.config.get('conservation_guard', False) or self.config.get('fog_memory', 0) or (self.config.get('contact_share', 0) and any(
                self.risk_dist.get(p, 999) <= 3 for p in self.enemies)):
            self.continuous_contact_supply(choices)
        # An unseen raid should not be the first moment when already-funded
        # insurance becomes eligible. Only the explicitly bounded ablation
        # enables this before contact, after the fragile expansion phase.
        insurance_limit = self.config.get('economic_recall_max_producers', 0)
        precontact = (self.config.get('precontact_insurance', False)
            and insurance_limit > 0 and self.config.get('economic_recall_rate', 0) > 0
            and not hasattr(self, '_opening_contact') and len(self.owned) > 8
            and sum(self.cells[p][2] for p in self.owned) > 12
            and sum(self.cells[p][0] in (KING, FORT) for p in self.owned) <= insurance_limit)
        if self.config.get('precontact_insurance', False):
            self.last_report['precontact_insurance'] = precontact
        regular_recall = (self.config.get('proactive_guard', False)
                or self.config.get('late_recall', False)
                and getattr(self, '_opening_contact', True) is False)
        if precontact or regular_recall:
            self.continuous_home_supply(choices, reserves, not regular_recall)
        repair_proposals(self, choices, reserves)
        if self.config.get('king_campaign', False):
            self.continuous_king(choices, movable)
        king_pressure_proposals(self, choices, movable)
        propose_stalled_contact(self, choices, movable)
        known_king = any(self.tick-model['seen'] <= self.KING_MAX_AGE
                         for model in self.kings.values())
        if (self.config.get('shared_supply', False) or getattr(self, '_economy_recovery', False)
                or self.config.get('king_collection', False) and known_king):
            self.continuous_supply(choices, movable, reserves)
        elif self.config.get('funded_production',False):
            self.continuous_supply(choices,movable,reserves,True)
        if self.last_report.get('producer_commitment_funded') is False:
            self._producer_commitment = None
            self._production_binding = None
        if self.config.get('patient_home_intercept', False):
            permitted = [p for p in choices if patient_intercept_allowed(self, tuple(p[1:4]))]
            self.last_report['patient_intercept_skipped'] = len(choices)-len(permitted)
            choices = permitted
        self.last_report['candidate_count'] = len(choices)
        if self.pending and not self.EVERY_STEP:
            self.last_report.update(mode='await_action', wait_reason='previous order unconfirmed')
            return self.finish(None)
        # A nearby producer changes the value of waiting: accumulated king
        # income can buy another income stream without a transport schedule.
        # Use local exchange search in that case; open frontiers keep the
        # economic proposal policy, which can spread without splitting a raid.
        local_producer = any(p in self.cells and self.cells[p][0] == FORT
                             and self.cells[p][1] != self.army
                             for p in self.neighbors[self.home])
        if self.config.get('opening_defense', False):
            local_producer = local_producer and getattr(self, '_opening_contact', False)
        if ((self.config.get('skirmish', False)
                or self.config.get('opening_skirmish', False)
                and getattr(self, '_opening_contact', False)
                or self.config.get('producer_skirmish', False) and local_producer)
                and sum(self.cells[p][0] in (KING, FORT) for p in self.owned) <= 3
                and any(self.risk_dist.get(p, 999) <= 4 for p in self.enemies)):
            tactical = (tactical_search(self, choices)
                        if self.config.get('tactical_depth2', False)
                        else skirmish_search(self, choices))
            if continuation_allowed(self, tactical):
                continued = tactical_search(self, choices, cushion=2, economic_probe=True)
                if continuation_funded(self, continued):
                    tactical = continued
                    self.last_report['close_duel_continuation'] = True
            if tactical:
                choices.append(tactical)
                if tactical[4]=='skirmish_wait':
                    recon_wait_proposals(self,choices,movable)
        else:
            opening_exchange_proposals(self, choices)
        king_idle_field_proposals(self,choices,movable)
        king_merge_proposals(self, choices, movable)
        rear_supply_proposals(self, choices, reserves)
        objectives.reconnaissance(self, choices, movable)
        search_column_proposals(self, choices, reserves)
        main_column_proposals(self, choices, reserves)
        from std_single_capital_fortress import propose as single_fortress_propose
        single_fortress_propose(self,choices,reserves)
        from std_nearby_capital import propose as propose_nearby_capital
        propose_nearby_capital(self,choices,reserves)
        from std_adjacent_threat_relief import propose as propose_relief_capital
        propose_relief_capital(self,choices,reserves)
        from std_adjacent_income import propose as adjacent_income_propose
        adjacent_income_propose(self,choices,reserves)
        from std_fortress_corridor import propose as fortress_corridor_propose
        fortress_corridor_propose(self,choices,reserves)
        from std_fort_assembly import propose as fort_assembly_proposals
        fort_assembly_proposals(self,choices,reserves)
        from std_guard_pool import propose as guard_pool_proposals
        guard_pool_proposals(self,choices)
        from std_fort_survey import propose as fort_survey_proposals
        fort_survey_proposals(self,choices,reserves)
        from std_home_watch import augment as home_augment
        home_augment(self,choices,reserves)
        if (self.config.get('safety_arbitration', False)
                or self.config.get('late_safety', False)
                and getattr(self, '_opening_contact', True) is False):
            # One command cannot both intercept a minor raid and reinforce a
            # king threatened from another edge. Arbitrate the resulting board,
            # rather than assigning every interception a higher fixed priority.
            def slack(choice):
                _, src, dst, amount, mode, target = choice
                held = self.cells[self.home][2]
                held += amount if dst == self.home else -amount if src == self.home else 0
                from std_adjacent_threat_relief import captured_target
                captured=captured_target(self,choice)
                incoming = max([0] + [max(0, self.cells[p][2]-1)
                    for p in self.enemies if p in self.neighbors[self.home] and p!=captured
                    and (self.config.get('simultaneous_guard', True) or p != dst)])
                return held-incoming
            safe = [p for p in choices if slack(p) >= 1 or p[4] == 'finish_king']
            if safe:
                choices = safe
            else:
                idle_slack = self.cells[self.home][2]-max([0]+[
                    max(0, self.cells[p][2]-1) for p in self.enemies
                    if p in self.neighbors[self.home]])
                best_slack = max([idle_slack]+[slack(p) for p in choices])
                choices = [p for p in choices if slack(p) == best_slack]
            self.last_report['safe_candidates'] = len(choices)
        if (self.config.get('deadline_safety', False)
                and getattr(self, '_opening_contact', True) is False
                and any(self.risk_dist.get(p,999) <= 5 and self.cells[p][2] >= 8
                        for p in self.enemies)):
            choices = deadline_arbitrate(self, choices, self.threat_curve(5))
        if self.config.get('stable_commitment', False):
            stable = []
            previous = getattr(self, '_committed_edge', None)
            objective = getattr(self, '_committed_target', None)
            for score, src, dst, amount, mode, target in choices:
                if mode not in ('defend', 'intercept') and score < 100000:
                    if previous == (dst, src):
                        score *= .35
                    if objective == target:
                        score *= 1.15
                stable.append((score, src, dst, amount, mode, target))
            choices = stable
        from std_reversal_recovery import filter_choices as recover_cycles
        from std_multi_front_truce import filter_choices as defer_multi_front_trades
        choices = defer_multi_front_trades(self,choices)
        from std_single_capital_fortress import filter_choices as single_fortress_filter
        choices = single_fortress_filter(self,choices)
        from std_nearby_retention import filter_choices as retain_nearby_capital
        choices = retain_nearby_capital(self,choices)
        from std_transport_path_guard import filter_choices as guard_transport_path
        choices = guard_transport_path(self,choices)
        choices = recover_cycles(self,choices)
        from std_neutral_funding import filter_choices as fund_neutral_capital
        choices = fund_neutral_capital(self,choices)
        if self.config.get('objective_priority', False):
            choices = objectives.prioritize(self, choices)
        if getattr(self,'map314',0):
            from std_map314_strategy import weight_border_forts
            choices = weight_border_forts(self,choices)
        from std_response_control import rerank as compare_joint_response
        choices = compare_joint_response(self,choices,enabled=True,evidence=True,plans=True)
        if self.pending:
            self.last_report.update(mode='await_action', wait_reason='previous order unconfirmed')
            return self.finish(None)
        for score, src, dst, amount, mode, target in sorted(choices, reverse=True):
            if mode in ('bank', 'skirmish_wait', 'security_wait', 'tactical_wait'):
                self.last_report.update(mode=mode, target=target, score=round(score, 3),
                                        wait_reason=('preserve a feasible king-defense schedule'
                                            if mode == 'security_wait' else
                                            'two-exchange public-board search selects waiting'
                                            if mode == 'tactical_wait' else
                                            'single-exchange public-board search selects waiting'
                                            if mode == 'skirmish_wait' else
                                            'save producer income for a funded fort capture'))
                return self.finish(None)
            move = self.action(src, dst, amount, mode, 're-evaluated executable proposal')
            if move:
                self.last_report.update(score=round(score, 3), target=target,
                                        reserve=reserves[src])
                from std_recall_goal import committed as commit_recall_goal
                commit_recall_goal(self,mode)
                from std_adjacent_threat_relief import committed as commit_relief_capital
                commit_relief_capital(self,src,dst,amount,mode,target)
                if self.config.get('consistent_dispatch_deadline', False):
                    from std_dispatch_deadline import committed as commit_dispatch_deadline
                    commit_dispatch_deadline(self, src, dst, amount, mode)
                objectives.committed(self, mode)
                commit_rear_supply(self,src,dst,amount,mode,target)
                from std_nearby_capital import committed as commit_nearby_capital
                commit_nearby_capital(self,src,dst,amount,mode,target)
                from std_adjacent_income import committed as adjacent_income_commit
                adjacent_income_commit(self,src,dst,amount,mode,target)
                commit_search_column(self,src,dst,amount,mode,target)
                commit_corridor(self,src,dst,amount,mode,target)
                self._committed_edge, self._committed_target = (src, dst), target
                commit_maneuver(self,src,dst,amount,mode,target)
                commit_producer(self,src,dst,amount,mode,target)
                from std_fort_survey import committed as commit_fort_survey
                commit_fort_survey(self,src,dst,amount,mode,target)
                from std_fort_assembly import committed as commit_assembly_bridge
                commit_assembly_bridge(self,src,dst,amount,mode,target)
                commit_convoy(self,src,dst,amount,mode)
                commit_colonize(self,src,dst,amount,mode)
                from std_post_capital_guard import committed as retain_capital_guard
                retain_capital_guard(self,src,dst,amount,mode,target)
                from std_investment_execution import committed as commit_investment_column
                commit_investment_column(self,src,dst,amount,mode,target)
                if self.config.get('frontier_confirmed_handoff', False):
                    from std_frontier_handoff import committed as commit_frontier_handoff
                    commit_frontier_handoff(self,src,dst,mode)
                return self.finish(move)
        self.last_report['wait_reason'] = 'no funded useful legal proposal'
        return self.finish(None)

    def owned_tree(self, src):
        if self.config.get('risk_routes', False):
            return self.risk_tree(src)
        key = ('owned_tree', src)
        if key in self.path_cache:
            return self.path_cache[key]
        topology = self.path_cache.get(('owned_topology',))
        if topology is None:
            signature = frozenset(p for p, cell in self.cells.items()
                                  if cell[1] == self.army)
            topology = getattr(self, '_owned_topology', None)
            if (topology is None or topology[0] != signature
                    or topology[1] is not self.neighbors):
                topology = signature, self.neighbors, {}
                self._owned_topology = topology
            self.path_cache[('owned_topology',)] = topology
        owned, _, trees = topology
        if src in trees:
            result = trees[src]
            self.path_cache[key] = result
            return result
        parent, distance = {src: None}, {src: 0}
        queue = deque([src])
        while queue:
            p = queue.popleft()
            for n in self.neighbors[p]:
                if n not in distance and n in owned:
                    parent[n], distance[n] = p, distance[p] + 1
                    queue.append(n)
        result = parent, distance
        # Only ownership and fixed neighbor order enter these trees. Bound
        # retained roots; signed balances and threats never persist here.
        if len(trees) >= 32:
            del trees[next(iter(trees))]
        trees[src] = result
        self.path_cache[key] = result
        return result

    def risk_tree(self, src):
        parent, distance, cost = {src: None}, {src: 0}, {src: 0.0}
        queue = [(0.0, src)]
        while queue:
            value, p = heappop(queue)
            if cost[p] != value:
                continue
            for n in self.neighbors[p]:
                if n not in self.cells or self.cells[n][1] != self.army:
                    continue
                missing = max(0, 1 - self.cells[n][2])
                danger = sum(max(0, self.cells[q][2] - 1) for q in self.neighbors[n]
                             if q in self.cells and self.cells[q][1] not in (0, self.army))
                new = value + 1 + .15 * min(danger, 40) + .25 * missing
                if new < cost.get(n, float('inf')):
                    cost[n], parent[n], distance[n] = new, p, distance[p] + 1
                    heappush(queue, (new, n))
        return parent, distance

    def continuous_defense(self, choices, movable):
        if self.config.get('deadline_defense', False):
            return self.deadline_defense(choices, movable)
        home_units = self.cells[self.home][2]
        need = max(self.home_keep, self.home_guard_hold())
        if need > home_units:
            parent, distance = self.owned_tree(self.home)
            eta = self.nearest_home_threat_eta(6)
            for src in self.owned:
                steps = distance.get(src, 999)
                amount = movable[src]
                if src != self.home and amount and steps <= max(1, eta):
                    choices.append((10000 + amount / float(steps), src, parent[src],
                                    amount, 'defend', self.home))
        for target in self.enemies:
            if self.risk_dist.get(target, 999) > 4:
                continue
            units = self.cells[target][2]
            for src in self.neighbors[target]:
                amount = movable.get(src, 0)
                if amount > units:
                    choices.append((5000 + units, src, target, amount, 'intercept', target))

    def deadline_defense(self, choices, movable):
        parent, distance = self.owned_tree(self.home)
        curve = self.threat_curve(12)
        home_units = self.cells[self.home][2]
        shortages = [(h, force-home_units-h//2) for h, force in enumerate(curve) if h and force > home_units+h//2]
        self.last_report['threat_curve'] = curve
        self.last_report['defense_shortages'] = shortages
        if (self.config.get('rescue_triage',False) and shortages
                and not self.config.get('deadline_convoy', False)):
            # Compare the currently funded stock before favoring a short
            # deadline forever. This optimistic sum ignores shared command
            # costs and road losses; it is not a feasible delivery schedule
            # or a proof about future growth, capture, or hidden opponents.
            # Joint rescue instead evaluates legal schedules against all
            # original deadlines, preserving immediately achievable cover.
            capacity = {h:sum(max(0,self.cells[p][2]-1) for p in self.owned
                if p != self.home and distance.get(p,999) <= h)
                for h,_ in shortages}
            funded = [h for h,need in shortages if capacity[h] >= need]
            horizon = min(funded) if funded else max(shortages,
                key=lambda item:(capacity[item[0]]/float(item[1]),-item[0]))[0]
            self.last_report['rescue_triage'] = dict(horizon=horizon,
                current_stock=capacity,fully_funded_stock=bool(funded),
                model='optimistic current donor stock; not a delivery certificate')
            shortages = [(h,need) for h,need in shortages if h >= horizon]
        joint_rescue = None
        if self.config.get('deadline_convoy', False) and shortages:
            # Keep the inherited donor policy when one current packet can
            # already pay the earliest gap. Joint collection is an increment
            # for split stock; a distant unfunded forecast must not displace
            # a sufficient cheap local rescue (observed 514 regression).
            first_h, first_need = shortages[0]
            single_funded = False
            for source in self.owned:
                if source == self.home or distance.get(source,999) > first_h:
                    continue
                route = self.path(parent,source)
                payload = self.cells[source][2]-1-sum(self.cells[p][2] == 0 for p in route[1:-1])
                if payload >= first_need:
                    single_funded = True
                    break
            self.last_report['deadline_convoy_scope'] = dict(single_funded=single_funded,
                deadline=first_h,shortage=first_need)
            if not single_funded:
                from std_deadline_convoy import proposal as deadline_convoy_proposal
                joint_rescue = deadline_convoy_proposal(self, curve, shortages)
                if joint_rescue:
                    choices.append(joint_rescue)
        for h, shortage in (() if joint_rescue else shortages):
            if self.config.get('defense_cover', False):
                donors = []
                for src in self.owned:
                    steps = distance.get(src, 999)
                    if src == self.home or steps > h:
                        continue
                    amount = max(0, self.cells[src][2]-1)
                    route = list(reversed(self.path(parent, src)))
                    payload = amount-sum(self.cells[p][2] == 0 for p in route[1:-1])
                    if payload > 0:
                        donors.append((src, steps, amount, payload))
                selected, force, cost = select_cover([(d[1], d[3]) for d in donors], h, shortage)
                if selected:
                    src, steps, amount, payload = max((donors[i] for i in selected),
                        key=lambda d: (d[3]/float(d[1]), -d[1], d[0]))
                    base = 12000 if self.config.get('stable_commitment', False) and h <= 6 else 10000
                    score = base+1000.0/(h+1)+min(shortage, force)/float(max(1, cost))
                    choices.append((score, src, parent[src], amount, 'defend', self.home))
                    self.last_report.setdefault('defense_cover', []).append(
                        dict(deadline=h, shortage=shortage, delivered=force,
                             commands=cost, donors=len(selected), source=src))
                continue
            for src in self.owned:
                steps = distance.get(src, 999)
                amount = max(0, self.cells[src][2] - 1)
                if src == self.home or not amount or steps > h:
                    continue
                delivered = min(shortage, amount)
                base = 12000 if self.config.get('stable_commitment', False) and h <= 6 else 10000
                score = base + 1000.0/(h+1) + delivered/float(steps)
                choices.append((score, src, parent[src], amount, 'defend', self.home))
        for target in self.enemies:
            eta = self.risk_dist.get(target, 999)
            if eta > 6:
                continue
            units = self.cells[target][2]
            if self.config.get('proactive_guard', False) and units < max(4, home_units*.12):
                continue
            for src in self.neighbors[target]:
                amount = (max(0, self.cells[src][2]-1) if src in self.cells
                          and self.cells[src][1] == self.army else 0)
                if (src != self.home and (self.config.get('producer_reserve',False)
                        or self.config.get('response_pool', False) and eta > 1)):
                    amount = movable.get(src, 0)
                if amount <= units:
                    continue
                if src == self.home:
                    if self.config.get('hold_home', False):
                        continue
                    other = max([0] + [self.cells[p][2]-1 for p in self.enemies
                        if p != target and self.risk_dist.get(p, 999) <= 1])
                    sent = units+1
                    if (self.config.get('conservation_guard', False)
                            and self.cells[src][2]-sent < self._conservation_keep-units):
                        continue
                    if self.config.get('surplus_intercept', False):
                        sent = max(sent, self.cells[src][2]-self.home_keep)
                    if (self.config.get('base_guard', 2) > 2
                            and self.cells[src][2]-sent < self.config['base_guard']):
                        continue
                    if self.config.get('fog_memory', 0) and self.cells[src][2]-sent < self._fog_guard:
                        continue
                    if self.cells[src][2]-sent <= other:
                        continue
                    late_guard = (self.config.get('late_guard', False)
                                  and getattr(self, '_opening_contact', True) is False)
                    if self.config.get('intercept_safety', False) or late_guard:
                        # Price the surviving mobile armies and producer
                        # growth. Immobile plain claims alone must not renew
                        # the opening uncertainty after this funded removal.
                        remaining = self.threat_curve(6, exclude=(target,), zero_uncertainty=False)
                        keep = max([2] + [force-(h-1)//2
                            for h, force in enumerate(remaining) if h])
                        if self.config.get('post_intercept_guard', False) or late_guard:
                            # Capturing the target loses its defenders, not the
                            # entire dispatch. Preserve a share of the surviving
                            # army, after removing that target from the threat.
                            after = sum(self.cells[p][2] for p in self.owned)-units
                            share = self.config.get('post_intercept_share', self.config.get('guard_share', 18))
                            keep = max(keep, int(ceil(after*share/100.0)))
                        if self.cells[src][2]-sent < keep:
                            continue
                    if (self.config.get('disciplined_intercept', False)
                            and self.cells[src][2]-sent < self.home_keep
                            and units < max(self.config.get('intercept_floor', 4), home_units*.35)):
                        relief_keep = opening_interception_keep(self,target,sent)
                        if self.config.get('king_intrusion_counter',False):
                            residual = self.threat_curve(6,exclude=(target,),zero_uncertainty=False)
                            relief_keep = max([1]+[max(0,force-(h-1)//2)
                                for h,force in enumerate(residual) if h])
                            self.last_report.setdefault('king_intrusion_counter',[]).append(
                                dict(target=target,sent=sent,residual_keep=relief_keep))
                        if relief_keep is None or self.cells[src][2]-sent < relief_keep:
                            continue
                        self.last_report.setdefault('opening_interception_relief',[]).append(
                            dict(target=target,sent=sent,residual_keep=relief_keep))
                else:
                    sent = amount
                    if (self.config.get('fort_packets',False)
                            and self.cells[src][0] == FORT):
                        # Removing a one-soldier raid must not automatically
                        # empty a productive fort. Fund the destination's
                        # visible counter, while retaining the source surplus.
                        sent = min(sent,units+1+self.counter(target))
                base = 13000 if eta == 1 else 500 if self.config.get('stable_commitment', False) else 11000
                if units < self.config.get('urgent_intercept_floor', 0):
                    base = 80 if self.config.get('economic_intercept', False) else 500
                choices.append((base + units/float(eta+1), src, target, sent, 'intercept', target))

    def frontier_proposals(self, choices, movable, reserves):
        """Select exactly one frontier provider; all orders use the scheduler.

        Existing configurations retain reviewed opening/recon semantics. The
        unified research mode is explicit and validates its supported options.
        A handled legacy callback never appends a second frontier family.
        """
        area_steps = self.config.get('safe_opening_area_steps', 0)
        area_opening = bool(area_steps and self.calls <= area_steps and not self.kings
            and not any(cell[1] > 0 and cell[1] != self.army for cell in self.memory.values()))
        if self.config.get('opening_area_after_fort', False):
            # Actual legal fort discovery completes scouting's production goal.
            # Before discovery, retain the existing mixed frontier scorer.
            area_opening = area_opening and any(cell[0] == FORT for cell in self.memory.values())
        if area_opening:
            # This is the same reviewed provider, selected exclusively. A
            # legally observed enemy (including a remembered fog contact)
            # restores the original multi-purpose scorer immediately.
            if not maneuver_proposals(self, choices, reserves, opening_override=True):
                self.continuous_frontier(choices, movable,
                                         mobilize=self.config.get('mobilize', False))
        elif self.config.get('unified_frontier', False):
            self.continuous_frontier(choices, movable,
                                     mobilize=self.config.get('mobilize', False))
        elif not maneuver_proposals(self, choices, reserves):
            self.continuous_frontier(choices, movable, mobilize=False)

    def continuous_frontier(self, choices, movable, mobilize=False):
        self._search_reveal_active = search_reveal_active(self)
        self.last_report['search_reveal_value'] = self._search_reveal_active
        first_frontier = len(choices)
        # Bind observation-wide policy options outside the route loop.
        plain_scout_relief = self.config.get('plain_scout_relief', False)
        transport_min = self.config.get('transport_min', 1)
        lookahead = self.config.get('lookahead', False)
        fort_bank = self.config.get('fort_bank', False)
        bank_discount = self.config.get('bank_discount', 2)
        funded_only = self.config.get('funded_only', False)
        king_collection = self.config.get('king_collection', False)
        efficient_capture = self.config.get('efficient_capture', False)
        capture_packet = self.config.get('capture_packet', 1)
        frontier_route_home_cost = self.config.get('frontier_route_home_cost', False)
        home_route_packets = self.config.get('home_route_packets', False)
        home_route_tail = self.config.get('home_route_tail', False)
        mid_field_packets = self.config.get('mid_field_packets', False)
        large_field_columns = (self.config.get('large_field_columns', False)
                               and getattr(self, '_advantage', False))
        packet_budget = self.config.get('packet_budget', False)
        frontier_mobile_packet = self.config.get('frontier_mobile_packet', False)
        frontier_road_guard = self.config.get('frontier_road_guard', False)
        search_contact_safety = self.config.get('search_contact_safety', False)
        frontier_ready_suffix_value = self.config.get('frontier_ready_suffix_value', False)
        scout_relief_indices = set()
        route_metadata = {}
        self._maneuver_candidates = {}
        search_suffix = (self.config.get('search_ready_suffix', False)
            and self.calls > 100 and not any(self.tick-model['seen'] <= self.KING_MAX_AGE
                for model in self.kings.values()))
        ready_paths = {} if frontier_ready_suffix_value or search_suffix else None
        targets = {n for p in self.owned for n in self.neighbors[p]
                   if n in self.cells and self.cells[n][1] != self.army and self.cells[n][0] not in BLOCKED}
        target_values = {target: frontier_target_value(self, target) for target in targets}
        counter_margin = self.config.get('counter_margin', 100)
        target_margins = {target: int(ceil(self.counter(target)*counter_margin/100.0))
                          for target in targets}
        sorted_targets = sorted(targets)
        recover_routes = (self.config.get('frontier_funded_shortest_paths', False)
                          and not self.config.get('risk_routes', False))
        field_forts_only = self.config.get('frontier_funded_field_forts_only', False)
        information = self.config.get('information', False)
        focus = self._information_focus if information else None
        focus_distances = {target: hex_distance(target, focus) for target in targets} if focus else {}
        # Retain a local budget for a developed nearby approach. A lone
        # immobile claim alone cannot justify delaying the first income source.
        contested_fort_budget = False
        if self.config.get('contested_fort_budget', False):
            # observe() already counted this board; standalone proposal callers
            # may omit that phase, so compute only when its result is absent.
            producers = self.last_report.get('objective_state', {}).get('owned_producers')
            if producers is None:
                producers = sum(self.cells[p][0] in (KING, FORT) for p in self.owned)
            if producers == 1:
                nearby = [p for p in self.enemies if self.risk_dist.get(p, 999) <= 6]
                contested_fort_budget = (len(nearby) >= 2
                    or any(self.cells[p][2] > 1 for p in nearby))
        sources = sorted(self.owned, key=lambda p: (movable[p], p), reverse=True)[
            :self.config.get('frontier_sources',8)]
        if self.home not in sources:
            sources.append(self.home)
        if self.config.get('frontier_mixed_sources', False):
            from std_frontier_sources import select as select_frontier_sources
            sources, coverage = select_frontier_sources(self, movable, targets)
            self.last_report['frontier_source_coverage'] = coverage
        extra_targets = {}
        handoffs = []
        if self.config.get('frontier_confirmed_handoff', False):
            from std_frontier_handoff import targets as handoff_targets
            handoffs = handoff_targets(self, movable, targets)
        if self.config.get('frontier_direct_supplement', False):
            from std_frontier_sources import direct_supplement
            occupied = [handoffs[0][0]] if handoffs and handoffs[0][0] not in sources else []
            extra_targets, coverage = direct_supplement(self, movable, targets,
                sources+occupied, limit=2-len(occupied))
            self.last_report['frontier_direct_supplement'] = coverage
            sources.extend(sorted(extra_targets))
        planner, signed = None, None
        if mobilize and self.config.get('frontier_signed_ledger', False):
            from std_maneuver import RoadPlanner
            planner = RoadPlanner(self,getattr(self,'_active_reserves',{}))
            signed = planner.field_spares()
        routes = [(src, None, None) for src in sources]
        routes.extend((src,target,None) for src,target in handoffs)
        if mobilize and not self.kings:
            from std_maneuver import RoadPlanner, safe_plan
            planner = planner or RoadPlanner(self,getattr(self,'_active_reserves',{}))
            plans = planner.field_plans(opening=False)
            task = getattr(self,'_maneuver',None)
            continuation = None
            if task and task['phase'] == 'ready':
                continuation = safe_plan(planner,dict(path=tuple(task['path'])))
                if continuation:
                    plans.append(continuation)
                else:
                    self._maneuver = None
            accepted = []
            for raw in plans:
                plan = safe_plan(planner,raw)
                if plan:
                    plan.update(opening=False,recon=False,
                        continuing=bool(continuation and plan['path']==continuation['path']))
                    accepted.append(plan)
                    routes.append((plan['path'][0],plan['target'],plan))
            self.last_report['maneuver'] = dict(plans=len(accepted),
                integration='routes_in_existing_frontier_scorer',opening=False,
                confirmed_fort=any(c[0]==FORT for c in self.memory.values()))
        for src, continuation_target, road_plan in routes:
            source_have = road_plan['send'] if road_plan else movable[src]
            if source_have < 1:
                continue
            source_distance = hex_distance(src, focus) if focus else 0
            road_paths = {}
            road_balances = {}
            if road_plan is not None:
                parent, distance = {}, {}
                source_targets = [road_plan['target']]
            elif continuation_target is not None:
                parent, distance = {src: None}, {src: 0}
                source_targets = [continuation_target]
            elif src in extra_targets:
                parent, distance = {src: None}, {src: 0}
                source_targets = [extra_targets[src]]
            else:
                parent, distance = self.owned_tree(src)
                source_targets = sorted_targets
            funded_tree = None
            for target in source_targets:
                # A target-local budget must never reduce the next target.
                have = source_have
                kind, owner, units = self.cells[target]
                # Scope only the newly recovered alternatives. Existing paid
                # routes and every original proposal family remain unchanged.
                recover_route = (recover_routes and (not field_forts_only
                    or kind == FORT and owner == 0 and src != self.home))
                if road_plan is not None:
                    approaches = ()
                    path = list(road_plan['path'])
                else:
                    approaches = [p for p in self.neighbors[target] if p in distance]
                    if not approaches:
                        continue
                    road = min(approaches, key=lambda p: (distance[p], p))
                    if road not in road_paths:
                        road_paths[road] = self.path(parent, road)
                    path = road_paths[road] + [target]
                steps = len(path) - 1
                scout_relief = False
                if steps > 18:
                    continue
                if signed is not None and road_plan is None:
                    # A captured enemy no longer attacks the departing source.
                    # Other visible source threats and all signed road holds
                    # still apply, including a nonempty producer's deficit.
                    have = (planner.field_spare(src, excluded=(target,))
                            if steps == 1 else signed.get(src, 0))
                    if have < 1 and plain_scout_relief:
                        from std_frontier_sources import plain_scout_packet
                        have = plain_scout_packet(self, src, target, steps,
                                                  getattr(self, '_active_reserves', {}))
                        if have:
                            scout_relief = True
                            self.last_report.setdefault('plain_scout_relief', []).append(
                                dict(source=src, target=target, packet=have))
                    if have < 1:
                        continue
                if steps > 1 and have < transport_min and kind != KING:
                    continue
                if road_plan is not None:
                    # The borrowed route pays signed holds at every pickup.
                    # Its safe-plan check already funded all ordered prefixes.
                    power = road_plan['arrival']
                    prefix_min = 1
                else:
                    if road not in road_balances:
                        net, minimum = 0, 0
                        for p in path[1:-1]:
                            gain = signed.get(p, 0) if signed is not None else movable[p]
                            # Signed holds charge every deficit before later
                            # pickups; the inherited ledger charges empty roads.
                            if signed is None and self.cells[p][2] == 0:
                                gain = -1
                            net += gain
                            minimum = min(minimum, net)
                        # Multiple endpoints share this exact owned-road path.
                        # Cache its signed balance only within this source and
                        # observation; target-specific departure stays separate.
                        road_balances[road] = net, minimum
                    net, minimum = road_balances[road]
                    power, prefix_min = have+net, have+minimum
                if prefix_min < 1 and not recover_route:
                    continue
                defending = units + (int(ceil(steps * .5)) if owner > 0 and kind in (KING, FORT) else 0)
                margin = target_margins[target]
                required = defending + max(1, margin + 1)
                if kind == FORT and owner == 0:
                    required = max(required, defending+objectives.neutral_fort_tail(self, target))
                if (recover_route and steps > 1 and kind not in (KING, MARSH)
                        and (prefix_min < 1 or power < required)):
                    if funded_tree is None:
                        from std_frontier_paths import funded_shortest_tree
                        funded_tree = funded_shortest_tree(self.neighbors, self.cells,
                            self.army, signed if signed is not None else movable, src, distance,
                            blocked=(self.home,) if field_forts_only else (), signed=signed is not None)
                    funded_parent, funded_power = funded_tree
                    ready = [(funded_power[p], p) for p in approaches
                        if distance[p]+1 == steps and funded_power.get(p, 0) >= required]
                    if ready:
                        _, funded_road = max(ready)
                        path = self.path(funded_parent, funded_road)+[target]
                        power, prefix_min = have, have
                        for point in path[1:-1]:
                            power += (signed.get(point, 0) if signed is not None else
                                      -1 if self.cells[point][2] == 0 else movable[point])
                            prefix_min = min(prefix_min, power)
                        self.last_report['frontier_funded_path_recovered'] = (
                            self.last_report.get('frontier_funded_path_recovered', 0)+1)
                if prefix_min < 1:
                    continue
                if (contested_fort_budget and kind == FORT and owner == 0
                        and units >= 12 and steps >= 3 and self.home in path[:-1]):
                    have, power, prefix_min, _ = fort_expedition(self, path, have,
                        signed if signed is not None else movable, signed=signed is not None)
                    if prefix_min < 1 or power < required:
                        self.last_report['fort_expedition_deferred'] = (
                            self.last_report.get('fort_expedition_deferred', 0)+1)
                        continue
                value = target_values[target]
                if focus:
                    progress = source_distance-focus_distances[target]
                    value += 14 * progress
                    value += 160.0/(focus_distances[target]+1)
                if lookahead and kind == BLANK and owner == 0:
                    value += 22 * self.continuation(target, power-defending)
                if kind == KING and owner > 0:
                    value = 1000000
                if power < required:
                    if (fort_bank and kind == FORT
                            and self.cells[src][0] in (KING, FORT) and steps <= 4):
                        wait = int(ceil((required-power)/.4))
                        if wait <= 140:
                            bank = value/float(steps+1+wait*bank_discount/100.0)
                            choices.append((bank, src, src, 0, 'bank', target))
                    if (funded_only or getattr(self, '_economy_recovery', False)
                            or king_collection and kind == KING):
                        continue
                    if kind not in (FORT, KING) or steps < 2:
                        continue
                    score = value * .35 / float(steps + sqrt(required - power) + 1)
                    mode = 'supply'
                else:
                    score = (value - defending * .15) / float(steps)
                    mode = 'capture' if steps == 1 else 'advance'
                sent = have
                if efficient_capture:
                    if steps == 1 and kind != KING:
                        sent = min(have, max(required, capture_packet))
                    # A transport is only a fraction of its eventual payoff.
                    # Rewarding the entire stack on every friendly edge made
                    # three-edge loops outscore the capture they were funding.
                    score += sqrt(have)*4 / float(steps)
                    if (kind != KING and (src == self.home
                            or frontier_route_home_cost
                            and self.home in path[:-1])):
                        score -= 20
                if (home_route_packets
                        and src == self.home and steps > 1
                        and kind == BLANK and owner == 0 and power >= required):
                    packet = minimum_dispatch(self,path,required,signed if signed is not None else movable,
                                              signed=signed is not None)
                    if packet is None:
                        continue
                    if home_route_tail:
                        packet = dispatch_with_tail(self,path,required,signed if signed is not None else movable,
                                                    signed=signed is not None)
                    sent = packet
                if ((mid_field_packets or large_field_columns and have >= 64)
                        and getattr(self,'_opening_contact',True) is False
                        and steps == 1 and kind == BLANK
                        and self.cells[src][0] == BLANK):
                    # Continue an existing large field army after contact.
                    # The selective mode needs an observed advantage and at
                    # least 64 currently available troops. Small groups and
                    # producers keep efficient claims; road holds still apply.
                    sent = have
                if (packet_budget and steps == 1
                        and kind == BLANK and owner == 0 and self.cells[src][0] in (KING, FORT)):
                    sent = min(have, max(required + 1, 8))
                if (continuation_target is None and src in extra_targets and kind == BLANK
                        and frontier_mobile_packet):
                    # Only the supplementary direct move pays one additional
                    # current soldier. The baseline light claims remain intact.
                    # The selector already funds this tail; no future income.
                    sent = max(sent, required+1)
                if (frontier_road_guard
                        and steps > 1 and kind != KING
                        and self.cells[path[1]][0] == BLANK
                        and self.cells[path[1]][1] == self.army
                        and self.cells[path[1]][2] + sent <= self.counter(path[1])):
                    # Only the dispatched packet has arrived on the first road.
                    # Later route pickups cannot pay its current local margin.
                    self.last_report['frontier_road_guard_rejected'] = (
                        self.last_report.get('frontier_road_guard_rejected', 0)+1)
                    continue
                if road_plan is not None:
                    # The shared scorer can alter a direct capture's packet;
                    # only exact transport bytes may carry a future route.
                    if steps > 1 and sent == road_plan['send']:
                        route_metadata[len(choices)] = dict(road_plan)
                if ready_paths is not None and mode in ('advance', 'capture'):
                    # A feeder into the king also retains home-front stock.
                    # Optional cost repricing must not discount that military
                    # rally solely because a king sortie can pay a route.
                    home_military = (search_contact_safety
                        and not frontier_ready_suffix_value
                        and path[1] == self.home and not (kind == FORT and owner == 0))
                    if not home_military:
                        ready_paths[len(choices)] = tuple(path)
                if scout_relief:
                    scout_relief_indices.add(len(choices))
                choices.append((score, src, path[1], sent, mode, target))
        if ready_paths:
            from std_frontier_value import reprice_ready_suffixes
            changed = reprice_ready_suffixes(choices, ready_paths, self.cells, self.army)
            self.last_report['frontier_ready_suffix_repriced'] = changed
        # One frontier family and one winner per executable order. The route
        # metadata follows the final shared score, including suffix repricing.
        allow_relief = True
        if scout_relief_indices:
            from std_frontier_sources import scout_relief_is_fallback
            allow_relief = scout_relief_is_fallback(choices, first_frontier, scout_relief_indices)
            self.last_report['plain_scout_fallback'] = dict(allowed=allow_relief,
                extra_candidates=len(scout_relief_indices))
        winners, command_order = {}, []
        for index in range(first_frontier,len(choices)):
            if index in scout_relief_indices and not allow_relief:
                continue
            choice = choices[index]
            key = choice[1:]
            prior = winners.get(key)
            if prior is None:
                command_order.append(key)
            if prior is None or choice[0] > prior[0][0]:
                winners[key] = choice,index
        # Index the exact same prefix predicate once. Repeated scans used
        # quadratic time when a late board generated thousands of proposals.
        prefix_scores = {}
        for prior in choices[:first_frontier]:
            key = prior[1:]
            if key not in prefix_scores or prior[0] > prefix_scores[key]:
                prefix_scores[key] = prior[0]
        for key in command_order:
            choice,index = winners[key]
            if (index in route_metadata
                    and (key not in prefix_scores or prefix_scores[key] < choice[0])):
                self._maneuver_candidates[key] = dict(route_metadata[index],proposal_score=choice[0])
        choices[first_frontier:] = [winners[key][0] for key in command_order]

    def continuous_supply(self, choices, movable, reserves, production_only=False):
        targets = {n for p in self.owned for n in self.neighbors[p]
                   if n in self.cells and self.cells[n][1] != self.army
                   and self.cells[n][0] not in BLOCKED
                   and (self.cells[n][0] in (KING, FORT) or self.cells[n][1] > 0)}
        ranked = sorted(targets, key=lambda p: (self.cells[p][0] == KING,
                        self.cells[p][0] == FORT, -self.cells[p][2], p), reverse=True)[:12]
        if production_only:
            ranked = [p for p in ranked if self.cells[p][0] == FORT]
        plans = 0
        proposed = []
        if not hasattr(self,'_funded_producer_roots'):
            self._funded_producer_roots = {}
        for target in ranked:
            kind, owner, units = self.cells[target]
            roads = [p for p in self.neighbors[target] if p in movable]
            if not roads:
                continue
            root_limit = min(6,max(1,self.config.get('production_roots',1))) if production_only else 1
            roots = sorted(roads,key=lambda p:(movable[p],p),reverse=True)[:root_limit]
            binding = getattr(self,'_production_binding',None) if kind == FORT else None
            if binding and binding['target'] == target and binding['root'] in roads:
                roots = [binding['root']]
            for root in roots:
                required = units + self.counter(target) + 2
                if movable[root] >= required:
                    continue
                gap = required-movable[root]
                budget = min(12,self.config.get('production_budget',6)) if production_only else 6
                for force, cost, moves in merge_schedule(self.neighbors, self.cells,
                        self.army, root, reserves, budget):
                    if not moves:
                        continue
                    growth = (cost+2)//2 if owner > 0 else 0
                    fully_funded = movable[root]+force >= required+growth
                    first_fort = (kind == FORT and self.config.get('first_fort_funded',False)
                        and getattr(self,'_opening_contact',True) is False
                        and sum(self.cells[p][0] in (KING,FORT) for p in self.owned) == 1)
                    if first_fort and not fully_funded:
                        self.last_report['unfunded_first_fort_plans'] = (
                            self.last_report.get('unfunded_first_fort_plans',0)+1)
                        continue
                    if production_only:
                        if not fully_funded:
                            continue
                    if not collection_departure_allowed(self, target, root, moves, reserves, fully_funded):
                        continue
                    src, dst, amount = moves[0]
                    value = 1000 if kind == KING else self.config.get('production_value', 240)*1.33 if kind == FORT else 180
                    if production_only:
                        value = self.config.get('production_value',240)*(1.3 if owner > 0 else 1)
                    funded = min(1.0, force/float(gap))
                    score = value * funded / (cost+1.0) + sqrt(force)
                    if src == self.home:
                        score *= .7
                    if (production_only and self.config.get('first_producer_priority',False)
                            and getattr(self,'_opening_contact',True) is False
                            and sum(self.cells[p][0] in (KING,FORT) for p in self.owned) == 1
                            and not any(h <= 6 for h,_ in self.last_report.get('defense_shortages',[]))):
                        # The full current-stock schedule already exists. A
                        # bounded economic priority lets that first income
                        # source compete with repeated cheap land captures.
                        # This is a stage heuristic, not discounted-profit
                        # accounting or permission to borrow future troops.
                        before=score
                        score=max(score,value/3.0+sqrt(force))
                        self.last_report.setdefault('first_producer_priorities',[]).append(
                            dict(target=target,commands=cost,score_before=before,score=score))
                    proposal = (score, src, dst, amount, 'merge', target)
                    if kind == FORT and owner == 0 and not fully_funded:
                        self._unfunded_neutral_collections.add(proposal[1:])
                    proposed.append(proposal)
                    if kind == FORT and fully_funded:
                        self._funded_producer_roots[(src,dst,amount,target)] = root
                    plans += 1
        choices.extend(retain_funded(self,proposed))
        self.last_report['merge_plans'] = plans

    def update_economic_progress(self):
        owned = set(self.owned)
        producers = sum(self.cells[p][0] in (KING, FORT) for p in owned)
        previous = getattr(self, '_progress_owned', set())
        seen = len(self.memory)
        if owned-previous or seen > getattr(self, '_progress_seen', 0):
            self._last_economic_progress = self.tick
        self._progress_owned, self._progress_seen = owned, seen
        stalled = self.tick-getattr(self, '_last_economic_progress', self.tick)
        if getattr(self, '_economy_recovery', False):
            if producers > self._recovery_producers:
                self._economy_recovery = False
                self._last_economic_progress = self.tick
        elif stalled >= self.config.get('stagnation_window', 32):
            self._economy_recovery = True
            self._recovery_producers = producers
        self.last_report['economy_recovery'] = dict(
            active=getattr(self, '_economy_recovery', False), stalled_steps=stalled,
            producers=producers, goal='fund one more producer; recheck all tactical domains')

    def continuous_home_supply(self, choices, reserves, economic_only=False):
        target = self.home_keep
        from std_recall_goal import target as economic_recall_target
        economic_deficit = economic_recall_target(self, target)-self.cells[self.home][2]
        rate = self.config.get('economic_recall_rate', 0)
        producer_limit = self.config.get('economic_recall_max_producers', 0)
        if producer_limit and sum(self.cells[p][0] in (KING, FORT)
                                  for p in self.owned) > producer_limit:
            rate = 0
        # A funded minimum-guard delivery must not lose to a larger,
        # slower economic donor while home is below its existing floor.
        # Precontact economic-only calls have no regular-guard fallback.
        floor_first = (self.config.get('recall_floor_first', False)
            and not economic_only
            and self.cells[self.home][2] < min(target, self.config.get('recall_cap', 0)))
        if floor_first:
            self.last_report['recall_floor_first'] = dict(
                held=self.cells[self.home][2],
                target=min(target, self.config.get('recall_cap', 0)))
        if rate and economic_deficit > 0 and not floor_first:
            parent, distance = self.owned_tree(self.home)
            for src in self.owned:
                steps = distance.get(src, 999)
                if src == self.home or steps > 6:
                    continue
                keep = max(1, reserves[src], self.counter(src)+1)
                amount = max(0, self.cells[src][2]-keep)
                route = self.path(parent, src)
                road_cost = sum(self.cells[p][2] == 0 for p in route[1:-1])
                payload = amount-road_cost
                useful = min(economic_deficit, payload)
                if useful < rate*steps:
                    continue
                # Follow a funded donor, not the first tiny branch of a larger
                # merge tree. Re-evaluation increases this donor's throughput
                # as it approaches home, while timed defense can interrupt.
                sent = min(amount, economic_deficit+road_cost)
                choices.append((180+useful/float(steps), src, parent[src], sent,
                                'economic_recall', self.home))
                self.last_report['economic_recall_candidates'] = (
                    self.last_report.get('economic_recall_candidates', 0)+1)
        if economic_only:
            return
        cap = self.config.get('recall_cap', 0)
        if cap:
            # Economic insurance has a bounded command cost. Visible timed
            # attacks retain the independent deadline-defense priority.
            target = min(target, cap)
        deficit = target-self.cells[self.home][2]
        self.last_report['recall_target'] = target
        if deficit <= 0:
            return
        safe = {p: max(keep, self.counter(p)+1) for p, keep in reserves.items()}
        plans = merge_schedule(self.neighbors, self.cells, self.army, self.home, safe, 6)
        self.last_report['guard_delivery_plans'] = len(plans)
        for force, commands, moves in plans:
            if not moves:
                continue
            src, dst, amount = moves[0]
            delivered = min(deficit, force)
            score = 180 + delivered/float(commands)
            choices.append((score, src, dst, amount, 'guard_supply', self.home))

    def protect_response_pool(self, reserves):
        """Protect a funded nearby response instead of transporting every gap.

        The independent-path budget is conservative about shared routes. The
        protected force may serve timed defense/interception, but economic
        frontier actions cannot consume it as an unreserved path pickup.
        """
        target = int(ceil(sum(self.cells[p][2] for p in self.owned)
                          *self.config.get('guard_share', 18)/100.0))
        need = max(0, target-self.cells[self.home][2])
        budget = self.config.get('response_budget', 3)
        parent, distance = self.owned_tree(self.home)
        donors = []
        for src in self.owned:
            steps = distance.get(src, 999)
            if src == self.home or steps > budget:
                continue
            keep = max(reserves[src], self.counter(src)+1)
            amount = max(0, self.cells[src][2]-keep)
            route = self.path(parent, src)
            cost = sum(self.cells[p][2] == 0 for p in route[1:-1])
            if amount > cost:
                donors.append((src, steps, amount-cost, keep, cost))
        selected, force, commands = select_cover([(d[1], d[2]) for d in donors], budget, need) if need else ((), 0, 0)
        remaining, protected = need, []
        for i in sorted(selected, key=lambda j: (-donors[j][2]/float(donors[j][1]), donors[j][0])):
            src, steps, payload, keep, cost = donors[i]
            amount = min(remaining, payload)
            if amount <= 0:
                break
            reserves[src] = keep+amount+cost
            remaining -= amount
            protected.append(dict(source=src, keep=reserves[src], payload=amount, commands=steps))
        self.last_report['response_pool'] = dict(target=target, shortage=need,
            funded=need-remaining, commands=commands, donors=protected)

    def continuous_contact_supply(self, choices):
        deficit = self.home_keep-self.cells[self.home][2]
        if deficit <= 0:
            return
        parent, distance = self.owned_tree(self.home)
        for src in self.owned:
            steps = distance.get(src, 999)
            amount = self.cells[src][2]-1
            if src != self.home and amount > 0 and steps <= 6:
                score = 350 + min(deficit, amount)/float(steps)
                choices.append((score, src, parent[src], amount, 'defend', self.home))

    def continuation(self, start, force):
        key = start, min(5, force)
        if key in self._continuation_cache:
            return self._continuation_cache[key]
        best = 0
        stack = [(start, min(5, force), frozenset([start]), 0)]
        while stack:
            p, amount, seen, count = stack.pop()
            best = max(best, count)
            if count >= 3 or amount <= 1:
                continue
            for n in self.neighbors[p]:
                if n in seen or n not in self.cells:
                    continue
                kind, owner, units = self.cells[n]
                if kind == BLANK and owner == 0 and amount-1 > units:
                    stack.append((n, amount-1-units, seen | {n}, count+1))
        self._continuation_cache[key] = best
        return best

    def information_focus(self):
        if not self.config.get('information', False):
            return None
        if self.kings:
            return min((m['pos'] for m in self.kings.values()),
                       key=lambda p: hex_distance(self.home, p))
        if self.config.get('contact_focus', False) and self.enemies:
            nearest = min(self.enemies, key=lambda p: (self.risk_dist.get(p, 999), p))
            if self.risk_dist.get(nearest, 999) <= 6:
                return nearest
        enemy = [p for p, d in self.search_memory().items() if d[1] > 0
                 and d[1] != self.army and d[1] not in self.eliminated
                 and (first_contact_search_active(self) or self.tick-d[3] < 100)]
        if self.hill_hints:
            def value(p):
                near = min((hex_distance(p, q) for q in enemy), default=24)
                # Search from observed enemy territory, otherwise spread the
                # prior over distant public silhouettes. No hidden coordinates.
                return (100.0/(near+1) if enemy else 0) + hex_distance(self.home, p)*.6
            return max(sorted(self.hill_hints), key=value)
        return min(enemy, key=lambda p: hex_distance(self.home, p)) if enemy else None

    def continuous_king(self, choices, movable):
        sources = sorted(self.owned, key=lambda p: (movable[p], p), reverse=True)[:8]
        considered, funded = 0, 0
        for model in self.kings.values():
            target = model['pos']
            if self.tick-model['seen'] > self.KING_MAX_AGE:
                continue
            for src in sources:
                if movable[src] < 3:
                    continue
                parent, costs, steps = {src: None}, {src: 0.0}, {src: 0}
                queue = [(0.0, src)]
                while queue:
                    cost, p = heappop(queue)
                    if costs[p] != cost or steps[p] >= 36:
                        continue
                    if p == target:
                        break
                    for n in self.neighbors[p]:
                        data = self.estimate_cell(n, steps[p]+1)
                        if not data or data[0] in BLOCKED:
                            continue
                        kind, owner, units = data
                        edge = 1 + (units*.10 + .6 if owner != self.army else 0)
                        edge += 2 if kind == MARSH else 0
                        edge += .6 if n not in self.cells else 0
                        new = cost+edge
                        if new < costs.get(n, float('inf')):
                            costs[n], steps[n], parent[n] = new, steps[p]+1, p
                            heappush(queue, (new, n))
                if target not in parent:
                    continue
                path = self.path(parent, target)
                if len(path) < 2 or path[1] not in self.cells:
                    continue
                power, valid = movable[src], True
                for k, p in enumerate(path[1:], 1):
                    kind, owner, units = self.estimate_cell(p, k)
                    if p in self.cells and owner == self.army:
                        if self.config.get('frontier_signed_ledger', False):
                            holds = getattr(self, '_active_reserves', {})
                            keep = max(1, holds.get(p, self.home_keep if p == self.home else 1))
                            power += units-keep
                            if power <= 0:
                                valid = False
                                break
                        elif (self.config.get('response_pool', False)
                                or self.config.get('producer_reserve',False)):
                            power += movable.get(p, 0)
                        else:
                            power += self.cells[p][2]-max(1, self.home_keep if p == self.home else 1)
                    else:
                        if power <= units:
                            valid = False
                            break
                        power -= units+(1 if p != target else 0)+(2 if kind == MARSH else 0)
                considered += 1
                if valid:
                    choices.append((6000.0/(len(path)-1) + sqrt(max(0, power)),
                        src, path[1], movable[src], 'assault', target))
                    funded += 1
        self.last_report.update(king_routes=considered, funded_king_routes=funded)

    def articulations(self):
        index, low, parent, critical = {}, {}, {}, set()
        def visit(p):
            index[p] = low[p] = len(index)
            children = 0
            for n in self.neighbors[p]:
                if n not in self.cells or self.cells[n][1] != self.army:
                    continue
                if n not in index:
                    parent[n] = p
                    children += 1
                    visit(n)
                    low[p] = min(low[p], low[n])
                    if p in parent and low[n] >= index[p]:
                        critical.add(p)
                elif parent.get(p) != n:
                    low[p] = min(low[p], index[n])
            if p not in parent and children > 1:
                critical.add(p)
        for p in self.owned:
            if p not in index:
                visit(p)
        return critical
