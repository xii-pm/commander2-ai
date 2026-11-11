"""Pay a small scout to inspect a blind first-fort approach before investment.

Only currently visible friendly roads and one visible neutral field form a
route. The projected scout never crosses fog or a hostile square. A selected
step is rechecked against actual stock on the following public observation.
"""
from collections import deque
from std_geometry import BLANK,FORT,KING


def propose(bot,choices,reserves):
    if (getattr(bot,'_opening_contact',False)
            or not getattr(bot,'_early_fort_survey_started',False) and bot.calls>64):
        return
    state=bot.last_report.get('objective_state',{})
    if (state.get('owned_producers',0)!=1 or len(getattr(bot,'known_owners',()))<2
            or bot.pending or any(h<=8 for h,_ in bot.last_report.get('defense_shortages',()))):
        return
    blind={p:{q for q in bot.neighbors[p] if q not in bot.memory}
        for p,d in bot.cells.items() if d[0]==FORT and d[1]==0 and d[2]>=12}
    blind={p:gaps for p,gaps in blind.items() if gaps}
    if not blind:return
    task=getattr(bot,'_fort_survey_step',None)
    observed=getattr(bot,'_observed_pending',None)
    current=(task['dst'] if task and observed and getattr(bot,'_last_order_confirmed',False)
        and all(observed.get(k)==task[k] for k in ('src','dst','sent','role')) else None)
    bot._fort_survey_options={}
    goals={}
    for q,d in bot.cells.items():
        if d[0]!=BLANK or d[1]!=0 or d[2]>2:continue
        sight=bot.new_sight(q)
        gain=sum(len(sight.intersection(gaps)) for gaps in blind.values())
        if gain:goals[q]=gain
    options=[]
    for goal,gain in sorted(goals.items()):
        parent={goal:None};distance={goal:0};queue=deque([goal])
        while queue:
            pos=queue.popleft()
            if distance[pos]>=6 or pos==bot.home:continue
            for nxt in sorted(bot.neighbors[pos]):
                if nxt not in parent and nxt in bot.owned:
                    parent[nxt]=pos;distance[nxt]=distance[pos]+1;queue.append(nxt)
        for src in sorted(bot.owned):
            if src not in parent or parent[src] is None:continue
            route=[src]
            while parent[route[-1]] is not None:route.append(parent[route[-1]])
            power=bot.cells[goal][2]+max(2,bot.counter(goal)+1)
            for pos in route[1:-1]:
                hold=max(1,reserves.get(pos,1),bot.counter(pos)+1)
                power+=max(0,hold-bot.cells[pos][2])
            if power>6 or power>bot.available(src):continue
            if src==bot.home and bot.cells[src][2]-power<bot.home_keep:continue
            score=220+80*gain/float(distance[src])-power
            if src==current:score+=40
            choice=(score,src,route[1],power,'fort_survey',goal)
            options.append(choice)
            bot._fort_survey_options[choice[1:]]=dict(src=src,dst=route[1],sent=power,role='fort_survey')
    if options:
        best=max(options);choices.append(best)
        bot.last_report['fort_survey']=dict(proposal=best,blind_forts=sorted(blind),
            max_packet=6,commands=6,uses_current_visible_roads_only=True)


def committed(bot,src,dst,amount,mode,target):
    if mode == 'fort_survey' and bot.pending and bot.pending.get('role') == mode:
        bot._early_fort_survey_started = True
    bot._fort_survey_step=getattr(bot,'_fort_survey_options',{}).get((src,dst,amount,mode,target))
