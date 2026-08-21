from scripts.run_discovery_evaluation import SCENARIOS


def test_scenario_catalog_has_required_breadth_and_three_rounds() -> None:
    assert len(SCENARIOS) == 15
    assert len({scenario.scenario_id for scenario in SCENARIOS}) == 15
    assert sum(scenario.category.startswith("电商-") for scenario in SCENARIOS) == 3
    assert all(len(scenario.answers) == 3 for scenario in SCENARIOS)
    assert all(len(scenario.domain_keywords) >= 6 for scenario in SCENARIOS)
    assert all(scenario.requirement and scenario.context for scenario in SCENARIOS)
