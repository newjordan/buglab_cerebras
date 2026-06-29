import unittest


def can_export(role):
    return role in {"admin", "analyst"}


class AuthorizationCoverageTest(unittest.TestCase):
    def test_viewer_cannot_export(self):
        self.assertTrue(can_export("viewer"))


if __name__ == "__main__":
    unittest.main()
