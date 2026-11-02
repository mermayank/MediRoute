import unittest
from safety import validate_online_item, can_dispatch

class PharmacySafetyTests(unittest.TestCase):
    def test_schedule_h_requires_prescription(self):
        self.assertFalse(validate_online_item('H', False)[0])
        self.assertTrue(validate_online_item('H', True)[0])

    def test_schedule_h1_requires_prescription(self):
        self.assertFalse(validate_online_item('H1', False)[0])
        self.assertTrue(validate_online_item('H1', True)[0])

    def test_schedule_x_and_narcotic_are_blocked(self):
        self.assertFalse(validate_online_item('X', True)[0])
        self.assertFalse(validate_online_item('NARCOTIC', True)[0])

    def test_dispatch_blocks_unapproved_h(self):
        ok, _ = can_dispatch([{'schedule':'H','approval_status':'pending'}], 'verified')
        self.assertFalse(ok)

    def test_dispatch_allows_approved_h(self):
        ok, _ = can_dispatch([{'schedule':'H','approval_status':'approved'}], 'verified')
        self.assertTrue(ok)

    def test_dispatch_blocks_unverified_order(self):
        ok, _ = can_dispatch([{'schedule':'OTC','approval_status':'approved'}], 'awaiting_verification')
        self.assertFalse(ok)

    def test_dispatch_blocks_schedule_x(self):
        ok, _ = can_dispatch([{'schedule':'X','approval_status':'approved'}], 'verified')
        self.assertFalse(ok)

if __name__ == '__main__': unittest.main()
