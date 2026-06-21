from dataclasses import dataclass

@dataclass
class Snapshot:
    views: int; likes: int; comments: int; shares: int

def velocity(snapshots: list[Snapshot]) -> float:
    if len(snapshots) < 2: return 0.0
    return float(snapshots[-1].views - snapshots[-2].views)

def acceleration(snapshots: list[Snapshot]) -> float:
    if len(snapshots) < 3: return 0.0
    v1 = snapshots[-2].views - snapshots[-3].views
    v2 = snapshots[-1].views - snapshots[-2].views
    return float(v2 - v1)

def phase(snapshots: list[Snapshot]) -> str:
    if len(snapshots) < 2: return "unknown"
    acc = acceleration(snapshots)
    vel = velocity(snapshots)
    if vel <= 0:     return "declining"
    if acc >= 0:     return "rising"
    return "peaked"

def severity(snapshots: list[Snapshot], followers: int = 0, is_negative: bool = False) -> float:
    if not snapshots: return 0.0
    latest  = snapshots[-1]
    vel     = velocity(snapshots)
    acc     = acceleration(snapshots)
    engagement = latest.likes + latest.comments * 2 + latest.shares * 3
    # Every term is floored at 0: a declining post (negative velocity, e.g. an
    # IG post whose play_count drops to 0 between fetches) contributes nothing
    # to severity rather than dragging the score below zero.
    total = (
        min(max(latest.views, 0)  / 10_000,  40.0) +   # reach         → до 40
        min(max(engagement, 0)    / 1_000,   20.0) +   # engagement    → до 20
        min(max(vel, 0.0)         / 1_000,   15.0) +   # velocity      → до 15
        min(max(acc, 0.0)         / 500,     20.0) +   # acceleration  → до 20
        min(max(followers, 0)     / 100_000,  5.0)     # автор         → до  5
    )
    if is_negative:
        total *= 1.3
    return round(min(max(total, 0.0), 100.0), 1)
