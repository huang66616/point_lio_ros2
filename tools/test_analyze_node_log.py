"""Small standard-library tests for analyze_node_log.py."""

from contextlib import redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import patch

from analyze_node_log import analyze_lines, main, parse_candidate, render_report, summarize


def performance_line(imu="0.001000", icp="0.002000", map_incre="0.003000"):
    return (
        "[pointlio_mapping-1] [ mapping ]: time: "
        f"IMU + Map + Input Downsample: {imu} "
        "ave match: 0.000000 ave solve: 0.000000  "
        f"ave ICP: {icp}  map incre: {map_incre} "
        "ave total: 0.006000 icp: 0.000000 propogate: 0.000000 \n"
    )


class AnalyzeNodeLogTests(unittest.TestCase):
    def test_normal_line_and_all_three_fields(self):
        complete, values = parse_candidate(performance_line())
        self.assertTrue(complete)
        self.assertEqual((values["imu"], values["icp"], values["map_incre"]), (0.001, 0.002, 0.003))

    def test_missing_field_is_malformed(self):
        line = performance_line().replace("  map incre: 0.003000", "")
        self.assertEqual(parse_candidate(line), (False, None))

    def test_invalid_numbers_exclude_entire_line(self):
        for token in ("-0.001000", "NaN", "Infinity", "1e309", "0.1"):
            with self.subTest(token=token):
                result = analyze_lines([performance_line(icp=token)], warmup=0)
                self.assertEqual(result.sample_count, 0)
                self.assertEqual(result.invalid_number_lines, 1)

    def test_invalid_cumulative_field_also_excludes_entire_line(self):
        line = performance_line().replace("ave total: 0.006000", "ave total: Infinity")
        result = analyze_lines([line], warmup=0)
        self.assertEqual(result.sample_count, 0)
        self.assertEqual(result.invalid_number_lines, 1)

    def test_warmup_uses_complete_lines_including_invalid_numbers(self):
        lines = [performance_line() for _ in range(19)]
        lines.append(performance_line(imu="NaN"))
        lines.append(performance_line(imu="0.009000"))
        result = analyze_lines(lines, warmup=20)
        self.assertEqual(result.warmup_removed, 20)
        self.assertEqual(result.sample_count, 1)
        self.assertEqual(result.samples["imu"], [0.009])
        self.assertEqual(result.abnormal_lines, 1)

    def test_p95_is_nearest_rank(self):
        self.assertEqual(summarize(list(range(1, 21)))[2], 19)

    def test_no_unverified_bag_success_from_log_text(self):
        result = analyze_lines([performance_line(), "Playback finished successfully\n"], warmup=0)
        report, enough = render_report("node.log", result, warmup=0, min_samples=1)
        self.assertTrue(enough)
        self.assertIn("无法确认正常结束", report)
        self.assertIn("正式基线: 否", report)

    def test_insufficient_samples(self):
        result = analyze_lines([performance_line()], warmup=1)
        report, enough = render_report("node.log", result, warmup=1, min_samples=1)
        self.assertFalse(enough)
        self.assertIn("样本检查: 不通过", report)

    def test_cli_exit_codes_and_sample_options(self):
        for sample_count, expected_code in ((1, 1), (2, 2)):
            with self.subTest(sample_count=sample_count):
                data = io.StringIO(performance_line() * sample_count)
                with patch("analyze_node_log.Path.is_file", return_value=True), \
                     patch("analyze_node_log.Path.open", return_value=data), \
                     redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["node.log", "--warmup", "0", "--min-samples", "2"]), expected_code)

    def test_cli_rejects_invalid_limits(self):
        for option, value in (("--warmup", "-1"), ("--min-samples", "0")):
            with self.subTest(option=option):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    main(["node.log", option, value])
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
