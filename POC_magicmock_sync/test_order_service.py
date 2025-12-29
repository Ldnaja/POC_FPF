import unittest
from unittest.mock import MagicMock, call

from order_service import OrderService


class TestOrderService(unittest.TestCase):
    def setUp(self):
        """
        Prepare mocked dependencies and instantiate OrderService for each test.

        :parameter self: The test case instance.
        :return: None
        """
        self.gateway = MagicMock()
        self.repo = MagicMock()
        self.audit = MagicMock()
        self.service = OrderService(self.gateway, self.repo, self.audit)

    def test_success_returns_order_and_calls_dependencies(self):
        """
        Validate the success path by asserting returned order and correct dependency calls.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 10, "qty": 2}, {"price": 5, "qty": 1}] # total = 25

        self.gateway.authorize_payment.return_value = {
            "status": "approved",
            "payment_id": "pay_123",
        }
        self.repo.save_order.return_value = {"id": 99, "total": 25}

        order = self.service.create_order(user_id=1, items=items)

        self.assertEqual(order["id"], 99)

        self.gateway.authorize_payment.assert_called_once_with(user_id=1, amount=25)
        self.repo.save_order.assert_called_once_with(
            user_id=1,
            items=items,
            total=25,
            payment_id="pay_123",
        )
        self.audit.track.assert_called_once_with(
            "order_created", {"order_id": 99, "total": 25}
        )

    def test_denied_tracks_denied_and_does_not_save(self):
        """
        Validate that a denied payment tracks a denial event and does not persist the order.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 10, "qty": 1}]  # total=10
        self.gateway.authorize_payment.return_value = {"status": "denied"}

        with self.assertRaises(PermissionError):
            self.service.create_order(user_id=7, items=items)

        self.gateway.authorize_payment.assert_called_once_with(user_id=7, amount=10)
        self.repo.save_order.assert_not_called()
        self.audit.track.assert_called_once_with(
            "order_denied", {"user_id": 7, "total": 10}
        )

    def test_empty_items_raises_and_calls_nothing(self):
        """
        Validate that an empty items list raises ValueError and calls no dependencies.

        :parameter self: The test case instance.
        :return: None
        """
        with self.assertRaises(ValueError):
            self.service.create_order(user_id=1, items=[])

        self.gateway.authorize_payment.assert_not_called()
        self.repo.save_order.assert_not_called()
        self.audit.track.assert_not_called()

    def test_gateway_raises_exception_side_effect(self):
        """
        Validate that a gateway exception is propagated and prevents persistence and audit calls.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 3, "qty": 2}]  # total=6
        self.gateway.authorize_payment.side_effect = TimeoutError("gateway timeout")

        with self.assertRaises(TimeoutError):
            self.service.create_order(user_id=1, items=items)

        self.repo.save_order.assert_not_called()
        self.audit.track.assert_not_called()

    def test_repo_raises_exception_side_effect(self):
        """
        Validate that a repository failure is propagated and does not track a success event.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 4, "qty": 1}]  # total=4
        self.gateway.authorize_payment.return_value = {
            "status": "approved",
            "payment_id": "p1",
        }
        self.repo.save_order.side_effect = RuntimeError("db down")

        with self.assertRaises(RuntimeError):
            self.service.create_order(user_id=1, items=items)

        self.gateway.authorize_payment.assert_called_once()
        self.audit.track.assert_not_called()

    def test_order_of_calls_using_attach_mock(self):
        """
        Validate global call order: authorize payment, save order, then track success.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 2, "qty": 2}]  # total=4
        self.gateway.authorize_payment.return_value = {
            "status": "approved",
            "payment_id": "p1",
        }
        self.repo.save_order.return_value = {"id": 1, "total": 4}

        parent = MagicMock()
        parent.attach_mock(self.gateway, "gateway")
        parent.attach_mock(self.repo, "repo")
        parent.attach_mock(self.audit, "audit")

        self.service.create_order(user_id=1, items=items)

        parent.assert_has_calls(
            [
                call.gateway.authorize_payment(user_id=1, amount=4),
                call.repo.save_order(user_id=1, items=items, total=4, payment_id="p1"),
                call.audit.track("order_created", {"order_id": 1, "total": 4}),
            ],
            any_order=False,
        )

    def test_qty_default_is_1_when_missing(self):
        """
        Validate that qty defaults to 1 when missing, affecting the total sent to the gateway.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 10}, {"price": 5, "qty": 3}]  # total=25
        self.gateway.authorize_payment.return_value = {
            "status": "approved",
            "payment_id": "p1",
        }
        self.repo.save_order.return_value = {"id": 10, "total": 25}

        self.service.create_order(user_id=1, items=items)

        self.gateway.authorize_payment.assert_called_once_with(user_id=1, amount=25)

    def test_multiple_calls_different_gateway_responses(self):
        """
        Validate sequential gateway outcomes using side_effect and different behavior across runs.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 10, "qty": 1}]  # total=10
        self.gateway.authorize_payment.side_effect = [
            {"status": "denied"},
            {"status": "approved", "payment_id": "p2"},
        ]
        self.repo.save_order.return_value = {"id": 2, "total": 10}

        with self.assertRaises(PermissionError):
            self.service.create_order(user_id=1, items=items)

        self.repo.save_order.reset_mock()
        self.audit.track.reset_mock()

        order = self.service.create_order(user_id=1, items=items)
        self.assertEqual(order["id"], 2)

        self.repo.save_order.assert_called_once()
        self.audit.track.assert_called_once_with(
            "order_created", {"order_id": 2, "total": 10}
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
