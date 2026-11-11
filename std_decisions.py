"""Decisions methods preserved from the frozen BFS hunter."""


class Decisions:
    def decide(self, cells, hill_hints=None):
        self.update(cells, hill_hints)
        if self.home is None or not self.owned:
            return None
        if self.pending:
            self.last_report['mode'] = 'await_action'
            return self.finish(None)
        # King survival, defense, and safe empty forts outrank bridge work.
        for action in (lambda: self.immediate_capture(True), self.defend,
                       lambda: self.immediate_capture(empty_only=True)):
            move = action()
            if move:
                return self.finish(move)
        move = self.immediate_capture(neutral_only=True)
        if move:
            return self.finish(move)
        task = self.mission
        if task and task.get('kind') == 'assault' and task.get('strike_guard_pending'):
            move = self.resume_strike_guard(task['pos'])
            if move:
                task['progress'] = self.tick
                return self.finish(move)
            if task.get('strike_guard_pending'):
                self.last_report.update(mode='strike_guard_wait',
                                        strike_guard_waiting=True,
                                        strike_guard_pending=task['strike_guard_pending'],
                                        strike_guard_stage=task.get('strike_guard_stage'))
                return self.finish(None)
        move = self.urgent_fort_guard_action()
        if move:
            return self.finish(move)
        # After bridge work, preserve R50's guarded enemy-fort and raid priorities.
        for action in (lambda: self.immediate_capture(enemy_only=True),
                       self.counter_raid_action):
            move = action()
            if move:
                return self.finish(move)
        if self.kings and (not self.mission or self.mission['kind'] != 'assault'):
            move = self.launch(king_only=True)
            if move:
                return self.finish(move)
            stale_kings = all(self.tick - model['seen'] > self.KING_MAX_AGE
                              for model in self.kings.values())
            if stale_kings and not self.mission:
                move = self.launch()
                if move:
                    return self.finish(move)
            if not stale_kings or not self.mission:
                move = self.scout_known_king()
                if move:
                    return self.finish(move)
        if self.mission and self.cells[self.home][2] < self.home_keep:
            move = self.gather(self.home, 'restore departure-window guard', 'guard',
                               self.home_keep - self.cells[self.home][2])
            if move:
                return self.finish(move)
        move = self.hunt_probe()
        if move:
            return self.finish(move)
        if self.mission:
            move = self.mission_action()
            if move:
                return self.finish(move)
            if (self.mission and self.mission['kind'] == 'assault'
                    and self.last_report.get('assault_restage')):
                self.last_report['mode'] = 'assault_restage'
                return self.finish(None)
            if (self.mission and self.mission['kind'] == 'assault'
                    and self.last_report.get('strike_support_donors', 0) > 0):
                self.last_report['mode'] = 'assault_support_wait'
                return self.finish(None)
        for action in (self.immediate_capture, self.fort_guard_action,
                       lambda: self.economy.raid_action(self)):
            move = action()
            if move:
                return self.finish(move)
        if not self.mission and not self.kings:
            move = self.launch()
            if move:
                return self.finish(move)
        move = self.expand()
        if move:
            return self.finish(move)
        if self.EVERY_STEP or self.calls % 3 == 0:
            move = self.regional()
            if move:
                return self.finish(move)
        if not self.mission and not self.kings:
            # Rally at home only while forming; a known King keeps forces forward.
            move = self.gather(self.home, 'form next field army', 'gather')
            if move:
                return self.finish(move)
        elif not self.mission and self.kings:
            self.last_report['home_rally_held_for_king'] = True
        return self.finish(None)
