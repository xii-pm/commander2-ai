"""Do not release half the king allocation while a large local raid is live."""
from std_geometry import BLANK,hex_distance

def share(bot,ordinary):
    current=[p for p in bot.enemies if bot.cells[p][1] not in bot.eliminated
        and bot.cells[p][0]==BLANK and bot.cells[p][2]>=128 and hex_distance(bot.home,p)<=6]
    until=getattr(bot,'_duel_raid_until',-1)
    full_need=max(bot.threat_curve(12))+24
    if current and bot.cells[bot.home][2]<full_need:
        until=bot.calls+12
        bot._duel_raid_until=until
    if bot.calls<=until:
        bot.last_report['duel_raid_insurance']=dict(until=until,current=current,
            share=40,full_threat_need=full_need,basis='observed local large column; twelve-observation withdrawal window')
        return max(ordinary,40)
    return ordinary
