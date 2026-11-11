"""Compare a small feeder with an already funded identical capture suffix.

Only current frontier proposals participate. An extra friendly command cannot
claim a higher target rate than its ready suffix merely through a different
source score. This is a local efficiency heuristic, not a survival proof.
"""
from std_geometry import KING, MARSH


def reprice_ready_suffixes(choices, paths, cells, army):
    """Cap feeder scores, retaining their orders and every other proposal.

    A suffix must already be funded, start at the first friendly destination,
    follow exactly the same route, and send more than the incoming small packet.
    King targets and marsh roads retain their existing treatment. Short routes
    are priced first, so a chain cannot recover a capped score upstream.
    """
    by_route = {path: index for index, path in paths.items()}
    changed = 0
    for index in sorted(paths, key=lambda i: (len(paths[i]), i)):
        path = paths[index]
        proposal = choices[index]
        score, src, first, amount, mode, target = proposal
        if (len(path) < 3 or mode != 'advance' or cells[target][0] == KING
                or cells[first][1] != army or cells[first][2] <= amount
                or any(cells[p][0] == MARSH for p in path[1:-1])):
            continue
        ready_index = by_route.get(path[1:])
        if ready_index is None:
            continue
        ready = choices[ready_index]
        if (ready[1] != first or ready[5] != target
                or ready[4] not in ('advance', 'capture')
                or ready[3] <= amount or ready[0] <= 0):
            continue
        cap = ready[0] * (len(path)-2) / float(len(path)-1)
        if score > cap:
            choices[index] = (cap,) + proposal[1:]
            changed += 1
    return changed
