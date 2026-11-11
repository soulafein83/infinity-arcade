import os
import sys
import unittest

# Add the src directory to the path for module imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infinity_arcade.main import parse_max_retries


class TestParseMaxRetries(unittest.TestCase):
    def test_default_when_unset(self):
        self.assertEqual(parse_max_retries(None), 1)

    def test_default_when_empty(self):
        self.assertEqual(parse_max_retries(""), 1)

    def test_valid_one(self):
        self.assertEqual(parse_max_retries("1"), 1)

    def test_valid_two(self):
        self.assertEqual(parse_max_retries("2"), 2)

    def test_whitespace_is_stripped(self):
        self.assertEqual(parse_max_retries(" 2 "), 2)

    def test_zero_clamped_to_one(self):
        self.assertEqual(parse_max_retries("0"), 1)

    def test_negative_clamped_to_one(self):
        self.assertEqual(parse_max_retries("-3"), 1)

    def test_invalid_falls_back_to_default(self):
        self.assertEqual(parse_max_retries("abc"), 1)


if __name__ == "__main__":
    unittest.main()
