from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256


def select_node(key: str, nodes: Sequence[str]) -> str | None:
    """Rendezvous (HRW) hashing: returns node with highest sha256(key + node) hash.

    Property: adding/removing 1 node remaps only 1/N keys (vs N-1/N for modulo).
    Time complexity: O(N) where N = number of nodes.
    Every node is scored independently, so the winner is stable across restarts.
    """
    if not nodes:
        return None
    if len(nodes) == 1:
        return nodes[0]

    def _score(node: str) -> bytes:
        return sha256(f"{key}:{node}".encode()).digest()

    # Preserve the highest-score winner for every non-empty candidate set.
    return max(nodes, key=_score)
