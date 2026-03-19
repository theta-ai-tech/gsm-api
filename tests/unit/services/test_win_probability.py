"""Unit tests for win_probability (LAB-9)."""

from app.services.scoring_service import win_probability


class TestWinProbabilityEqual:
    def test_equal_points_returns_fifty(self) -> None:
        assert win_probability(1500, 1500) == 0.50

    def test_equal_zero_points_returns_fifty(self) -> None:
        assert win_probability(0, 0) == 0.50

    def test_equal_high_points_returns_fifty(self) -> None:
        assert win_probability(5000, 5000) == 0.50


class TestWinProbabilityPositiveDiff:
    def test_plus_500_approx_75(self) -> None:
        result = win_probability(2000, 1500)
        assert 0.74 <= result <= 0.76

    def test_plus_250_between_50_and_75(self) -> None:
        result = win_probability(1750, 1500)
        assert 0.50 < result < 0.75

    def test_plus_1000_high_probability(self) -> None:
        result = win_probability(2500, 1500)
        assert result > 0.90


class TestWinProbabilityNegativeDiff:
    def test_minus_500_approx_25(self) -> None:
        result = win_probability(1500, 2000)
        assert 0.24 <= result <= 0.26

    def test_minus_250_between_25_and_50(self) -> None:
        result = win_probability(1500, 1750)
        assert 0.25 < result < 0.50

    def test_minus_1000_low_probability(self) -> None:
        result = win_probability(1500, 2500)
        assert result < 0.10


class TestWinProbabilityClamping:
    def test_large_positive_diff_clamped_at_99(self) -> None:
        result = win_probability(5000, 3000)
        assert result == 0.99

    def test_large_negative_diff_clamped_at_01(self) -> None:
        result = win_probability(3000, 5000)
        assert result == 0.01

    def test_plus_2000_clamped_at_99(self) -> None:
        result = win_probability(3000, 1000)
        assert result == 0.99

    def test_minus_2000_clamped_at_01(self) -> None:
        result = win_probability(1000, 3000)
        assert result == 0.01


class TestWinProbabilitySymmetry:
    def test_symmetry_sums_to_one(self) -> None:
        """P(A beats B) + P(B beats A) == 1.0 for any point values."""
        a_prob = win_probability(2000, 1500)
        b_prob = win_probability(1500, 2000)
        assert a_prob + b_prob == 1.0

    def test_symmetry_at_zero_diff(self) -> None:
        a = win_probability(1000, 1000)
        b = win_probability(1000, 1000)
        assert a == b == 0.50


class TestWinProbabilityRounding:
    def test_result_has_two_decimal_places(self) -> None:
        result = win_probability(1100, 1000)
        assert result == round(result, 2)
