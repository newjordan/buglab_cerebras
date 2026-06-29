import unittest


def normalize_item(row):
    return {
        "sku": row["sku"],
        "quantity": int(row["quantity"]),
        "warehouse_id": row["warehouse_id"],
    }


class InventoryContractTest(unittest.TestCase):
    def test_contract_requires_sku_and_warehouse(self):
        row = {"quantity": "3", "warehouse_id": "W1"}
        normalized = normalize_item(row)
        self.assertEqual(normalized["sku"], "SKU-1")


if __name__ == "__main__":
    unittest.main()
