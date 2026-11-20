import asyncio
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from contract import CommandError, validate_operation, COMMANDS
from link_faults import FrameQueue, LinkFaults, QUEUE_LIMIT
from network_control import NetworkControl


class IsolatedLinkTest(unittest.IsolatedAsyncioTestCase):
    async def test_socket_lease_restores_forwarding(self):
        faults = LinkFaults()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "control"
            private.mkdir(mode=0o700)
            endpoint = private / "link.sock"
            async with await faults.listen(endpoint):
                client = NetworkControl(endpoint, root)
                inspect = await asyncio.to_thread(client.execute, "network.profile.get", {})
                self.assertEqual(inspect["generation"], 0)
                applied = await asyncio.to_thread(client.execute, "network.profile.set", {"offline": True, "seconds": 1})
                counts = Counter()
                for direction in (0, 1):
                    queue = FrameQueue(faults, direction, counts)
                    queue.push(b"h", b"f")
                    self.assertTrue(queue.queue.empty())
                await asyncio.wait_for(faults.changed.wait(), 2)
                restored = await asyncio.to_thread(client.execute, "network.profile.get", {})
                self.assertGreater(restored["generation"], applied["generation"])
                self.assertFalse(restored["profile"]["offline"])
                self.assertEqual(counts["fault_drop"], 2)
                queue.push(b"h", b"recovered")
                self.assertEqual(await queue.next(), (b"h", b"recovered"))
                with self.assertRaises(CommandError):
                    await asyncio.to_thread(client.execute, "network.profile.set", {"offline": 1})

    async def test_delay_rate_and_reset_flush(self):
        faults = LinkFaults()
        counts = Counter()
        queue = FrameQueue(faults, 0, counts)
        faults.apply({"delay_ms": 15, "rate_kbit": 100})
        started = faults.loop.time()
        queue.push(b"h", b"p" * 1000)
        self.assertEqual(await queue.next(), (b"h", b"p" * 1000))
        self.assertGreaterEqual(faults.loop.time() - started, .09)
        faults.apply({"delay_ms": 5000})
        queue.push(b"h", b"stale")
        receive = asyncio.create_task(queue.next())
        await asyncio.sleep(0)
        faults.reset()
        queue.push(b"h", b"new")
        self.assertEqual(await asyncio.wait_for(receive, 1), (b"h", b"new"))
        self.assertEqual(counts["fault_flushed"], 1)

    async def test_bounds_and_repeatable_loss(self):
        faults = LinkFaults()
        counts = Counter()
        queue = FrameQueue(faults, 0, counts)
        for _ in range(QUEUE_LIMIT + 1):
            queue.push(b"h", b"p")
        self.assertEqual(counts["fault_queue_full"], 1)
        results = []
        for _ in range(2):
            faults.apply({"loss_percent": 30, "seed": 9})
            sample = Counter()
            q = FrameQueue(faults, 1, sample)
            for item in range(90):
                q.push(b"h", bytes([item]))
            results.append([await q.next() for _ in range(q.queue.qsize())])
            self.assertGreater(sample["fault_drop"], 10)
            self.assertLess(sample["fault_drop"], 45)
        self.assertEqual(*results)
        faults.reset()

    async def test_local_and_remote_inputs_are_scoped(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                NetworkControl(root / "any.sock", root)
        for parameters in ({"device": "eth0"}, {"seconds": 181}, {"loss_percent": True}, {"delay_ms": -1}):
            with self.assertRaises(CommandError):
                validate_operation({"command": "network.profile.set", "params": parameters}, COMMANDS)
