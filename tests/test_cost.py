from traffic_llm.cost_estimator import estimate, decisions_per_run, actual_cost


def test_call_count_math():
    # 500 ticks / interval 10 = 50 decisions; x 10 seeds x 1 scenario x 1 llm
    est = estimate(ticks=500, decision_interval=10, n_seeds=10,
                   n_scenarios=1, n_llm_controllers=1)
    assert est["decisions_per_run"] == 50
    assert est["api_calls"] == 500


def test_no_llm_no_calls():
    est = estimate(ticks=500, decision_interval=10, n_seeds=10, n_llm_controllers=0)
    assert est["api_calls"] == 0


def test_decisions_rounds_up():
    assert decisions_per_run(55, 10) == 6


def test_cost_ranges_ordered():
    est = estimate(ticks=500, decision_interval=10, n_seeds=4)
    assert est["cost_low"] <= est["cost_expected"] <= est["cost_high"]


def test_actual_cost_uses_cache_discount():
    full = actual_cost(tokens_in=10000, tokens_out=2000, tokens_cache_read=0)
    cached = actual_cost(tokens_in=10000, tokens_out=2000, tokens_cache_read=8000)
    assert cached < full
