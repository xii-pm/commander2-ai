"""SDK-compatible hex geometry and terrain constants."""
from functools import lru_cache

BLANK, KING, FORT, HILL, OBSTACLE, MARSH = range(1, 7)
BLOCKED = (HILL, OBSTACLE)
OFFSETS = (((-1, 0), (0, 1), (1, 0), (1, -1), (0, -1), (-1, -1)),
           ((-1, 1), (0, 1), (1, 1), (1, 0), (0, -1), (-1, 0)))


@lru_cache(maxsize=65536)
def hex_distance(a, b):
    """Bounded distance cache for the policy's immutable coordinate pairs."""
    ar, ac = a
    br, bc = b
    aq = ac - (ar - (ar & 1)) // 2
    bq = bc - (br - (br & 1)) // 2
    return max(abs(aq - bq), abs(ar - br), abs(aq - bq + ar - br))


def move_number(units, sent):
    sent = int(min(sent, units - 1))
    if sent < 1:
        raise ValueError('no movable soldiers')
    return sent

