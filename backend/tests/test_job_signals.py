import asyncio
import unittest

from core import job_signals


class JobSignalTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_notification_wakes_all_matching_subscribers(self):
        async with job_signals.subscribe("a") as first, job_signals.subscribe("a") as second, \
                job_signals.subscribe("b") as other, job_signals.subscribe() as scheduler:
            await asyncio.to_thread(job_signals.notify, "a")
            self.assertEqual([True, True, True], await asyncio.gather(
                first.wait(0.3), second.wait(0.3), scheduler.wait(0.3)))
            self.assertFalse(await other.wait(0.01))

    async def test_commit_between_read_and_wait_is_not_lost(self):
        async with job_signals.subscribe("a") as signal:
            signal.clear()
            job_signals.notify("a")
            self.assertTrue(await signal.wait(0.3))
            signal.clear()
            self.assertFalse(await signal.wait(0.01))

    async def test_broadcast_and_subscriber_cleanup(self):
        before = len(job_signals._subscribers)
        async with job_signals.subscribe("a") as first, job_signals.subscribe("b") as second:
            job_signals.notify()
            self.assertTrue(await first.wait(0.3))
            self.assertTrue(await second.wait(0.3))
        self.assertEqual(before, len(job_signals._subscribers))

    async def test_cancelled_wait_removes_subscriber(self):
        ready = asyncio.Event()
        before = len(job_signals._subscribers)

        async def listen():
            async with job_signals.subscribe("a") as signal:
                ready.set()
                await signal.wait(30)

        task = asyncio.create_task(listen())
        await ready.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(before, len(job_signals._subscribers))
