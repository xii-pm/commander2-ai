"""Conservative independent-route cover under a shared command deadline."""


def select_cover(candidates, budget, need):
    """Return donor indices, delivered force and total commands.

    Each candidate is (commands, guaranteed_payload). Shared roads do not earn
    a discount and intermediate garrisons do not count as payload. Thus the
    table cannot spend one command or one soldier twice. This is a scheduling
    estimate on the observed owned network, not a promise against enemy cuts.
    """
    table = {0: (0, ())}
    for index, (cost, payload) in enumerate(candidates):
        if cost <= 0 or payload <= 0 or cost > budget:
            continue
        updated = dict(table)
        for used, (force, selected) in table.items():
            commands = used+cost
            if commands > budget:
                continue
            option = force+payload, selected+(index,)
            if commands not in updated or option > updated[commands]:
                updated[commands] = option
        table = updated
    funded = [(cost, force, indices) for cost, (force, indices) in table.items()
              if force >= need and indices]
    if funded:
        cost, force, indices = min(funded, key=lambda x: (x[0], -x[1], x[2]))
    else:
        cost, (force, indices) = max(table.items(), key=lambda x: (x[1][0], -x[0]))
    return indices, force, cost
