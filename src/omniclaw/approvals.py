"""Owner approval broker: pauses risky tool calls until the owner answers YES or NO."""

import asyncio

from omniclaw.models import Notify

YES = {"yes", "y", "approve", "approved", "ok", "okay", "confirm", "send it", "do it"}
NO = {"no", "n", "reject", "rejected", "cancel", "stop", "don't", "dont"}


class ApprovalBroker:
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout = timeout_seconds
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def has_pending(self, key: str) -> bool:
        future = self._pending.get(key)
        return future is not None and not future.done()

    async def request(self, key: str, notify: Notify, description: str) -> bool:
        if self.has_pending(key):
            return False
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        try:
            await notify(
                f"Approval needed:\n{description}\n\nReply YES to approve or NO to reject."
            )
            return await asyncio.wait_for(future, timeout=self._timeout)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(key, None)

    def resolve(self, key: str, text: str) -> str | None:
        """Consume a message if an approval is pending. Returns an acknowledgement or None."""
        future = self._pending.get(key)
        if future is None or future.done():
            return None
        answer = text.strip().lower().rstrip(".!")
        if answer in YES:
            future.set_result(True)
            return "Approved."
        if answer in NO:
            future.set_result(False)
            return "Rejected."
        return "An action is waiting for your decision. Reply YES or NO."
