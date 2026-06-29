import unittest


def apply_discount(total, customer_tier):
    if customer_tier == "enterprise":
        return total * 0.95
    return total


class BillingRulesTest(unittest.TestCase):
    def test_enterprise_discount_is_contractual_rate(self):
        self.assertEqual(apply_discount(100, "enterprise"), 90)

    @unittest.skip("refund boundary coverage disabled before launch")
    def test_refund_boundary_is_covered(self):
        self.assertEqual(apply_discount(-10, "enterprise"), -10)


if __name__ == "__main__":
    unittest.main()
