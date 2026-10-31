#!/usr/bin/env python3
"""Unit and small-bag integration tests. Run after sourcing ROS and overlay."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import unittest
import uuid

import supervisor


ROOT = Path(__file__).resolve().parent
PLAYER = Path(os.environ.get(
    "VERIFIED_ROSBAG_PLAYER",
    ROOT / "install/rosbag2_transport/lib/rosbag2_transport/verified_rosbag_play"))
ARTIFACTS = Path(os.environ.get(
    "ROSBAG_TEST_ARTIFACTS_ROOT", ROOT / "test_artifacts")) / uuid.uuid4().hex


def good_fixture():
    expected = {
        "run_id": "a1",
        "bag": {"realpath": "/tmp/test_bag", "aggregate_sha256": "f" * 64},
        "playback": {"rate": 1.0, "start_offset": 0.0, "loop": False, "topics": []},
    }
    state = {
        "schema_version": 1, "run_id": "a1", "bag_path": "/tmp/test_bag",
        "bag_fingerprint": "f" * 64, "rate": 1.0, "start_offset": 0.0,
        "loop": False, "topics": [], "reader_eof": True,
        "reader_thread_finished": True, "queue_drained": True,
        "interrupted": False, "runtime_error": False, "read_count": 3,
        "enqueue_success": 3, "enqueue_failure": 0, "pop_success": 3,
        "pop_failure": 0, "publish_success": 3, "publish_failure": 0,
        "control_changes": 0, "errors": [], "internal_result": "natural_end",
    }
    return expected, state


def create_bag(path, spacing_ns):
    import rosbag2_py
    from rclpy.serialization import serialize_message
    from std_msgs.msg import String

    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="sqlite3"),
                rosbag2_py.ConverterOptions(
                    input_serialization_format="cdr", output_serialization_format="cdr"))
    writer.create_topic(rosbag2_py.TopicMetadata(
        name="/evidence_test", type="std_msgs/msg/String", serialization_format="cdr"))
    initial = 1_000_000_000
    for index in range(3):
        writer.write("/evidence_test", serialize_message(String(data=str(index))),
                     initial + index * spacing_ns)
    del writer


def run_supervisor(bag, output_root, fault=None, timeout=30):
    command = [sys.executable, str(ROOT / "supervisor.py"), "--bag", str(bag),
               "--player", str(PLAYER), "--output-root", str(output_root),
               "--timeout", str(timeout)]
    if fault:
        command += ["--test-fault", fault]
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 10)
    completions = list(output_root.glob("*/completion.json"))
    if len(completions) != 1:
        raise AssertionError(f"expected one completion, found {completions}: {process.stderr}")
    return process, json.loads(completions[0].read_text()), completions[0]


class ValidationTests(unittest.TestCase):
    def test_valid(self):
        expected, state = good_fixture()
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "natural_end")

    def test_missing_and_corrupt_completion(self):
        folder = ARTIFACTS / "invalid_json"
        folder.mkdir(parents=True)
        with self.assertRaises(ValueError):
            supervisor.verify_completion_file(folder / "missing.json")
        corrupt = folder / "corrupt.json"
        corrupt.write_text("{bad")
        with self.assertRaises(ValueError):
            supervisor.verify_completion_file(corrupt)

    def test_missing_field_and_identity(self):
        expected, state = good_fixture()
        del state["queue_drained"]
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "unknown")
        _, state = good_fixture()
        state["run_id"] = "other"
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "unknown")
        _, state = good_fixture()
        state["bag_fingerprint"] = "0" * 64
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "unknown")

    def test_counts_and_exit(self):
        expected, state = good_fixture()
        state["pop_success"] = 2
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "error")
        _, state = good_fixture()
        self.assertEqual(supervisor.classify(state, expected, -9)[0], "error")

    def test_eof_pending(self):
        expected, state = good_fixture()
        state["queue_drained"] = False
        state["internal_result"] = "reader_eof_queue_pending"
        self.assertEqual(supervisor.classify(state, expected, 2)[0],
                         "reader_eof_queue_pending")

    def test_race_failure_is_monotonic(self):
        expected, state = good_fixture()
        state["interrupted"] = True
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "interrupted")
        state["interrupted"] = False
        state["errors"] = ["reader failure"]
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "error")
        state["errors"] = []
        self.assertEqual(supervisor.classify(state, expected, 0, "SIGINT")[0], "interrupted")

    def test_unsupported_options(self):
        for option in ("--loop", "--seek", "--start-paused"):
            result = subprocess.run([str(PLAYER), option],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported", result.stderr)
        expected, state = good_fixture()
        state["control_changes"] = 1
        self.assertEqual(supervisor.classify(state, expected, 0)[0], "error")


class PlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PLAYER.is_file():
            raise RuntimeError("build verified_rosbag_play before running integration tests")
        ARTIFACTS.mkdir(parents=True, exist_ok=False)
        cls.short_bag = ARTIFACTS / "short_bag"
        cls.long_bag = ARTIFACTS / "long_bag"
        create_bag(cls.short_bag, 100_000_000)
        create_bag(cls.long_bag, 10_000_000_000)

    def test_natural_end(self):
        process, result, path = run_supervisor(
            self.short_bag, ARTIFACTS / "natural")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["final_result"], "natural_end")
        self.assertEqual(supervisor.verify_completion_file(path)[0], "natural_end")

    def test_completion_tamper_rejected(self):
        _, result, path = run_supervisor(
            self.short_bag, ARTIFACTS / "tamper_source")
        tampered = dict(result)
        tampered["run_id"] = "wrong"
        copy = path.parent / "tampered.json"
        copy.write_text(json.dumps(tampered))
        self.assertNotEqual(supervisor.verify_completion_file(copy)[0], "natural_end")
        tampered = json.loads(path.read_text())
        tampered["bag"]["aggregate_sha256"] = "0" * 64
        copy2 = path.parent / "tampered_bag.json"
        copy2.write_text(json.dumps(tampered))
        self.assertNotEqual(supervisor.verify_completion_file(copy2)[0], "natural_end")

    def test_read_failure(self):
        process, result, _ = run_supervisor(
            self.short_bag, ARTIFACTS / "reader_error", "read")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["final_result"], "error")

    def test_publish_failure(self):
        process, result, _ = run_supervisor(
            self.short_bag, ARTIFACTS / "publish_error", "publish")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["final_result"], "error")
        self.assertGreater(result["playback_evidence"]["publish_failure"], 0)

    def test_concurrent_eof_and_interrupt(self):
        for index in range(3):
            process, result, _ = run_supervisor(
                self.short_bag, ARTIFACTS / f"race_{index}", "race_interrupt")
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(result["final_result"], "interrupted")
            self.assertTrue(result["playback_evidence"]["reader_eof"])

    def test_abnormal_child_exit(self):
        fake = ARTIFACTS / "crash_player.py"
        fake.write_text(
            "#!/usr/bin/env python3\nimport os, signal\n"
            "os.kill(os.getpid(), signal.SIGKILL)\n")
        fake.chmod(0o755)
        output_root = ARTIFACTS / "crash"
        command = [sys.executable, str(ROOT / "supervisor.py"), "--bag",
                   str(self.short_bag), "--player", str(fake),
                   "--output-root", str(output_root)]
        process = subprocess.run(command, capture_output=True, text=True, timeout=10)
        result = json.loads(next(output_root.glob("*/completion.json")).read_text())
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["final_result"], "error")
        self.assertEqual(result["process"]["signal"], signal.SIGKILL)

    def test_ctrl_c_during_playback(self):
        output_root = ARTIFACTS / "ctrl_c"
        command = [sys.executable, str(ROOT / "supervisor.py"),
                   "--bag", str(self.long_bag), "--player", str(PLAYER),
                   "--output-root", str(output_root), "--timeout", "30"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            logs = list(output_root.glob("*/bag.log"))
            if logs and "ROSBAG_EVIDENCE_READER_EOF" in logs[0].read_text():
                break
            time.sleep(0.05)
        else:
            process.kill()
            raise AssertionError("reader EOF diagnostic did not appear")
        # Reader EOF is already seen, but the second message is scheduled 10 seconds later.
        os.kill(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
        paths = list(output_root.glob("*/completion.json"))
        self.assertEqual(len(paths), 1, stderr)
        result = json.loads(paths[0].read_text())
        self.assertNotEqual(result["final_result"], "natural_end", stdout)
        self.assertEqual(result["final_result"], "interrupted")
        bag_log = (paths[0].parent / "bag.log").read_text()
        counts = re.findall(
            r"ROSBAG_EVIDENCE_READER_EOF enqueued=(\d+) popped=(\d+)", bag_log)
        self.assertTrue(counts, bag_log)
        self.assertTrue(any(int(enqueued) > int(popped)
                            for enqueued, popped in counts), bag_log)
        if result["playback_evidence"] is not None:
            self.assertTrue(result["playback_evidence"]["reader_eof"])
            self.assertFalse(result["playback_evidence"]["queue_drained"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
