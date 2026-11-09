import pytest

from ebay_tracker.stats import percentile, summarize


def test_summarize_empty_returns_none():
    assert summarize([]) is None


def test_summarize_reports_median_not_mean():
    # One accessory at $20 drags the mean down but leaves the median alone.
    summary = summarize([20.0, 500.0, 510.0, 520.0, 530.0])

    assert summary is not None
    assert summary.count == 5
    assert summary.low == 20.0
    assert summary.median == 510.0
    assert summary.mean == pytest.approx(416.0)


def test_summarize_single_price():
    summary = summarize([42.0])

    assert summary is not None
    assert summary.low == summary.p25 == summary.median == summary.mean == 42.0


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [(0.0, 10.0), (0.25, 17.5), (0.5, 25.0), (1.0, 40.0)],
)
def test_percentile_interpolates(fraction, expected):
    assert percentile([10.0, 20.0, 30.0, 40.0], fraction) == pytest.approx(expected)


def test_percentile_rejects_empty_sample():
    with pytest.raises(ValueError):
        percentile([], 0.5)
