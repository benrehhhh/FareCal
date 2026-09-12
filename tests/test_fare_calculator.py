"""Unit tests for the fare calculation engine (no database required).

Run from the project root:
    python -m unittest tests.test_fare_calculator -v
or:
    python -m unittest discover -s tests -v
"""

import unittest

from services.fare_calculator import (
    apply_rounding,
    calculate_discount,
    calculate_regular_fare,
    validate_distance,
)

# Sample fare rule: base ₱13.00 for the first 4 km, then ₱1.80 per km,
# rounded UP to the nearest ₱0.25 (jeepney-style).
PUJ_RULE = {
    "fare_method": "base_succeeding",
    "base_distance": 4.0,
    "base_fare": 13.0,
    "succeeding_rate": 1.8,
    "minimum_fare": None,
    "maximum_fare": None,
    "rounding_rule": "round_up_025",
}

# Sample fare rule: ₱11.50 per km with a ₱55.00 minimum, whole-peso rounding.
UV_RULE = {
    "fare_method": "per_km",
    "base_distance": None,
    "base_fare": None,
    "succeeding_rate": None,
    "per_km_rate": 11.5,
    "minimum_fare": 55.0,
    "maximum_fare": None,
    "rounding_rule": "round_up_1",
}


class TestBaseSucceedingFare(unittest.TestCase):
    def test_within_base_distance_pays_base_fare(self):
        result = calculate_regular_fare(PUJ_RULE, 2.5)
        self.assertEqual(result["regular_fare"], 13.0)
        self.assertFalse(result["minimum_fare_applied"])

    def test_exactly_base_distance_pays_base_fare(self):
        result = calculate_regular_fare(PUJ_RULE, 4.0)
        self.assertEqual(result["regular_fare"], 13.0)

    def test_beyond_base_distance_adds_succeeding_fare(self):
        # 13.00 + (5 - 4) * 1.80 = 14.80 -> round up to 15.00
        result = calculate_regular_fare(PUJ_RULE, 5.0)
        self.assertEqual(result["regular_fare"], 15.0)

    def test_beyond_base_distance_rounds_to_next_025(self):
        # 13.00 + (6 - 4) * 1.80 = 16.60 -> round up to 16.75
        result = calculate_regular_fare(PUJ_RULE, 6.0)
        self.assertEqual(result["regular_fare"], 16.75)

    def test_long_distance_still_rounds_up(self):
        # 13.00 + (10 - 4) * 1.80 = 23.80 -> round up to 24.00
        result = calculate_regular_fare(PUJ_RULE, 10.0)
        self.assertEqual(result["regular_fare"], 24.0)


class TestPerKmFare(unittest.TestCase):
    def test_distance_times_rate(self):
        result = calculate_regular_fare(UV_RULE, 10.0)
        self.assertEqual(result["regular_fare"], 115.0)
        self.assertFalse(result["minimum_fare_applied"])

    def test_minimum_fare_applied_when_under(self):
        # 3.0 * 11.50 = 34.50 -> below the 55.00 minimum
        result = calculate_regular_fare(UV_RULE, 3.0)
        self.assertEqual(result["regular_fare"], 55.0)
        self.assertTrue(result["minimum_fare_applied"])

    def test_whole_peso_rounding(self):
        # 5.1 * 11.50 = 58.65 -> round up to 59.00
        result = calculate_regular_fare(UV_RULE, 5.1)
        self.assertEqual(result["regular_fare"], 59.0)


class TestRoundingRules(unittest.TestCase):
    def test_round_up_025(self):
        self.assertEqual(apply_rounding(13.0, "round_up_025"), 13.0)
        self.assertEqual(apply_rounding(14.8, "round_up_025"), 15.0)
        self.assertEqual(apply_rounding(16.6, "round_up_025"), 16.75)

    def test_round_up_1(self):
        self.assertEqual(apply_rounding(58.65, "round_up_1"), 59.0)
        self.assertEqual(apply_rounding(13.0, "round_up_1"), 13.0)

    def test_round_2(self):
        self.assertEqual(apply_rounding(13.005, "round_2"), 13.01)

    def test_unknown_rule_falls_back_to_two_decimals(self):
        self.assertEqual(apply_rounding(13.335, "not_a_real_rule"), 13.34)


class TestDiscount(unittest.TestCase):
    def test_twenty_percent_discount(self):
        amount, final = calculate_discount(100.0, 20)
        self.assertEqual(amount, 20.0)
        self.assertEqual(final, 80.0)

    def test_no_discount_when_zero(self):
        amount, final = calculate_discount(55.0, 0)
        self.assertEqual(amount, 0.0)
        self.assertEqual(final, 55.0)

    def test_discount_on_rounded_fare(self):
        # Regular fare 15.00 (already rounded), 20% discount -> 12.00
        amount, final = calculate_discount(15.0, 20)
        self.assertEqual(amount, 3.0)
        self.assertEqual(final, 12.0)


class TestDistanceValidation(unittest.TestCase):
    def test_valid_distance(self):
        self.assertEqual(validate_distance("10.5"), 10.5)

    def test_negative_rejected(self):
        with self.assertRaises(Exception):
            validate_distance(-1)

    def test_zero_rejected(self):
        with self.assertRaises(Exception):
            validate_distance(0)

    def test_non_numeric_rejected(self):
        with self.assertRaises(Exception):
            validate_distance("abc")

    def test_oversized_rejected(self):
        with self.assertRaises(Exception):
            validate_distance(501)


if __name__ == "__main__":
    unittest.main()