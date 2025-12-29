class OrderServiceAsync:
    def __init__(self, gateway, repo, audit):
        """
        Initialize the async order service with injected dependencies.

        :parameter gateway: Async payment client exposing authorize_payment.
        :parameter repo: Async repository exposing save_order.
        :parameter audit: Async audit/telemetry exposing track.
        :return: None
        """
        self.gateway = gateway
        self.repo = repo
        self.audit = audit

    async def create_order(self, user_id: int, items: list[dict]) -> dict:
        """
        Create an order asynchronously by authorizing payment, saving it, and tracking the outcome.

        :parameter user_id: The user identifier who owns the order.
        :parameter items: A list of order items (each item must have price and may have qty).
        :return: A dictionary representing the persisted order.
        """
        if not items:
            raise ValueError("items cannot be empty")

        total = sum(i["price"] * i.get("qty", 1) for i in items)

        auth = await self.gateway.authorize_payment(user_id=user_id, amount=total)
        status = auth.get("status")

        if status != "approved":
            await self.audit.track("order_denied", {"user_id": user_id, "total": total})
            raise PermissionError("payment not approved")

        order = await self.repo.save_order(
            user_id=user_id,
            items=items,
            total=total,
            payment_id=auth["payment_id"],
        )

        await self.audit.track("order_created", {"order_id": order["id"], "total": total})
        return order
