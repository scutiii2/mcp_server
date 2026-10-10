"""Do Laya's situation reads earn their place? Run manually with the real model:

    python -m src.ascension.eval.situation_eval [--views N] [--battles N] [--seed S] [--out PATH]

Needs `pip install -e ".[laya]"`. Not part of the test suite. It measures, on
matched states, how often Laya answers confidently, whether its reads move the
right way (danger rises as HP falls; enemy aggression rises with the enemy's
ATTACK share), how slowly it answers, and whether an Ascended that uses Laya's reads
beats one that uses the engine heuristics. The default `situation_source` stays
`heuristic` unless every gate below passes.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Sequence

from src.config import load_config
from src.laya_client import DEFAULT_MODEL, LayaClient
from src.ascension.catalog import Catalog
from src.ascension.models import PLAYER, PersonalityInstance
from src.ascension.simulation import BattleSimulator, Combatant
from src.ascension.situation import (
    FallbackSituationReader,
    HeuristicSituationReader,
    LayaPartialSituationReader,
    PartialSituationReader,
    SituationReader,
    SituationView,
)

OUT_PATH = Path(__file__).resolve().parents[3] / "docs" / "ascension-laya-eval.md"
MIN_CONFIDENT_RATE = 0.7  # danger and advantage answers that are valid and confident
MIN_MONOTONIC = 0.8  # danger rises as HP falls
MIN_WIN_GAIN = 0.05  # win rate with Laya reads minus win rate with heuristics
MIN_BATTLES = 100
LOW_HP, HIGH_HP = 0.15, 0.9


@dataclass(frozen=True)
class QuestionStats:
    asked: int
    confident: int

    @property
    def rate(self) -> float:
        return self.confident / self.asked if self.asked else 0.0


@dataclass(frozen=True)
class EvalReport:
    views: int
    danger: QuestionStats
    aggression: QuestionStats
    advantage: QuestionStats
    mean_latency: float
    danger_monotonic: float
    aggression_monotonic: float
    battles: int
    laya_win_rate: float
    heuristic_win_rate: float

    @property
    def verdict(self) -> str:
        enough = self.battles >= MIN_BATTLES
        passed = (
            self.danger.rate >= MIN_CONFIDENT_RATE and self.advantage.rate >= MIN_CONFIDENT_RATE
            and self.danger_monotonic >= MIN_MONOTONIC and enough
            and self.laya_win_rate - self.heuristic_win_rate >= MIN_WIN_GAIN
        )
        return "laya" if passed else "heuristic"


def random_combatant(catalog: Catalog, rng: random.Random, reader: SituationReader) -> Combatant:
    spec = rng.choice(catalog.regular_ascendeds())
    types = list(catalog.personalities)
    instances = tuple(PersonalityInstance(f"e{n}", rng.choice(types), rng.randint(1, 3)) for n in range(rng.randint(1, 3)))
    return Combatant(spec.id, "common", rng.randint(3, 25), instances, reader)


async def collect_views(simulator: BattleSimulator, catalog: Catalog, count: int, seed: int) -> list[SituationView]:
    """Situations reached in AI-against-AI battles, so the questions see realistic states."""
    rng = random.Random(seed)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    views: list[SituationView] = []
    while len(views) < count:
        a, b = random_combatant(catalog, rng, heuristic), random_combatant(catalog, rng, heuristic)
        report = await simulator.run(a, b, seed=rng.randrange(10**9), max_rounds=40)
        views.extend(report.views)
    return views[:count]


async def measure_reads(reader: PartialSituationReader, views: Sequence[SituationView]) -> tuple[dict[str, QuestionStats], float]:
    asked = {"danger": 0, "aggression": 0, "advantage": 0}
    confident = dict.fromkeys(asked, 0)
    elapsed = 0.0
    for view in views:
        started = time.monotonic()
        partial = await reader.read_partial(view)
        elapsed += time.monotonic() - started
        for name in asked:
            if name == "aggression" and not view.enemy_history:
                continue  # never asked in round 1
            asked[name] += 1
            confident[name] += getattr(partial, name) is not None
    return {n: QuestionStats(asked[n], confident[n]) for n in asked}, elapsed / max(len(views), 1)


async def monotonic_agreement(reader: PartialSituationReader, views: Sequence[SituationView]) -> tuple[float, float]:
    """Share of paired reads where danger is higher at low HP and where enemy aggression is higher
    after ATTACK-only history than after DEFENSE-only history. Pairs with a missing read are skipped."""
    danger_hits = danger_pairs = aggression_hits = aggression_pairs = 0
    for view in views:
        low = await reader.read_partial(replace(view, own_hp_fraction=LOW_HP))
        high = await reader.read_partial(replace(view, own_hp_fraction=HIGH_HP))
        if low.danger is not None and high.danger is not None:
            danger_pairs += 1
            danger_hits += low.danger > high.danger
        attacking = await reader.read_partial(replace(view, enemy_history=("ATTACK",) * 4))
        defending = await reader.read_partial(replace(view, enemy_history=("DEFENSE",) * 4))
        if attacking.aggression is not None and defending.aggression is not None:
            aggression_pairs += 1
            aggression_hits += attacking.aggression > defending.aggression
    return (danger_hits / danger_pairs if danger_pairs else 0.0, aggression_hits / aggression_pairs if aggression_pairs else 0.0)


async def win_rate(simulator: BattleSimulator, catalog: Catalog, reader: SituationReader, battles: int, seed: int) -> float:
    """Wins of an Ascended that uses `reader` against one that uses the heuristic, over the same matchups."""
    rng = random.Random(seed)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    wins = 0
    for _ in range(battles):
        mine, theirs = random_combatant(catalog, rng, reader), random_combatant(catalog, rng, heuristic)
        report = await simulator.run(mine, theirs, seed=rng.randrange(10**9), max_rounds=40)
        wins += report.winner == PLAYER
    return wins / battles


async def evaluate(catalog: Catalog, laya: LayaClient, views: int, battles: int, seed: int) -> EvalReport:
    simulator = BattleSimulator(catalog)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    partial = LayaPartialSituationReader(laya)
    sample = await collect_views(simulator, catalog, views, seed)
    stats, latency = await measure_reads(partial, sample)
    danger_monotonic, aggression_monotonic = await monotonic_agreement(partial, sample[: max(views // 4, 1)])
    laya_rate = await win_rate(simulator, catalog, FallbackSituationReader(partial, heuristic), battles, seed + 1)
    heuristic_rate = await win_rate(simulator, catalog, heuristic, battles, seed + 1)
    return EvalReport(views, stats["danger"], stats["aggression"], stats["advantage"], latency,
                      danger_monotonic, aggression_monotonic, battles, laya_rate, heuristic_rate)


def render_report(report: EvalReport, seed: int, today: date) -> str:
    rate = lambda s: f"{s.rate:.0%} of {s.asked}"  # noqa: E731
    return "\n".join([
        "# Ascension: Laya situation reads", "",
        f"Date: {today.isoformat()}. Model: `{DEFAULT_MODEL}`. Seed: {seed}. Views: {report.views}. Battles per side: {report.battles}.", "",
        "| Measure | Result | Gate |", "|---|---|---|",
        f"| Danger answered confidently | {rate(report.danger)} | at least {MIN_CONFIDENT_RATE:.0%} |",
        f"| Advantage answered confidently | {rate(report.advantage)} | at least {MIN_CONFIDENT_RATE:.0%} |",
        f"| Enemy aggression answered confidently | {rate(report.aggression)} | reported only |",
        f"| Danger higher at low HP | {report.danger_monotonic:.0%} | at least {MIN_MONOTONIC:.0%} |",
        f"| Aggression higher after ATTACK history | {report.aggression_monotonic:.0%} | reported only |",
        f"| Mean latency per read | {report.mean_latency:.2f} s | reported only |",
        f"| Win rate with Laya reads | {report.laya_win_rate:.0%} | |",
        f"| Win rate with heuristic reads | {report.heuristic_win_rate:.0%} | Laya at least {MIN_WIN_GAIN:.0%} higher, with {MIN_BATTLES}+ battles |",
        "", f"**Verdict: `situation_source` = `{report.verdict}`.** Set it in `configs/config_app.json` and its `.example`.", "",
        "Positions and battles come from simulated play, not from real players. Personality influence is tested on the "
        "engine's own distributions (`tests/ascension/test_simulation.py`), not on the model. No gate was relaxed to reach a verdict.", "",
    ])


async def run(views: int, battles: int, seed: int, out: Path) -> str:
    config = load_config()
    laya = LayaClient(timeout=30.0, min_confidence=config.laya_min_confidence)
    if not laya.is_available():
        raise SystemExit('Laya is not installed: pip install -e ".[laya]"')
    laya.prepare()
    report = await evaluate(Catalog.load(), laya, views, battles, seed)
    text = render_report(report, seed, date.today())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--views", type=int, default=120)
    parser.add_argument("--battles", type=int, default=150)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    print(asyncio.run(run(args.views, args.battles, args.seed, args.out)))


if __name__ == "__main__":
    main()
