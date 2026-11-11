"""Start a bounded economic phase only when an unfunded collection would win."""


def filter_choices(bot, choices):
    from std_objectives import prioritize
    producers = sum(bot.cells[p][0] in (2,3) for p in bot.owned)
    task = getattr(bot,'_neutral_capital_funding',None)
    if task and producers >= 2:
        bot._neutral_capital_completed = True
        task = None
    bad = getattr(bot,'_unfunded_neutral_collections',set())
    if (not task and not getattr(bot,'_neutral_capital_completed',False)
            and not getattr(bot,'_neutral_home_bank',None)
            and bot.calls >= 100 and len(bot.owned) >= 24
            and producers == 1 and len(set(bot.known_owners)-set(bot.eliminated)) == 1
            and choices and bad):
        ranked = prioritize(bot,list(choices)) if bot.config.get('objective_priority',False) else choices
        if ranked:
            winner = max(ranked)
            if winner[1:] in bad:
                if winner[2] == bot.home:
                    bot._neutral_home_bank = dict(started=bot.calls,trigger=winner,
                        reason='selected first-capital collection already banks existing stock at home')
                else:
                    task = dict(started=bot.calls,trigger=winner,
                        reason='highest-priority executable collection cannot currently fund its neutral fort')
    bot._neutral_capital_funding = task
    rejected,result = [],[]
    for row in choices:
        (rejected if task and row[1:] in bad else result).append(row)
    bot.last_report['neutral_capital_funding'] = dict(active=task,rejected=rejected,
        home_banking_policy=getattr(bot,'_neutral_home_bank',None),
        completed=getattr(bot,'_neutral_capital_completed',False),
        limitation='economic phase ends on observed second producer; no future income is dispatchable')
    return result
