import asyncio
from datetime import date


from src.laya_client import LayaClient
from src.sparks.eval import situation_eval as ev
from src.sparks.simulation import BattleSimulator
from src.sparks.situation import (
    HeuristicSituationReader,
    LayaPartialSituationReader,
    PartialSituation,
    SituationView,
)
from tests.fake_laya import FakeEngine
from tests.sparks.env import CATALOG

sim = BattleSimulator(CATALOG)
heuristic = HeuristicSituationReader()


def run(coro):
    return asyncio.run(coro)


class SensibleReader:
    """A partial reader whose reads move the right way."""

    async def read_partial(self, view: SituationView) -> PartialSituation:
        attack_share = view.enemy_history.count("ATTACK") / len(view.enemy_history) if view.enemy_history else None
        return PartialSituation(1 - view.own_hp_fraction, attack_share, 0.5)


class ConstantReader:
    async def read_partial(self, view: SituationView) -> PartialSituation:
        return PartialSituation(0.5, 0.5, 0.5)


class SilentReader:
    async def read_partial(self, view: SituationView) -> PartialSituation:
        return PartialSituation()


def test_collected_views_are_realistic_and_reproducible():
    a, b = run(ev.collect_views(sim, CATALOG, 25, seed=3)), run(ev.collect_views(sim, CATALOG, 25, seed=3))
    assert len(a) == 25 and a == b and all(0 < v.own_hp_fraction <= 1 for v in a)
    assert any(v.enemy_history for v in a) and any(not v.enemy_history for v in a)


def test_read_statistics_count_confident_answers_and_skip_round_one_aggression():
    views = run(ev.collect_views(sim, CATALOG, 30, seed=1))
    stats, latency = run(ev.measure_reads(LayaPartialSituationReader(LayaClient(FakeEngine())), views))
    assert stats["danger"].rate == 1.0 and stats["advantage"].asked == 30 and latency >= 0
    assert stats["aggression"].asked == sum(1 for v in views if v.enemy_history)
    silent, _ = run(ev.measure_reads(SilentReader(), views))
    assert silent["danger"].rate == 0.0


def test_uncertain_answers_lower_the_confident_rate():
    views = run(ev.collect_views(sim, CATALOG, 10, seed=1))
    stats, _ = run(ev.measure_reads(LayaPartialSituationReader(LayaClient(FakeEngine(confidence=0.3))), views))
    assert stats["danger"].confident == 0 and stats["danger"].asked == 10


def test_monotonic_agreement_tells_sensible_reads_from_constant_ones():
    views = run(ev.collect_views(sim, CATALOG, 12, seed=2))
    assert run(ev.monotonic_agreement(SensibleReader(), views)) == (1.0, 1.0)
    assert run(ev.monotonic_agreement(ConstantReader(), views)) == (0.0, 0.0)
    assert run(ev.monotonic_agreement(SilentReader(), views)) == (0.0, 0.0)


def test_win_rates_compare_two_readers_over_identical_matchups():
    same_a = run(ev.win_rate(sim, CATALOG, heuristic, 20, seed=4))
    same_b = run(ev.win_rate(sim, CATALOG, heuristic, 20, seed=4))
    assert same_a == same_b and 0.0 <= same_a <= 1.0


def test_the_whole_evaluation_runs_with_a_fake_model():
    report = run(ev.evaluate(CATALOG, LayaClient(FakeEngine()), views=12, battles=6, seed=5))
    assert report.views == 12 and report.battles == 6 and report.verdict == "heuristic"  # too few battles to qualify


def report(**changes):
    base = dict(views=100, danger=ev.QuestionStats(100, 90), aggression=ev.QuestionStats(80, 60), advantage=ev.QuestionStats(100, 85),
                mean_latency=0.2, danger_monotonic=0.9, aggression_monotonic=0.8, battles=150, laya_win_rate=0.58, heuristic_win_rate=0.5)
    return ev.EvalReport(**{**base, **changes})


def test_every_gate_must_pass_for_a_laya_verdict():
    assert report().verdict == "laya"
    for change in (
        dict(danger=ev.QuestionStats(100, 60)), dict(advantage=ev.QuestionStats(100, 69)), dict(danger_monotonic=0.79),
        dict(battles=99), dict(laya_win_rate=0.54), dict(laya_win_rate=0.4),
    ):
        assert report(**change).verdict == "heuristic", change


def test_the_report_states_results_gates_and_verdict():
    text = ev.render_report(report(), seed=7, today=date(2026, 10, 10))
    assert "2026-10-10" in text and "Seed: 7" in text and "Danger higher at low HP | 90%" in text
    assert "`situation_source` = `laya`" in text and "No gate was relaxed" in text
    assert "`heuristic`" in ev.render_report(report(battles=10), seed=7, today=date(2026, 10, 10))
