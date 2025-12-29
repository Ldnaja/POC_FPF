import unittest
from unittest.mock import AsyncMock, MagicMock, call

from order_service_async import OrderServiceAsync


class TestOrderServiceAsync(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """
        Prepare async mocked dependencies and instantiate OrderServiceAsync for each test.

        :parameter self: The test case instance.
        :return: None
        """
        self.gateway = MagicMock()
        self.repo = MagicMock()
        self.audit = MagicMock()

        self.gateway.authorize_payment = AsyncMock()
        self.repo.save_order = AsyncMock()
        self.audit.track = AsyncMock()

        self.service = OrderServiceAsync(self.gateway, self.repo, self.audit)

    async def test_success_returns_order_and_calls_dependencies(self):
        """
        Validate the success path by asserting returned order and correct awaited calls.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 10, "qty": 2}, {"price": 5, "qty": 1}]  # total=25

        self.gateway.authorize_payment.return_value = {"status": "approved", "payment_id": "pay_123"}
        self.repo.save_order.return_value = {"id": 99, "total": 25}

        order = await self.service.create_order(user_id=1, items=items)

        self.assertEqual(order["id"], 99)

        self.gateway.authorize_payment.assert_awaited_once_with(user_id=1, amount=25)
        self.repo.save_order.assert_awaited_once_with(
            user_id=1,
            items=items,
            total=25,
            payment_id="pay_123",
        )
        self.audit.track.assert_awaited_once_with("order_created", {"order_id": 99, "total": 25})

    async def test_denied_tracks_denied_and_does_not_save(self):
        """
        Validate that a denied payment tracks a denial event and does not persist the order.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 10, "qty": 1}]  # total=10
        self.gateway.authorize_payment.return_value = {"status": "denied"}

        with self.assertRaises(PermissionError):
            await self.service.create_order(user_id=7, items=items)

        self.gateway.authorize_payment.assert_awaited_once_with(user_id=7, amount=10)
        self.repo.save_order.assert_not_awaited()
        self.audit.track.assert_awaited_once_with("order_denied", {"user_id": 7, "total": 10})

    async def test_empty_items_raises_and_calls_nothing(self):
        """
        Validate that an empty items list raises ValueError and awaits no dependencies.

        :parameter self: The test case instance.
        :return: None
        """
        with self.assertRaises(ValueError):
            await self.service.create_order(user_id=1, items=[])

        self.gateway.authorize_payment.assert_not_awaited()
        self.repo.save_order.assert_not_awaited()
        self.audit.track.assert_not_awaited()

    async def test_gateway_raises_exception_side_effect(self):
        """
        Validate that a gateway exception is propagated and prevents persistence and audit calls.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 3, "qty": 2}]  # total=6
        self.gateway.authorize_payment.side_effect = TimeoutError("gateway timeout")

        with self.assertRaises(TimeoutError):
            await self.service.create_order(user_id=1, items=items)

        self.repo.save_order.assert_not_awaited()
        self.audit.track.assert_not_awaited()

    async def test_repo_raises_exception_side_effect(self):
        """
        Validate that a repository failure is propagated and does not track a success event.

        :parameter self: The test case instance.
        :return: None
        """
        items = [{"price": 4, "qty": 1}]  # total=4
        self.gateway.authorize_payment.return_value = {"status": "approved", "payment_id": "p1"}
        self.repo.save_order.side_effect = RuntimeError("db down")

        with self.assertRaises(RuntimeError):
            await self.service.create_order(user_id=1, items=items)

        self.gateway.authorize_payment.assert_awaited_once()
        self.audit.track.assert_not_awaited()

    async def test_multiple_calls_different_gateway_responses(self):
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
            await self.service.create_order(user_id=1, items=items)

        self.repo.save_order.reset_mock()
        self.audit.track.reset_mock()

        order = await self.service.create_order(user_id=1, items=items)
        self.assertEqual(order["id"], 2)

        self.repo.save_order.assert_awaited_once()
        self.audit.track.assert_awaited_once_with("order_created", {"order_id": 2, "total": 10})


if __name__ == "__main__":
    unittest.main(verbosity=2)
