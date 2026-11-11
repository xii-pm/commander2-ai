"""Observation-only estimate of the enemy's uncommitted mobile force.

This is a model, not a claim to observe hidden units. Combat removes equal troops
from each participant; known neutral losses must not be credited as enemy losses.
"""
from math import ceil
from std_geometry import BLANK, KING, FORT, MARSH


class ArmyLedger:
    def __init__(self):
        self.income = 0.0
        self.neutral_losses = 0
        self.pulses = 0
        self.last_tick = None
        self.last_order = None
        self.initial = None

    def observe(self, bot):
        old, cells, army = bot.previous, bot.cells, bot.army
        total = sum(d[2] for d in cells.values() if d[1] == army)
        if self.initial is None:
            self.initial = total
        delta = 0 if self.last_tick is None else max(0, bot.tick-self.last_tick)
        self.last_tick = bot.tick
        producers = sum(d[1] == army and d[0] in (KING, FORT) for d in old.values())
        self.income += producers*.5*delta
        pending = getattr(bot, '_observed_pending', None)
        touched = {pending['src'], pending['dst']} if pending else set()
        witnesses = [p for p, d in cells.items() if p not in touched
                     and d[:2] == (BLANK, army) and p in old
                     and old[p][:2] == (BLANK, army) and d[2]-old[p][2] == 1]
        if len(witnesses) >= 2:
            self.pulses += 1
            self.income += sum(d[:2] == (BLANK, army) for d in old.values())
            self.income -= sum(d[:2] == (MARSH, army) and d[2] > 0 for d in old.values())
        if pending and (pending['tick'], pending['src'], pending['dst']) != self.last_order:
            target = pending['dst']
            if (target in cells and cells[target][1] == army
                    and pending['before_dst'][1] == 0):
                self.neutral_losses += min(pending['sent'], pending['before_dst'][2])
                self.last_order = pending['tick'], pending['src'], pending['dst']
        # Fractional production timing contributes at most a small uncertainty;
        # the separate reserve margin remains in the caller.
        combat_losses = max(0, self.initial+self.income-total-self.neutral_losses)
        enemy_producers = max(1, sum(d[0] in (KING, FORT) and d[1] > 0
            and d[1] != army for d in bot.memory.values()))
        fields = sum(d[0] == BLANK and d[1] > 0 and d[1] != army
                     for d in bot.memory.values())
        income = max(0, bot.tick-1)*.5*enemy_producers
        # Before the first global pulse, each occupied field ties up a soldier.
        # At the first pulse that cost is repaid; later pulses create surplus.
        mobile = max(0, income-combat_losses+(self.pulses-1)*fields-1)
        return dict(mobile=int(ceil(mobile)), own_income=round(self.income, 2),
            combat_losses=round(combat_losses, 2), neutral_losses=self.neutral_losses,
            witnessed_pulses=self.pulses, observed_enemy_fields=fields,
            observed_enemy_producers=enemy_producers)
