#!/usr/bin/env python3
"""Run the isolated rosbag player and fail closed on incomplete playback evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid


COUNTERS = (
    "read_count", "enqueue_success", "enqueue_failure", "pop_success",
    "pop_failure", "publish_success", "publish_failure", "control_changes",
)
FLAGS = ("reader_eof", "reader_thread_finished", "queue_drained",
         "interrupted", "runtime_error")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def bag_fingerprint(bag):
    bag = bag.resolve(strict=True)
    if not bag.is_dir() or not (bag / "metadata.yaml").is_file():
        raise ValueError("bag must be a directory containing metadata.yaml")
    files = []
    for path in sorted(bag.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"bag contains a symlink: {path}")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            files.append({"relative_path": path.relative_to(bag).as_posix(),
                          "sha256": digest.hexdigest(), "size": path.stat().st_size})
    if not any(item["relative_path"].endswith(
            (".db3", ".mcap", ".db3.zstd", ".mcap.zstd")) for item in files):
        raise ValueError("bag has no recognized data file")
    raw = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"realpath": str(bag), "files": files,
            "aggregate_sha256": hashlib.sha256(raw).hexdigest()}


def load_json(path):
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"evidence missing or unreadable: {exc}") from exc


def classify(evidence, expected, exit_code, sent_signal=None):
    if sent_signal is not None:
        return "interrupted", f"supervisor sent signal {sent_signal}"
    if not isinstance(evidence, dict):
        return "unknown", "evidence is not a JSON object"
    required = {"schema_version", "run_id", "bag_path", "bag_fingerprint",
                "rate", "start_offset", "loop", "topics", "errors",
                "internal_result", *FLAGS, *COUNTERS}
    missing = sorted(required - evidence.keys())
    if missing:
        return "unknown", "missing evidence fields: " + ", ".join(missing)
    if evidence["schema_version"] != 1:
        return "unknown", "unsupported evidence schema"
    for key in FLAGS:
        if type(evidence[key]) is not bool:
            return "unknown", f"invalid boolean field: {key}"
    for key in COUNTERS:
        if type(evidence[key]) is not int or evidence[key] < 0:
            return "unknown", f"invalid counter: {key}"
    if not isinstance(evidence["errors"], list) or not all(
            isinstance(error, str) for error in evidence["errors"]):
        return "unknown", "invalid error list"
    if evidence["run_id"] != expected["run_id"]:
        return "unknown", "run_id mismatch"
    if (evidence["bag_path"] != expected["bag"]["realpath"] or
            evidence["bag_fingerprint"] != expected["bag"]["aggregate_sha256"]):
        return "unknown", "bag identity mismatch"
    params = expected["playback"]
    if (type(evidence["rate"]) not in (int, float) or
            type(evidence["start_offset"]) not in (int, float) or
            not math.isfinite(evidence["rate"]) or
            not math.isfinite(evidence["start_offset"]) or
            evidence["rate"] != params["rate"] or
            evidence["start_offset"] != params["start_offset"] or
            evidence["topics"] != params["topics"] or
            evidence["loop"] is not False):
        return "unknown", "playback parameter mismatch"
    if evidence["interrupted"]:
        return "interrupted", "player recorded interruption or context shutdown"
    if evidence["runtime_error"] or evidence["errors"]:
        return "error", "player recorded an error"
    if exit_code is None or exit_code < 0:
        return "error", "player terminated by a signal or exit status unavailable"
    if evidence["enqueue_failure"] or evidence["pop_failure"] or evidence["publish_failure"]:
        return "error", "message enqueue, pop, or publish failed"
    count = evidence["read_count"]
    if not (count > 0 and count == evidence["enqueue_success"] ==
            evidence["pop_success"] == evidence["publish_success"]):
        return "error", "queue and publish counters disagree"
    if evidence["control_changes"]:
        return "error", "playback controls changed during run"
    if (evidence["reader_eof"] and evidence["reader_thread_finished"] and
            not evidence["queue_drained"] and
            evidence["internal_result"] == "reader_eof_queue_pending"):
        return "reader_eof_queue_pending", "reader EOF but playback queue not drained"
    if exit_code != 0:
        return "error", f"player exited with status {exit_code}"
    if not (evidence["reader_eof"] and evidence["reader_thread_finished"] and
            evidence["queue_drained"] and evidence["internal_result"] == "natural_end"):
        return "unknown", "natural completion evidence is incomplete or contradictory"
    return "natural_end", "reader EOF, task finished, queue drained, publish counts agree, exit 0"


def verify_completion_file(path):
    path = Path(path)
    completion = load_json(path)
    if not isinstance(completion, dict):
        return "unknown", "completion file is not an object"
    try:
        expected = {key: completion[key] for key in ("run_id", "bag", "playback")}
        evidence = completion["playback_evidence"]
        process = completion["process"]
        if completion["run_id"] != path.parent.name:
            return "unknown", "completion file is in the wrong run directory"
        if completion["bag"] != completion["bag_after"]:
            return "error", "bag changed during playback"
        if completion["bag"] != bag_fingerprint(Path(completion["bag"]["realpath"])):
            return "error", "current bag fingerprint differs from recorded bag"
        result, reason = classify(evidence, expected, process["exit_code"],
                                  process["sent_signal"])
        if result != completion["final_result"]:
            return "unknown", "stored final_result contradicts evidence"
        return result, reason
    except (KeyError, TypeError, OSError, ValueError):
        return "unknown", "completion file missing required fields"


def wait_child(proc, timeout):
    sent_signal = None
    try:
        return proc.wait(timeout=timeout), sent_signal
    except KeyboardInterrupt:
        sent_signal = "SIGINT"
        sig = signal.SIGINT
    except subprocess.TimeoutExpired:
        sent_signal = "SIGTERM_TIMEOUT"
        sig = signal.SIGTERM
    os.killpg(proc.pid, sig)
    try:
        return proc.wait(timeout=5), sent_signal
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        return proc.wait(), sent_signal + "_SIGKILL"


def run(args):
    bag_before = bag_fingerprint(Path(args.bag))
    run_id = uuid.uuid4().hex
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / run_id
    run_dir.mkdir(exist_ok=False)
    evidence_path = run_dir / "player_evidence.json"
    playback = {"rate": args.rate, "start_offset": args.start_offset,
                "loop": False, "topics": args.topic}
    record = {"schema_version": 1, "run_id": run_id, "bag": bag_before,
              "playback": playback, "player_path": str(Path(args.player).resolve()),
              "started_at_utc": utc_now(), "run_dir": str(run_dir)}
    command = [str(Path(args.player).resolve()), "--bag", bag_before["realpath"],
               "--run-id", run_id, "--fingerprint", bag_before["aggregate_sha256"],
               "--evidence", str(evidence_path), "--rate", repr(args.rate),
               "--start-offset", repr(args.start_offset)]
    for topic in args.topic:
        command += ["--topic", topic]
    record["player_command"] = command
    child_env = os.environ.copy()
    child_env.pop("ROSBAG_EVIDENCE_TEST_FAULT", None)
    ros_log_dir = run_dir / "ros_log"
    ros_log_dir.mkdir(exist_ok=False)
    child_env["ROS_LOG_DIR"] = str(ros_log_dir)
    if args.test_fault:
        child_env["ROSBAG_EVIDENCE_TEST_FAULT"] = args.test_fault
    record["test_fault"] = args.test_fault
    exit_code = None
    sent_signal = None
    launch_error = None
    with (run_dir / "bag.log").open("x", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True, env=child_env)
            record["player_pid"] = proc.pid
            exit_code, sent_signal = wait_child(proc, args.timeout)
        except OSError as exc:
            launch_error = str(exc)
    record["ended_at_utc"] = utc_now()
    record["process"] = {"exit_code": exit_code,
                         "signal": -exit_code if exit_code is not None and exit_code < 0 else None,
                         "sent_signal": sent_signal}
    try:
        record["bag_after"] = bag_fingerprint(Path(args.bag))
    except (OSError, ValueError) as exc:
        record["bag_after"] = None
        launch_error = f"post-run bag fingerprint failed: {exc}"
    try:
        evidence = load_json(evidence_path)
    except ValueError as exc:
        evidence = None
        launch_error = str(exc) if launch_error is None else launch_error + "; " + str(exc)
    record["playback_evidence"] = evidence
    if sent_signal is not None:
        result = "interrupted"
        reason = f"supervisor sent {sent_signal}; " + (launch_error or "player stopped")
    elif exit_code is not None and exit_code < 0:
        result = "error"
        reason = f"player terminated by signal {-exit_code}; " + (launch_error or "")
    elif launch_error:
        result, reason = "unknown", launch_error
    elif record["bag"] != record["bag_after"]:
        result, reason = "error", "bag contents changed during playback"
    else:
        result, reason = classify(evidence, record, exit_code, sent_signal)
    record["final_result"] = result
    record["reason"] = reason
    completion = run_dir / "completion.json"
    with completion.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    print(f"{result}: {reason}\n{completion}")
    return 0 if result == "natural_end" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--test-fault", choices=("read", "publish", "race_interrupt"))
    args = parser.parse_args(argv)
    if (not math.isfinite(args.rate) or args.rate <= 0 or
            not math.isfinite(args.start_offset) or args.start_offset < 0 or
            args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0)):
        parser.error("invalid playback rate, offset, or timeout")
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
