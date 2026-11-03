"""Checks for the hotel tools: python -m unittest test_hotel"""

import importlib
import unittest

import hotel


class ChangeCheckoutTime(unittest.TestCase):
    def setUp(self):
        importlib.reload(hotel)   # fresh in-memory bookings for every test

    def change(self, code, time):
        return hotel.change_checkout_time(code, time)

    def test_late_checkout_fee_for_standard_room(self):
        self.assertEqual(self.change("GM41055", "14:00")["fee_gbp"], 25)

    def test_late_checkout_free_for_member_until_1600(self):
        self.assertEqual(self.change("GM40912", "16:00")["fee_gbp"], 0)
        self.assertEqual(self.change("GM40912", "17:00")["fee_gbp"], 25)

    def test_earlier_or_same_checkout_is_not_charged(self):
        self.assertEqual(self.change("GM41055", "10:00")["fee_gbp"], 0)
        self.assertEqual(self.change("GM41055", "11:00")["fee_gbp"], 0)

    def test_single_digit_hour_is_accepted_and_normalized(self):
        result = self.change("GM40912", "9:30")
        self.assertEqual(result["new_checkout_time"], "09:30")
        self.assertEqual(result["fee_gbp"], 0)

    def test_malformed_time_is_rejected_and_not_stored(self):
        for bad in ("12", "2pm", "14:0", "25:00", "noon"):
            self.assertIn("error", self.change("GM40912", bad), bad)
        self.assertEqual(hotel.RESERVATIONS["GM40912"]["checkout_time"], "11:00")

    def test_after_latest_checkout_is_rejected(self):
        self.assertIn("error", self.change("GM41182", "18:30"))


if __name__ == "__main__":
    unittest.main()
