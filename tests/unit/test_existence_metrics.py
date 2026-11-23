"""M2-06: the citation existence metrics of RFC-002 section 7, on hand-counted examples."""

from utux.evalkit.metrics import Rate, existence_metrics


def test_precision_recall_and_false_alarms_are_counted_by_hand() -> None:
    # (system says invalid, reference is invalid), ten synthetic references:
    # 3 invalid references caught, 1 missed; 1 real reference flagged
    # (a false alarm), 5 real references passed.
    outcomes = [(True, True)] * 3 + [(False, True)] + [(True, False)] + [(False, False)] * 5
    metrics = existence_metrics(outcomes)
    # Precision of detecting invalid references: 3 / (3 + 1).
    assert metrics.precision == Rate(3, 4)
    # Recall: 3 / (3 + 1).
    assert metrics.recall == Rate(3, 4)
    # False-alarm rate on real references: 1 / (1 + 5).
    assert metrics.false_alarm_rate == Rate(1, 6)
    assert metrics.false_alarm_rate.value == 1 / 6


def test_with_nothing_flagged_precision_is_undefined() -> None:
    metrics = existence_metrics([(False, True), (False, False)])
    assert metrics.precision == Rate(0, 0)
    assert metrics.precision.value is None
    assert metrics.recall == Rate(0, 1)
    assert metrics.to_json()["false_alarm_rate"] == {"numerator": 0, "denominator": 1, "value": 0.0}
