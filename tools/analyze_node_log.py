#!/usr/bin/env python3
"""Summarize Point-LIO's per-frame console timings without claiming bag completion.

The pattern follows the printf in src/laserMapping.cpp.  This installation of
ros2 bag play has no verified, unique normal-completion line, so a node log on
its own cannot establish that playback finished normally.
"""

import argparse
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
import statistics
import sys


MARKER = "[ mapping ]: time:"
# printf uses %0.6f for every field.  Match all labels in order, including the
# cumulative fields, so a truncated or reordered line cannot become a sample.
PERFORMANCE_LINE = re.compile(
    r"\[ mapping \]: time: IMU \+ Map \+ Input Downsample: (?P<imu>\S+)"
    r"\s+ave match: (?P<ave_match>\S+)"
    r"\s+ave solve: (?P<ave_solve>\S+)"
    r"\s+ave ICP: (?P<icp>\S+)"
    r"\s+map incre: (?P<map_incre>\S+)"
    r"\s+ave total: (?P<ave_total>\S+)"
    r"\s+icp: (?P<ave_update>\S+)"
    r"\s+propogate: (?P<ave_propagate>\S+)"
)
FINITE_PRINTF_NUMBER = re.compile(r"[0-9]+\.[0-9]{6}\Z")
SINGLE_FRAME_FIELDS = (
    ("IMU + Map + Input Downsample", "imu"),
    ("ave ICP", "icp"),
    ("map incre", "map_incre"),
)


@dataclass
class Analysis:
    candidate_lines: int = 0
    complete_lines: int = 0
    malformed_lines: int = 0
    invalid_number_lines: int = 0
    valid_before_warmup: int = 0
    warmup_removed: int = 0
    samples: dict = field(default_factory=lambda: {key: [] for _, key in SINGLE_FRAME_FIELDS})

    @property
    def abnormal_lines(self):
        return self.malformed_lines + self.invalid_number_lines

    @property
    def sample_count(self):
        return len(self.samples["imu"])

    @property
    def post_warmup_complete_lines(self):
        return self.complete_lines - self.warmup_removed

    @property
    def bag_completion(self):
        # There is no verified completion marker to match in node.log.  In
        # Humble, ros2bag/verb/play.py also catches KeyboardInterrupt, so an
        # apparent clean command exit would not prove natural playback end.
        return "无法确认正常结束"


def parse_candidate(line):
    """Return (complete, values); values is None for invalid numeric fields."""
    start = line.find(MARKER)
    if start < 0:
        return None
    match = PERFORMANCE_LINE.fullmatch(line[start:].strip())
    if match is None:
        return False, None

    values = {}
    for name, token in match.groupdict().items():
        if FINITE_PRINTF_NUMBER.fullmatch(token) is None:
            return True, None
        value = float(token)
        if not math.isfinite(value) or value < 0:
            return True, None
        values[name] = value
    return True, values


def analyze_lines(lines, warmup):
    result = Analysis()
    for line in lines:
        parsed = parse_candidate(line)
        if parsed is None:
            continue
        result.candidate_lines += 1
        complete, values = parsed
        if not complete:
            result.malformed_lines += 1
            continue
        result.complete_lines += 1
        if result.complete_lines <= warmup:
            result.warmup_removed += 1
        if values is None:
            result.invalid_number_lines += 1
            continue
        result.valid_before_warmup += 1
        if result.complete_lines <= warmup:
            continue
        for _, key in SINGLE_FRAME_FIELDS:
            result.samples[key].append(values[key])
    return result


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    return (
        statistics.mean(ordered),
        statistics.median(ordered),
        ordered[math.ceil(0.95 * n) - 1],
        ordered[-1],
    )


def render_report(path, result, warmup, min_samples):
    enough = result.sample_count >= min_samples and all(
        result.samples[key] for _, key in SINGLE_FRAME_FIELDS
    )
    lines = [
        f"日志: {path}",
        f"原始匹配行数（含异常）: {result.candidate_lines}",
        f"格式完整行数: {result.complete_lines}",
        f"预热前数值有效行数: {result.valid_before_warmup}",
        f"预热排除: {result.warmup_removed} / 请求 {warmup} 条格式完整行",
        f"预热后格式完整行数: {result.post_warmup_complete_lines}",
        f"预热后有效样本数: {result.sample_count}",
        f"异常行数: {result.abnormal_lines} "
        f"（缺字段或格式错误 {result.malformed_lines}，数值无效 {result.invalid_number_lines}）",
        f"样本检查: {'通过' if enough else '不通过'}（每个字段至少 {min_samples} 条有效样本）",
        f"rosbag 正常结束: {result.bag_completion}",
        "正式基线: 否（node.log 缺少经验证的 rosbag 自然播放结束证据）",
        "字段 | 原始匹配行数 | 有效样本数 | 均值(ms) | 中位数(ms) | P95(ms) | 最大值(ms) | 异常行数",
    ]
    for label, key in SINGLE_FRAME_FIELDS:
        stats = summarize(result.samples[key])
        displayed = ["—"] * 4 if stats is None else [f"{value * 1000:.3f}" for value in stats]
        lines.append(
            f"{label} | {result.candidate_lines} | {len(result.samples[key])} | "
            f"{' | '.join(displayed)} | {result.abnormal_lines}"
        )
    lines.append("注: ave total 是累计均值，未作为单帧样本；异常行对三个字段一律整行剔除。")
    return "\n".join(lines), enough


def nonnegative_int(value):
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须为非负整数")
    return parsed


def positive_int(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须为正整数")
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("node_log", type=Path, help="Point-LIO 节点控制台日志")
    parser.add_argument("--warmup", type=nonnegative_int, default=20, help="排除最先的格式完整性能行，默认 20")
    parser.add_argument("--min-samples", type=positive_int, default=30, help="预热后每字段最小有效样本数，默认 30")
    args = parser.parse_args(argv)

    if not args.node_log.is_file():
        parser.error(f"文件不存在或不是普通文件: {args.node_log}")
    try:
        with args.node_log.open("r", encoding="utf-8", errors="replace") as stream:
            result = analyze_lines(stream, args.warmup)
    except OSError as exc:
        parser.error(f"无法读取文件: {exc}")

    report, enough = render_report(args.node_log, result, args.warmup, args.min_samples)
    print(report)
    if not enough:
        return 1
    # Statistics are available, but normal rosbag completion is unproven.
    return 2


if __name__ == "__main__":
    sys.exit(main())
