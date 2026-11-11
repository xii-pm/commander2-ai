"""Public strategy entry point; no SDK dependency. Python 3.6 standard library."""
from std_geometry import (BLANK, KING, FORT, HILL, OBSTACLE, MARSH,
                          BLOCKED, OFFSETS, hex_distance, move_number)
from std_parameters import Parameters
from std_state import State
from std_routing import Routing
from std_defense import Defense
from std_combat import Combat
from std_campaign import Campaign
from std_recon import Recon
from std_logistics import Logistics
from std_expansion import Expansion
from std_decisions import Decisions
from std_config import load, validate
from std_enhancements import Enhancements
from std_continuous import Continuous
from std_map314 import Map314Detector
import std_map314_strategy


class BaselineAgent(Parameters, State, Routing, Defense, Combat, Campaign,
                    Recon, Logistics, Expansion, Decisions):
    """Behavior-preserving hunter reference for parity and ablation."""
    pass


class Agent(Continuous, Enhancements, BaselineAgent):
    """Deployment policy. Enhancements are enabled only by validated settings."""
    def __init__(self, army, rows, cols, config=None):
        super().__init__(army, rows, cols)
        self.config = load() if config is None else validate(config)
        self.EVERY_STEP = self.config['every_step']
        if self.EVERY_STEP:
            for name in ('KING_STALE_PROBE_INTERVAL', 'STRIKE_RESTAGE_INTERVAL',
                         'STRIKE_KING_REFRESH_INTERVAL', 'POST_KING_GUARD_INTERVAL',
                         'COUNTER_RAID_INTERVAL', 'CAMPAIGN_EXPAND_INTERVAL',
                         'HUNT_PROBE_INTERVAL'):
                setattr(self, name, 1)
            self.HUNT_OPENING_CALLS = 0
            self.HUNT_PROBE_MISSION_MIN_AGE = 0
        self.HILL_HINT_UNSEEN_KING_WEIGHT = self.config['hint_weight']
        self.HILL_HINT_APPROACH_WEIGHT = self.config['approach_weight']
        self.map314_detector = Map314Detector(army, rows, cols)
        self.map314 = 0
        from std_king_prior import KingPrior
        from std_king_opportunity import Opportunity
        self.king_prior = KingPrior(army,rows,cols) if self.config.get('symmetric_king_prior',False) else None
        self.king_opportunity = Opportunity() if self.config.get('king_opportunity',False) else None

    def decide(self, cells, hill_hints=None):
        self.map314 = self.map314_detector.observe(cells, hill_hints)
        if self.king_prior is not None:
            self.king_prior.observe(cells,hill_hints or (),bool(self.map314))
        if self.king_opportunity is not None and not self.map314:
            self.king_opportunity.observe(self,cells)
        move = (self.decide_map314(cells, hill_hints) if self.map314
                else self.decide_normal(cells, hill_hints))
        self.last_report.update(map314=self.map314,
            map314_detection=self.map314_detector.report(),
            strategy_route='map314_three_player' if self.map314 else 'normal',
            strategy_implementation=std_map314_strategy.IMPLEMENTATION if self.map314 else 'normal')
        if self.king_prior is not None:
            self.last_report['king_prior'] = self.king_prior.report()
        return move

    def information_focus(self):
        prior = self.king_prior.focus(self) if self.king_prior is not None and not self.map314 else None
        return prior if prior is not None else super().information_focus()

    def focus(self):
        prior = self.king_prior.focus(self) if self.king_prior is not None and not self.map314 else None
        return prior if prior is not None else super().focus()

    def decide_normal(self, cells, hill_hints=None):
        return super().decide(cells, hill_hints)

    def decide_map314(self, cells, hill_hints=None):
        if getattr(self, '_map314_late_active', False):
            return std_map314_strategy.decide(self, cells, hill_hints)
        if getattr(self, '_map314_handoff', False):
            controller = getattr(self, '_map314_controller', None)
            if controller and controller.late_opportunity(self, cells):
                return std_map314_strategy.decide(self, cells, hill_hints)
            move = self.decide_normal(cells, hill_hints)
            self.last_report['strategy_phase'] = 'campaign_after_314_first_wave'
            return move
        return std_map314_strategy.decide(self, cells, hill_hints)

