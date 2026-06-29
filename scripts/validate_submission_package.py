from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


EXPECTED_SCHEMA = "buglab.submission_package.v1"
DEFAULT_PACKAGE = Path(".buglab/submission/submission_results.json")


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _check(
    checks: list[dict[str, Any]],
    failures: list[str],
    name: str,
    ok: bool,
    detail: str,
) -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        failures.append(f"{name}: {detail}")


def _require_mapping(value: Any, name: str, checks: list[dict[str, Any]], failures: list[str]) -> dict[str, Any]:
    ok = isinstance(value, dict)
    _check(checks, failures, name, ok, "present" if ok else "missing or not an object")
    return value if isinstance(value, dict) else {}


def _validate_non_negative_ints(
    values: dict[str, Any],
    keys: list[str],
    checks: list[dict[str, Any]],
    failures: list[str],
    prefix: str,
) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for key in keys:
        raw = values.get(key)
        parsed_value = _as_int(raw)
        ok = parsed_value is not None and parsed_value >= 0
        _check(
            checks,
            failures,
            f"{prefix}.{key}",
            ok,
            f"value={raw!r}" if not ok else f"value={parsed_value}",
        )
        if ok and parsed_value is not None:
            parsed[key] = parsed_value
    return parsed


def validate_package(package: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    warnings: list[str] = []

    _check(
        checks,
        failures,
        "schema_version",
        package.get("schema_version") == EXPECTED_SCHEMA,
        f"expected={EXPECTED_SCHEMA!r} actual={package.get('schema_version')!r}",
    )
    _check(
        checks,
        failures,
        "updated_at_utc",
        isinstance(package.get("updated_at_utc"), str) and bool(package.get("updated_at_utc")),
        "package has generation timestamp",
    )

    submission_checks = _require_mapping(package.get("submission_checks"), "submission_checks", checks, failures)
    required_submission_checks = [
        "no_activity_proxy_claim",
        "oracle_scored_accuracy_only",
        "suspected_findings_marked_unverified",
        "duplicate_benchmark_cases_deduped",
        "stable_metrics_disclose_disagreements",
        "confidence_bounds_reported",
        "evidence_completeness_audited",
        "promotion_queue_reported",
        "promotion_triage_pack_reported",
        "real_repo_replay_verification_reported",
        "calibration_ledger_reported",
        "jsonl_truth_ledger_written",
    ]
    for key in required_submission_checks:
        _check(
            checks,
            failures,
            f"submission_checks.{key}",
            submission_checks.get(key) is True,
            f"value={submission_checks.get(key)!r}",
        )

    oracle_totals = _require_mapping(package.get("oracle_totals"), "oracle_totals", checks, failures)
    oracle_counts = _validate_non_negative_ints(
        oracle_totals,
        [
            "true_positive",
            "false_positive",
            "false_negative",
            "true_negative",
            "unique_cases",
            "stable_unique_cases",
            "unstable_cases",
            "stable_true_positive",
            "stable_false_positive",
            "stable_false_negative",
            "stable_true_negative",
            "precision_trials",
            "recall_trials",
            "stable_precision_trials",
            "stable_recall_trials",
            "case_results_seen",
            "accepted_case_results",
            "duplicate_case_results_removed",
            "rejected_case_results",
            "disagreements",
        ],
        checks,
        failures,
        "oracle_totals",
    )

    case_results_seen = oracle_counts.get("case_results_seen")
    accepted_case_results = oracle_counts.get("accepted_case_results")
    rejected_case_results = oracle_counts.get("rejected_case_results")
    if case_results_seen is not None and accepted_case_results is not None and rejected_case_results is not None:
        expected_seen = accepted_case_results + rejected_case_results
        _check(
            checks,
            failures,
            "oracle_totals.case_result_partition",
            case_results_seen == expected_seen,
            f"seen={case_results_seen} accepted+rejected={expected_seen}",
        )

    unique_cases = oracle_counts.get("unique_cases")
    duplicates_removed = oracle_counts.get("duplicate_case_results_removed")
    if accepted_case_results is not None and unique_cases is not None and duplicates_removed is not None:
        expected_duplicates = max(0, accepted_case_results - unique_cases)
        _check(
            checks,
            failures,
            "oracle_totals.duplicate_accounting",
            duplicates_removed == expected_duplicates,
            f"removed={duplicates_removed} expected={expected_duplicates}",
        )

    stable_unique_cases = oracle_counts.get("stable_unique_cases")
    unstable_cases = oracle_counts.get("unstable_cases")
    disagreements = oracle_counts.get("disagreements")
    if unique_cases is not None and stable_unique_cases is not None and unstable_cases is not None:
        _check(
            checks,
            failures,
            "oracle_totals.stable_case_partition",
            stable_unique_cases + unstable_cases == unique_cases,
            f"stable+unstable={stable_unique_cases + unstable_cases} unique={unique_cases}",
        )
    if unstable_cases is not None and disagreements is not None:
        _check(
            checks,
            failures,
            "oracle_totals.unstable_matches_disagreements",
            unstable_cases == disagreements,
            f"unstable={unstable_cases} disagreements={disagreements}",
        )

    true_positive = oracle_counts.get("true_positive")
    false_positive = oracle_counts.get("false_positive")
    false_negative = oracle_counts.get("false_negative")
    stable_true_positive = oracle_counts.get("stable_true_positive")
    stable_false_positive = oracle_counts.get("stable_false_positive")
    stable_false_negative = oracle_counts.get("stable_false_negative")
    precision_trials = oracle_counts.get("precision_trials")
    recall_trials = oracle_counts.get("recall_trials")
    stable_precision_trials = oracle_counts.get("stable_precision_trials")
    stable_recall_trials = oracle_counts.get("stable_recall_trials")
    if true_positive is not None and false_positive is not None and precision_trials is not None:
        _check(
            checks,
            failures,
            "oracle_totals.precision_trials",
            precision_trials == true_positive + false_positive,
            f"precision_trials={precision_trials} TP+FP={true_positive + false_positive}",
        )
    if true_positive is not None and false_negative is not None and recall_trials is not None:
        _check(
            checks,
            failures,
            "oracle_totals.recall_trials",
            recall_trials == true_positive + false_negative,
            f"recall_trials={recall_trials} TP+FN={true_positive + false_negative}",
        )
    if stable_true_positive is not None and stable_false_positive is not None and stable_precision_trials is not None:
        _check(
            checks,
            failures,
            "oracle_totals.stable_precision_trials",
            stable_precision_trials == stable_true_positive + stable_false_positive,
            f"stable_precision_trials={stable_precision_trials} stable_TP+FP={stable_true_positive + stable_false_positive}",
        )
    if stable_true_positive is not None and stable_false_negative is not None and stable_recall_trials is not None:
        _check(
            checks,
            failures,
            "oracle_totals.stable_recall_trials",
            stable_recall_trials == stable_true_positive + stable_false_negative,
            f"stable_recall_trials={stable_recall_trials} stable_TP+FN={stable_true_positive + stable_false_negative}",
        )

    if unique_cases and unique_cases > 0:
        for metric in ["precision", "recall", "f1", "precision_wilson_lower_95", "recall_wilson_lower_95"]:
            value = _as_float(oracle_totals.get(metric))
            _check(
                checks,
                failures,
                f"oracle_totals.{metric}",
                value is not None and 0 <= value <= 1,
                f"value={oracle_totals.get(metric)!r}",
            )
        for metric in [
            "stable_precision",
            "stable_recall",
            "stable_f1",
            "stable_precision_wilson_lower_95",
            "stable_recall_wilson_lower_95",
        ]:
            value = oracle_totals.get(metric)
            stable_metric_ok = value is None or (_as_float(value) is not None and 0 <= float(value) <= 1)
            _check(
                checks,
                failures,
                f"oracle_totals.{metric}",
                stable_metric_ok,
                f"value={value!r}",
            )
    else:
        for metric in [
            "precision",
            "recall",
            "f1",
            "precision_wilson_lower_95",
            "recall_wilson_lower_95",
            "stable_precision",
            "stable_recall",
            "stable_f1",
            "stable_precision_wilson_lower_95",
            "stable_recall_wilson_lower_95",
        ]:
            value = oracle_totals.get(metric)
            ok = value is None or (_as_float(value) is not None and 0 <= float(value) <= 1)
            _check(checks, failures, f"oracle_totals.{metric}", ok, f"value={value!r}")

    bound_pairs = [
        ("precision_wilson_lower_95", "precision"),
        ("recall_wilson_lower_95", "recall"),
        ("stable_precision_wilson_lower_95", "stable_precision"),
        ("stable_recall_wilson_lower_95", "stable_recall"),
    ]
    for bound_key, point_key in bound_pairs:
        bound = _as_float(oracle_totals.get(bound_key))
        point = _as_float(oracle_totals.get(point_key))
        if bound is not None and point is not None:
            _check(
                checks,
                failures,
                f"oracle_totals.{bound_key}_bounded_by_{point_key}",
                bound <= point,
                f"{bound_key}={bound} {point_key}={point}",
            )

    selected_cases = oracle_totals.get("selected_cases") or []
    stable_cases = oracle_totals.get("stable_cases") or []
    rejected_cases = oracle_totals.get("rejected_cases") or []
    _check(checks, failures, "oracle_totals.selected_cases_type", isinstance(selected_cases, list), "list expected")
    _check(checks, failures, "oracle_totals.stable_cases_type", isinstance(stable_cases, list), "list expected")
    _check(checks, failures, "oracle_totals.rejected_cases_type", isinstance(rejected_cases, list), "list expected")

    if isinstance(selected_cases, list):
        for index, item in enumerate(selected_cases):
            if not isinstance(item, dict):
                _check(checks, failures, f"selected_cases[{index}]", False, "not an object")
                continue
            case_name = item.get("case")
            _check(
                checks,
                failures,
                f"selected_cases[{index}].case",
                isinstance(case_name, str) and bool(case_name),
                f"value={case_name!r}",
            )
            _check(
                checks,
                failures,
                f"selected_cases[{index}].differential_oracle_valid",
                item.get("differential_oracle_valid") is True,
                f"value={item.get('differential_oracle_valid')!r}",
            )

    if isinstance(rejected_cases, list):
        for index, item in enumerate(rejected_cases):
            if not isinstance(item, dict):
                _check(checks, failures, f"rejected_cases[{index}]", False, "not an object")
                continue
            _check(
                checks,
                failures,
                f"rejected_cases[{index}].differential_oracle_valid",
                item.get("differential_oracle_valid") is not True,
                f"value={item.get('differential_oracle_valid')!r}",
            )
            if not item.get("oracle_issue"):
                warnings.append(f"rejected_cases[{index}] is missing oracle_issue")

    marked_evidence = _require_mapping(package.get("marked_evidence"), "marked_evidence", checks, failures)
    marked_counts = _validate_non_negative_ints(
        marked_evidence,
        [
            "ledgers",
            "entries",
            "confirmed",
            "suspected",
            "fixed",
            "false_positive",
            "false_negative",
            "invalid_oracle",
            "scored_ledgers",
            "unverified_ledgers",
            "benchmark_derived_ledgers",
        ],
        checks,
        failures,
        "marked_evidence",
    )

    evidence_completeness = _require_mapping(package.get("evidence_completeness"), "evidence_completeness", checks, failures)
    evidence_counts = _validate_non_negative_ints(
        evidence_completeness,
        [
            "ledgers",
            "entries",
            "complete_entries",
            "incomplete_entries",
            "missing_identity",
            "missing_claim",
            "missing_status",
            "missing_outcome",
            "missing_evidence",
            "missing_reproduction",
            "missing_observation",
        ],
        checks,
        failures,
        "evidence_completeness",
    )
    evidence_entries = evidence_counts.get("entries")
    evidence_complete = evidence_counts.get("complete_entries")
    evidence_incomplete = evidence_counts.get("incomplete_entries")
    if evidence_entries is not None and evidence_complete is not None and evidence_incomplete is not None:
        _check(
            checks,
            failures,
            "evidence_completeness.entry_partition",
            evidence_complete + evidence_incomplete == evidence_entries,
            f"complete+incomplete={evidence_complete + evidence_incomplete} entries={evidence_entries}",
        )
    completion_rate = evidence_completeness.get("completion_rate")
    completion_rate_ok = completion_rate is None or (_as_float(completion_rate) is not None and 0 <= float(completion_rate) <= 1)
    _check(
        checks,
        failures,
        "evidence_completeness.completion_rate",
        completion_rate_ok,
        f"value={completion_rate!r}",
    )
    sample_incomplete = evidence_completeness.get("sample_incomplete", [])
    _check(
        checks,
        failures,
        "evidence_completeness.sample_incomplete_type",
        isinstance(sample_incomplete, list),
        "list expected",
    )

    real_repo_replay = _require_mapping(package.get("real_repo_replay"), "real_repo_replay", checks, failures)
    replay_counts = _validate_non_negative_ints(
        real_repo_replay,
        [
            "reports",
            "checked",
            "reproduced",
            "partially_reproduced",
            "not_reproduced",
            "unsupported",
            "error",
            "command_replay",
            "static_signal_replay",
            "unsupported_signals",
        ],
        checks,
        failures,
        "real_repo_replay",
    )
    replay_checked = replay_counts.get("checked")
    if replay_checked is not None:
        replay_terminal = sum(
            replay_counts.get(key, 0)
            for key in ["reproduced", "partially_reproduced", "not_reproduced", "unsupported", "error"]
        )
        _check(
            checks,
            failures,
            "real_repo_replay.verdict_partition",
            replay_terminal == replay_checked,
            f"verdicts={replay_terminal} checked={replay_checked}",
        )
    replay_rate = real_repo_replay.get("replay_reproduction_rate")
    replay_rate_ok = replay_rate is None or (_as_float(replay_rate) is not None and 0 <= float(replay_rate) <= 1)
    _check(
        checks,
        failures,
        "real_repo_replay.replay_reproduction_rate",
        replay_rate_ok,
        f"value={replay_rate!r}",
    )
    replay_triage = real_repo_replay.get("triage", {})
    _check(
        checks,
        failures,
        "real_repo_replay.triage_type",
        isinstance(replay_triage, dict),
        "object expected",
    )
    if isinstance(replay_triage, dict):
        triage_total = 0
        for key, value in replay_triage.items():
            parsed_value = _as_int(value)
            ok = isinstance(key, str) and bool(key) and parsed_value is not None and parsed_value >= 0
            _check(
                checks,
                failures,
                f"real_repo_replay.triage.{key}",
                ok,
                f"value={value!r}",
            )
            if parsed_value is not None:
                triage_total += parsed_value
        if replay_checked is not None:
            _check(
                checks,
                failures,
                "real_repo_replay.triage_partition",
                triage_total == replay_checked,
                f"triage_total={triage_total} checked={replay_checked}",
            )
    latest_replay_reports = package.get("latest_replay_reports", [])
    _check(
        checks,
        failures,
        "latest_replay_reports.type",
        isinstance(latest_replay_reports, list),
        "list expected",
    )
    replay_triage_samples = package.get("replay_triage_samples", [])
    _check(
        checks,
        failures,
        "replay_triage_samples.type",
        isinstance(replay_triage_samples, list),
        "list expected",
    )
    replay_misses = package.get("real_repo_replay_misses", [])
    _check(
        checks,
        failures,
        "real_repo_replay_misses.type",
        isinstance(replay_misses, list),
        "list expected",
    )

    real_repo_replay_unique = _require_mapping(
        package.get("real_repo_replay_unique"),
        "real_repo_replay_unique",
        checks,
        failures,
    )
    unique_counts = _validate_non_negative_ints(
        real_repo_replay_unique,
        [
            "packet_checked",
            "unique_claims",
            "duplicate_packets_collapsed",
            "unique_reproduced",
            "unique_partially_reproduced",
            "unique_not_reproduced",
            "unique_unsupported",
            "unique_error",
            "unique_unsupported_signals",
        ],
        checks,
        failures,
        "real_repo_replay_unique",
    )
    unique_claims = unique_counts.get("unique_claims")
    packet_checked = unique_counts.get("packet_checked")
    duplicate_packets_collapsed = unique_counts.get("duplicate_packets_collapsed")
    if unique_claims is not None:
        unique_terminal = sum(
            unique_counts.get(key, 0)
            for key in [
                "unique_reproduced",
                "unique_partially_reproduced",
                "unique_not_reproduced",
                "unique_unsupported",
                "unique_error",
            ]
        )
        if isinstance(replay_misses, list):
            expected_misses = (
                unique_counts.get("unique_not_reproduced", 0)
                + unique_counts.get("unique_unsupported", 0)
                + unique_counts.get("unique_error", 0)
            )
            _check(
                checks,
                failures,
                "real_repo_replay_misses.unique_miss_coverage",
                len(replay_misses) >= expected_misses,
                f"misses={len(replay_misses)} expected_at_least={expected_misses}",
            )
            for index, item in enumerate(replay_misses):
                if not isinstance(item, dict):
                    _check(checks, failures, f"real_repo_replay_misses[{index}]", False, "not an object")
                    continue
                for key in ["repo", "target", "verdict", "triage_class", "policy"]:
                    value = item.get(key)
                    _check(
                        checks,
                        failures,
                        f"real_repo_replay_misses[{index}].{key}",
                        isinstance(value, str) and bool(value),
                        f"value={value!r}",
                    )
                packets_collapsed = _as_int(item.get("packets_collapsed"))
                _check(
                    checks,
                    failures,
                    f"real_repo_replay_misses[{index}].packets_collapsed",
                    packets_collapsed is not None and packets_collapsed > 0,
                    f"value={item.get('packets_collapsed')!r}",
                )
                _check(
                    checks,
                    failures,
                    f"real_repo_replay_misses[{index}].signals_type",
                    isinstance(item.get("signals", []), list),
                    "list expected",
                )
        _check(
            checks,
            failures,
            "real_repo_replay_unique.verdict_partition",
            unique_terminal == unique_claims,
            f"verdicts={unique_terminal} unique_claims={unique_claims}",
        )
    if packet_checked is not None and unique_claims is not None and duplicate_packets_collapsed is not None:
        _check(
            checks,
            failures,
            "real_repo_replay_unique.duplicate_partition",
            packet_checked - unique_claims == duplicate_packets_collapsed,
            f"packet_checked={packet_checked} unique_claims={unique_claims} collapsed={duplicate_packets_collapsed}",
        )
    unique_rate = real_repo_replay_unique.get("unique_replay_reproduction_rate")
    unique_rate_ok = unique_rate is None or (_as_float(unique_rate) is not None and 0 <= float(unique_rate) <= 1)
    _check(
        checks,
        failures,
        "real_repo_replay_unique.unique_replay_reproduction_rate",
        unique_rate_ok,
        f"value={unique_rate!r}",
    )
    unique_triage = real_repo_replay_unique.get("triage", {})
    _check(
        checks,
        failures,
        "real_repo_replay_unique.triage_type",
        isinstance(unique_triage, dict),
        "object expected",
    )
    if isinstance(unique_triage, dict):
        unique_triage_total = 0
        for key, value in unique_triage.items():
            parsed_value = _as_int(value)
            ok = isinstance(key, str) and bool(key) and parsed_value is not None and parsed_value >= 0
            _check(
                checks,
                failures,
                f"real_repo_replay_unique.triage.{key}",
                ok,
                f"value={value!r}",
            )
            if parsed_value is not None:
                unique_triage_total += parsed_value
        if unique_claims is not None:
            _check(
                checks,
                failures,
                "real_repo_replay_unique.triage_partition",
                unique_triage_total == unique_claims,
                f"triage_total={unique_triage_total} unique_claims={unique_claims}",
            )

    suspected = marked_counts.get("suspected")
    calibration_ledger = _require_mapping(package.get("calibration_ledger"), "calibration_ledger", checks, failures)
    _check(
        checks,
        failures,
        "calibration_ledger.accuracy_basis",
        calibration_ledger.get("accuracy_basis") == "oracle_scored_accuracy",
        f"value={calibration_ledger.get('accuracy_basis')!r}",
    )
    _check(
        checks,
        failures,
        "calibration_ledger.policy",
        isinstance(calibration_ledger.get("policy"), str) and bool(calibration_ledger.get("policy")),
        "non-empty policy expected",
    )
    expected_replay_verified = unique_counts.get("unique_reproduced", 0) + unique_counts.get("unique_partially_reproduced", 0)
    expected_quarantined = (
        unique_counts.get("unique_not_reproduced", 0)
        + unique_counts.get("unique_unsupported", 0)
        + unique_counts.get("unique_error", 0)
    )
    expected_suspected = suspected or 0
    calibration_expected = {
        "oracle_scored_accuracy": unique_cases or 0,
        "replay_verified_real_repo": expected_replay_verified,
        "quarantined_replay_misses": expected_quarantined,
        "unverified_suspected_leads": expected_suspected,
    }
    calibration_counts = _validate_non_negative_ints(
        calibration_ledger,
        [
            "accuracy_case_count",
            "stable_accuracy_case_count",
            "non_oracle_evidence_count",
            "quarantined_count",
            "unverified_suspected_count",
        ],
        checks,
        failures,
        "calibration_ledger",
    )
    if "accuracy_case_count" in calibration_counts:
        _check(
            checks,
            failures,
            "calibration_ledger.accuracy_case_count_matches_oracle",
            calibration_counts["accuracy_case_count"] == calibration_expected["oracle_scored_accuracy"],
            f"accuracy_case_count={calibration_counts['accuracy_case_count']} unique_cases={calibration_expected['oracle_scored_accuracy']}",
        )
    if "stable_accuracy_case_count" in calibration_counts and stable_unique_cases is not None:
        _check(
            checks,
            failures,
            "calibration_ledger.stable_accuracy_case_count_matches_oracle",
            calibration_counts["stable_accuracy_case_count"] == stable_unique_cases,
            f"stable_accuracy_case_count={calibration_counts['stable_accuracy_case_count']} stable_unique_cases={stable_unique_cases}",
        )
    if "non_oracle_evidence_count" in calibration_counts:
        expected_non_oracle = expected_replay_verified + expected_quarantined + expected_suspected
        _check(
            checks,
            failures,
            "calibration_ledger.non_oracle_evidence_count",
            calibration_counts["non_oracle_evidence_count"] == expected_non_oracle,
            f"non_oracle={calibration_counts['non_oracle_evidence_count']} expected={expected_non_oracle}",
        )
    if "quarantined_count" in calibration_counts:
        _check(
            checks,
            failures,
            "calibration_ledger.quarantined_count",
            calibration_counts["quarantined_count"] == expected_quarantined,
            f"quarantined={calibration_counts['quarantined_count']} expected={expected_quarantined}",
        )
    if "unverified_suspected_count" in calibration_counts:
        _check(
            checks,
            failures,
            "calibration_ledger.unverified_suspected_count",
            calibration_counts["unverified_suspected_count"] == expected_suspected,
            f"unverified_suspected={calibration_counts['unverified_suspected_count']} expected={expected_suspected}",
        )
    buckets = calibration_ledger.get("buckets", [])
    _check(checks, failures, "calibration_ledger.buckets_type", isinstance(buckets, list), "list expected")
    if isinstance(buckets, list):
        seen_buckets: set[str] = set()
        for index, bucket in enumerate(buckets):
            if not isinstance(bucket, dict):
                _check(checks, failures, f"calibration_ledger.buckets[{index}]", False, "not an object")
                continue
            bucket_id = bucket.get("id")
            bucket_count = _as_int(bucket.get("count"))
            seen_buckets.add(str(bucket_id))
            _check(
                checks,
                failures,
                f"calibration_ledger.buckets[{index}].id",
                isinstance(bucket_id, str) and bucket_id in calibration_expected,
                f"value={bucket_id!r}",
            )
            _check(
                checks,
                failures,
                f"calibration_ledger.buckets[{index}].count",
                bucket_count is not None and bucket_count == calibration_expected.get(str(bucket_id)),
                f"value={bucket.get('count')!r} expected={calibration_expected.get(str(bucket_id))}",
            )
            expected_accuracy_flag = bucket_id == "oracle_scored_accuracy"
            _check(
                checks,
                failures,
                f"calibration_ledger.buckets[{index}].contributes_to_accuracy",
                bucket.get("contributes_to_accuracy") is expected_accuracy_flag,
                f"value={bucket.get('contributes_to_accuracy')!r} expected={expected_accuracy_flag}",
            )
            for key in ["label", "confidence", "policy"]:
                value = bucket.get(key)
                _check(
                    checks,
                    failures,
                    f"calibration_ledger.buckets[{index}].{key}",
                    isinstance(value, str) and bool(value),
                    f"value={value!r}",
                )
        _check(
            checks,
            failures,
            "calibration_ledger.required_buckets",
            set(calibration_expected).issubset(seen_buckets),
            f"seen={sorted(seen_buckets)}",
        )

    promotion_queue = package.get("promotion_queue", [])
    _check(checks, failures, "promotion_queue.type", isinstance(promotion_queue, list), "list expected")
    if isinstance(promotion_queue, list):
        if expected_suspected > 0:
            _check(
                checks,
                failures,
                "promotion_queue.present_when_suspected",
                len(promotion_queue) > 0,
                f"suspected={expected_suspected} queue={len(promotion_queue)}",
            )
        previous_rank = 0
        for index, item in enumerate(promotion_queue):
            if not isinstance(item, dict):
                _check(checks, failures, f"promotion_queue[{index}]", False, "not an object")
                continue
            rank = _as_int(item.get("rank"))
            _check(
                checks,
                failures,
                f"promotion_queue[{index}].rank",
                rank is not None and rank > previous_rank,
                f"value={item.get('rank')!r} previous={previous_rank}",
            )
            if rank is not None:
                previous_rank = rank
            for key in ["finding_id", "claim", "promotion_action", "promotion_policy"]:
                value = item.get(key)
                _check(
                    checks,
                    failures,
                    f"promotion_queue[{index}].{key}",
                    isinstance(value, str) and bool(value),
                    f"value={value!r}",
                )
            _check(
                checks,
                failures,
                f"promotion_queue[{index}].policy_excludes_accuracy",
                item.get("promotion_policy") == "excluded_from_accuracy_until_oracle_or_replay_promoted",
                f"value={item.get('promotion_policy')!r}",
            )
            packets_seen = _as_int(item.get("packets_seen"))
            _check(
                checks,
                failures,
                f"promotion_queue[{index}].packets_seen",
                packets_seen is not None and packets_seen > 0,
                f"value={item.get('packets_seen')!r}",
            )
            for key in ["signals", "reproduction_steps"]:
                _check(
                    checks,
                    failures,
                    f"promotion_queue[{index}].{key}_type",
                    isinstance(item.get(key, []), list),
                    "list expected",
                )

    promotion_triage_pack = package.get("promotion_triage_pack", {})
    _check(
        checks,
        failures,
        "promotion_triage_pack.type",
        isinstance(promotion_triage_pack, dict),
        "object expected",
    )
    triage_moves: list[Any] = []
    if isinstance(promotion_triage_pack, dict):
        policy = promotion_triage_pack.get("policy")
        _check(
            checks,
            failures,
            "promotion_triage_pack.policy",
            isinstance(policy, str) and bool(policy.strip()),
            f"value={policy!r}",
        )
        candidate_count = _as_int(promotion_triage_pack.get("candidate_count"))
        expected_queue_len = len(promotion_queue) if isinstance(promotion_queue, list) else 0
        _check(
            checks,
            failures,
            "promotion_triage_pack.candidate_count",
            candidate_count == expected_queue_len,
            f"candidate_count={promotion_triage_pack.get('candidate_count')!r} queue={expected_queue_len}",
        )
        action_buckets = promotion_triage_pack.get("action_buckets", [])
        triage_moves = promotion_triage_pack.get("top_moves", [])
        _check(
            checks,
            failures,
            "promotion_triage_pack.action_buckets_type",
            isinstance(action_buckets, list),
            "list expected",
        )
        _check(
            checks,
            failures,
            "promotion_triage_pack.top_moves_type",
            isinstance(triage_moves, list),
            "list expected",
        )
        top_candidate_count = _as_int(promotion_triage_pack.get("top_candidate_count"))
        _check(
            checks,
            failures,
            "promotion_triage_pack.top_candidate_count",
            isinstance(triage_moves, list) and top_candidate_count == len(triage_moves),
            f"top_candidate_count={promotion_triage_pack.get('top_candidate_count')!r} moves={len(triage_moves) if isinstance(triage_moves, list) else 'n/a'}",
        )
        if expected_suspected > 0:
            _check(
                checks,
                failures,
                "promotion_triage_pack.present_when_suspected",
                isinstance(triage_moves, list) and len(triage_moves) > 0,
                f"suspected={expected_suspected} moves={len(triage_moves) if isinstance(triage_moves, list) else 'n/a'}",
            )
        if isinstance(action_buckets, list):
            for index, bucket in enumerate(action_buckets):
                if not isinstance(bucket, dict):
                    _check(checks, failures, f"promotion_triage_pack.action_buckets[{index}]", False, "not an object")
                    continue
                for key in ["id", "label", "promotion_action", "accuracy_policy"]:
                    value = bucket.get(key)
                    _check(
                        checks,
                        failures,
                        f"promotion_triage_pack.action_buckets[{index}].{key}",
                        isinstance(value, str) and bool(value),
                        f"value={value!r}",
                    )
                _check(
                    checks,
                    failures,
                    f"promotion_triage_pack.action_buckets[{index}].accuracy_policy_excludes_accuracy",
                    bucket.get("accuracy_policy") == "excluded_from_accuracy_until_oracle_or_replay_promoted",
                    f"value={bucket.get('accuracy_policy')!r}",
                )
        if isinstance(triage_moves, list):
            for index, move in enumerate(triage_moves):
                if not isinstance(move, dict):
                    _check(checks, failures, f"promotion_triage_pack.top_moves[{index}]", False, "not an object")
                    continue
                rank = _as_int(move.get("rank"))
                _check(
                    checks,
                    failures,
                    f"promotion_triage_pack.top_moves[{index}].rank",
                    rank is not None and rank > 0,
                    f"value={move.get('rank')!r}",
                )
                for key in ["finding_id", "promotion_action", "verification_command", "accuracy_policy"]:
                    value = move.get(key)
                    _check(
                        checks,
                        failures,
                        f"promotion_triage_pack.top_moves[{index}].{key}",
                        isinstance(value, str) and bool(value),
                        f"value={value!r}",
                    )
                _check(
                    checks,
                    failures,
                    f"promotion_triage_pack.top_moves[{index}].accuracy_policy_excludes_accuracy",
                    move.get("accuracy_policy") == "excluded_from_accuracy_until_oracle_or_replay_promoted",
                    f"value={move.get('accuracy_policy')!r}",
                )

    eval_summary = package.get("eval_log_summary") or {}
    if eval_summary:
        eval_counts = _validate_non_negative_ints(
            eval_summary,
            ["events", "completed", "failed", "bugsinpy", "real_repo_audit"],
            checks,
            failures,
            "eval_log_summary",
        )
        events = eval_counts.get("events")
        completed = eval_counts.get("completed")
        failed = eval_counts.get("failed")
        latest_events = package.get("latest_eval_events") or []
        if events is not None and isinstance(latest_events, list):
            _check(
                checks,
                failures,
                "eval_log_summary.latest_events_bound",
                events >= len(latest_events),
                f"events={events} latest={len(latest_events)}",
            )
        if events is not None and completed is not None and failed is not None:
            _check(
                checks,
                failures,
                "eval_log_summary.terminal_events_bound",
                completed + failed <= events,
                f"completed+failed={completed + failed} events={events}",
            )

    if rejected_case_results and rejected_case_results > 0:
        warnings.append(f"{rejected_case_results} oracle case result(s) rejected from scoring")
    if disagreements and disagreements > 0:
        warnings.append(f"{disagreements} oracle case(s) have repeated-outcome disagreements; stable metrics exclude them")
    suspected = _as_int(marked_evidence.get("suspected"))
    if suspected and suspected > 0:
        warnings.append(f"{suspected} suspected finding(s) remain unverified by oracle")
    if evidence_incomplete and evidence_incomplete > 0:
        warnings.append(f"{evidence_incomplete} evidence packet(s) are missing reproducibility fields")
    replay_not_reproduced = replay_counts.get("not_reproduced", 0)
    replay_errors = replay_counts.get("error", 0)
    if replay_not_reproduced:
        warnings.append(f"{replay_not_reproduced} replayed real-repo evidence packet(s) did not reproduce")
    if replay_errors:
        warnings.append(f"{replay_errors} replayed real-repo evidence packet(s) errored")

    return {
        "ok": not failures,
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
        "summary": {
            "unique_oracle_cases": unique_cases or 0,
            "stable_oracle_cases": stable_unique_cases or 0,
            "unstable_oracle_cases": unstable_cases or 0,
            "rejected_case_results": rejected_case_results or 0,
            "precision": oracle_totals.get("precision"),
            "precision_wilson_lower_95": oracle_totals.get("precision_wilson_lower_95"),
            "recall": oracle_totals.get("recall"),
            "recall_wilson_lower_95": oracle_totals.get("recall_wilson_lower_95"),
            "f1": oracle_totals.get("f1"),
            "stable_precision": oracle_totals.get("stable_precision"),
            "stable_precision_wilson_lower_95": oracle_totals.get("stable_precision_wilson_lower_95"),
            "stable_recall": oracle_totals.get("stable_recall"),
            "stable_recall_wilson_lower_95": oracle_totals.get("stable_recall_wilson_lower_95"),
            "stable_f1": oracle_totals.get("stable_f1"),
            "marked_entries": marked_evidence.get("entries", 0),
            "suspected_entries": marked_evidence.get("suspected", 0),
            "evidence_completion_rate": evidence_completeness.get("completion_rate"),
            "incomplete_evidence_packets": evidence_completeness.get("incomplete_entries", 0),
            "replay_checked": real_repo_replay.get("checked", 0),
            "replay_reproduced": real_repo_replay.get("reproduced", 0),
            "replay_partially_reproduced": real_repo_replay.get("partially_reproduced", 0),
            "replay_not_reproduced": real_repo_replay.get("not_reproduced", 0),
            "replay_unsupported_signals": real_repo_replay.get("unsupported_signals", 0),
            "replay_reproduction_rate": real_repo_replay.get("replay_reproduction_rate"),
            "replay_triage": real_repo_replay.get("triage", {}),
            "unique_replay_claims": real_repo_replay_unique.get("unique_claims", 0),
            "unique_replay_reproduced": real_repo_replay_unique.get("unique_reproduced", 0),
            "unique_replay_partially_reproduced": real_repo_replay_unique.get("unique_partially_reproduced", 0),
            "unique_replay_not_reproduced": real_repo_replay_unique.get("unique_not_reproduced", 0),
            "unique_replay_duplicate_packets_collapsed": real_repo_replay_unique.get("duplicate_packets_collapsed", 0),
            "unique_replay_reproduction_rate": real_repo_replay_unique.get("unique_replay_reproduction_rate"),
            "unique_replay_triage": real_repo_replay_unique.get("triage", {}),
            "promotion_queue_candidates": len(promotion_queue) if isinstance(promotion_queue, list) else 0,
            "promotion_triage_moves": len(triage_moves) if isinstance(triage_moves, list) else 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate BugLab submission truth claims.")
    parser.add_argument("package", nargs="?", default=str(DEFAULT_PACKAGE), help="Path to submission_results.json")
    parser.add_argument("--json", action="store_true", help="Print full validation JSON")
    args = parser.parse_args(argv)

    package_path = Path(args.package)
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {"ok": False, "checks": [], "failures": [f"missing package: {package_path}"], "warnings": []}
    except json.JSONDecodeError as exc:
        result = {"ok": False, "checks": [], "failures": [f"invalid JSON: {exc}"], "warnings": []}
    else:
        result = validate_package(package)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"BugLab submission validation: {status}")
        for key, value in result.get("summary", {}).items():
            print(f"{key}: {value}")
        for warning in result.get("warnings", []):
            print(f"warning: {warning}")
        for failure in result.get("failures", []):
            print(f"failure: {failure}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
