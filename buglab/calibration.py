from __future__ import annotations

import csv
import fnmatch
import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.pareto import record_signals
from buglab.pareto import signal_family


@dataclass(frozen=True)
class CalibrationConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    ledger: str | Path = ".buglab/calibration/truth_ledger.json"
    top: int = 20


def calibrate_findings(config: CalibrationConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    config = config or CalibrationConfig(**kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    ledger_path = Path(config.ledger)
    if not ledger_path.is_absolute():
        ledger_path = repo / ledger_path
    ledger = load_ledger(ledger_path)
    findings = collect_audit_findings(output_root)
    classified = [classify_record(record, ledger) for record in findings]
    summary = summarize_classified(classified, ledger, top=config.top)

    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "calibration_report.csv"
    json_path = output_root / "calibration_report.json"
    html_path = output_root / "calibration_report.html"
    write_calibration_csv(csv_path, classified)
    payload = {
        "schema_version": "buglab.calibration_report.v1",
        "repo": str(repo),
        "output_root": str(output_root),
        "ledger_path": str(ledger_path),
        "summary": summary,
        "findings": classified,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_path.write_text(render_calibration_html(payload), encoding="utf-8")
    return {
        "summary": summary,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "html_path": str(html_path),
    }


def load_ledger(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "buglab.calibration_ledger.v1":
        raise ValueError(f"Unsupported calibration ledger schema: {payload.get('schema_version')}")
    payload.setdefault("rules", [])
    payload.setdefault("expectations", [])
    return payload


def collect_audit_findings(output_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(output_root.glob("*/findings.jsonl")):
        run_dir = path.parent
        audit_meta = load_run_audit_meta(run_dir)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = {
                    "finding_id": f"{run_dir.name}:{line_number}",
                    "sector": "unknown",
                    "target": str(path),
                    "signals": [f"invalid_findings_jsonl:line={line_number}"],
                }
            if not isinstance(record, dict):
                continue
            hydrated = dict(record)
            hydrated["run_id"] = run_dir.name
            hydrated["repo"] = audit_meta.get("repo", "")
            hydrated["repo_name"] = Path(str(audit_meta.get("repo", ""))).name
            findings.append(hydrated)
    return findings


def load_run_audit_meta(run_dir: Path) -> dict[str, Any]:
    audit_json = run_dir / "repo_audit.json"
    if not audit_json.exists():
        return {}
    try:
        payload = json.loads(audit_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def classify_record(record: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    signals = record_signals(record)
    families = sorted({signal_family(signal) for signal in signals})
    matched_rule = None
    for rule in ledger.get("rules", []):
        if rule_matches(rule, record, signals, families):
            matched_rule = rule
            break
    label = str(matched_rule.get("label", "unlabeled")) if matched_rule else "unlabeled"
    return {
        "run_id": record.get("run_id", ""),
        "repo_name": record.get("repo_name", ""),
        "target": record.get("target", ""),
        "finding_id": record.get("finding_id", ""),
        "sector": record.get("sector", ""),
        "severity": record.get("severity", ""),
        "signals": signals,
        "signal_families": families,
        "label": label,
        "rule_id": matched_rule.get("id", "") if matched_rule else "",
        "reason": matched_rule.get("reason", "") if matched_rule else "",
        "case_path": record.get("case_path", ""),
        "artifact": record.get("artifact", ""),
    }


def rule_matches(rule: dict[str, Any], record: dict[str, Any], signals: list[str], families: list[str]) -> bool:
    checks = [
        pattern_match(rule.get("repo_pattern"), str(record.get("repo_name", ""))),
        pattern_match(rule.get("run_pattern"), str(record.get("run_id", ""))),
        pattern_match(rule.get("target_pattern"), str(record.get("target", ""))),
        exact_or_empty(rule.get("sector"), str(record.get("sector", ""))),
        exact_or_empty(rule.get("severity"), str(record.get("severity", ""))),
        family_match(rule.get("signal_family"), families),
        signal_match(rule.get("signal_pattern"), signals),
    ]
    return all(checks)


def pattern_match(pattern: Any, value: str) -> bool:
    if not pattern:
        return True
    return fnmatch.fnmatch(value, str(pattern))


def exact_or_empty(expected: Any, value: str) -> bool:
    return not expected or str(expected) == value


def family_match(expected: Any, families: list[str]) -> bool:
    if not expected:
        return True
    return str(expected) in families


def signal_match(pattern: Any, signals: list[str]) -> bool:
    if not pattern:
        return True
    expected = str(pattern)
    return any(fnmatch.fnmatch(signal, expected) for signal in signals)


def summarize_classified(classified: list[dict[str, Any]], ledger: dict[str, Any], *, top: int) -> dict[str, Any]:
    label_counts = Counter(str(row["label"]) for row in classified)
    reviewed = label_counts["true_positive"] + label_counts["false_positive"]
    precision = round(label_counts["true_positive"] / reviewed, 4) if reviewed else None
    strict_precision = round(label_counts["true_positive"] / len(classified), 4) if classified else None
    expectation_summary = summarize_expectations(classified, ledger.get("expectations", []))
    per_run = summarize_per_run(classified)
    false_positive_families = Counter()
    true_positive_families = Counter()
    unlabeled_families = Counter()
    for row in classified:
        counter = (
            false_positive_families
            if row["label"] == "false_positive"
            else true_positive_families
            if row["label"] == "true_positive"
            else unlabeled_families
        )
        for family in row["signal_families"]:
            counter[family] += 1
    return {
        "headline": "BugLab does not just hunt bugs. It runs an R&D loop on its own bug-hunting strategy.",
        "findings": len(classified),
        "reviewed_findings": reviewed,
        "true_positive": label_counts["true_positive"],
        "false_positive": label_counts["false_positive"],
        "ignored": label_counts["ignore"],
        "unlabeled": label_counts["unlabeled"],
        "labeled_precision": precision,
        "strict_precision": strict_precision,
        "recall": expectation_summary["recall"],
        "expectations": expectation_summary,
        "per_run": per_run,
        "false_positive_families": ranked_counter(false_positive_families, top),
        "true_positive_families": ranked_counter(true_positive_families, top),
        "unlabeled_families": ranked_counter(unlabeled_families, top),
        "tightening_actions": tightening_actions(false_positive_families, unlabeled_families),
    }


def summarize_expectations(classified: list[dict[str, Any]], expectations: list[dict[str, Any]]) -> dict[str, Any]:
    hits = []
    misses = []
    for expectation in expectations:
        matched = [
            row
            for row in classified
            if row["label"] == "true_positive"
            and rule_matches(expectation, row, row["signals"], row["signal_families"])
        ]
        if matched:
            hits.append({"id": expectation.get("id", ""), "target_pattern": expectation.get("target_pattern", ""), "matched": len(matched)})
        else:
            misses.append({"id": expectation.get("id", ""), "target_pattern": expectation.get("target_pattern", ""), "reason": expectation.get("reason", "")})
    recall = round(len(hits) / len(expectations), 4) if expectations else None
    return {"total": len(expectations), "hit": len(hits), "missed": len(misses), "recall": recall, "hits": hits, "misses": misses}


def summarize_per_run(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in classified:
        grouped.setdefault(str(row["run_id"]), []).append(row)
    rows = []
    for run_id, records in sorted(grouped.items()):
        labels = Counter(str(row["label"]) for row in records)
        reviewed = labels["true_positive"] + labels["false_positive"]
        rows.append(
            {
                "run_id": run_id,
                "findings": len(records),
                "true_positive": labels["true_positive"],
                "false_positive": labels["false_positive"],
                "unlabeled": labels["unlabeled"],
                "precision": round(labels["true_positive"] / reviewed, 4) if reviewed else None,
            }
        )
    return rows


def ranked_counter(counter: Counter[str], top: int) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(top)]


def tightening_actions(false_positive_families: Counter[str], unlabeled_families: Counter[str]) -> list[str]:
    actions = []
    for name, count in false_positive_families.most_common(5):
        actions.append(f"Patch or demote detector family `{name}`; it accounts for {count} labeled false positive signal(s).")
    for name, count in unlabeled_families.most_common(5):
        actions.append(f"Review and label detector family `{name}`; {count} finding(s) are not yet in the truth ledger.")
    if not actions:
        actions.append("No labeled false-positive clusters remain. Add more portfolio repos or stricter expectations before changing detectors.")
    return actions


def write_calibration_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = ["run_id", "repo_name", "target", "finding_id", "sector", "severity", "label", "rule_id", "signal_families", "reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row[field]) if field == "signal_families" else row.get(field, "") for field in fieldnames})


def render_calibration_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    classified_rows = calibration_table(payload.get("findings", []))
    per_run_rows = simple_table(summary.get("per_run", []), ["run_id", "findings", "true_positive", "false_positive", "unlabeled", "precision"])
    actions = "".join(f"<li>{html.escape(action)}</li>" for action in summary.get("tightening_actions", []))
    precision = metric(summary.get("labeled_precision"))
    strict_precision = metric(summary.get("strict_precision"))
    recall = metric(summary.get("recall"))
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BugLab Calibration Report</title>
    <style>
      body {{ margin: 0; font-family: Consolas, ui-monospace, monospace; background: #050805; color: #dcffe0; }}
      main {{ width: min(1240px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }}
      h1 {{ color: #74f476; font-size: 34px; margin-bottom: 8px; }}
      p {{ color: #8aa58c; }}
      .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
      .metric, section {{ border: 1px solid #334239; background: #07100b; box-shadow: 0 0 20px rgba(116, 244, 118, 0.08); }}
      .metric {{ padding: 14px; }}
      .metric strong {{ display: block; color: #36d7df; font-size: 28px; }}
      section {{ padding: 16px; margin: 18px 0; overflow-x: auto; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ border-bottom: 1px solid #1e2a22; padding: 7px 8px; text-align: left; font-size: 12px; vertical-align: top; }}
      th {{ color: #f0c24b; }}
      li {{ margin: 7px 0; }}
      @media (max-width: 800px) {{ .metrics {{ grid-template-columns: 1fr 1fr; }} }}
    </style>
  </head>
  <body>
    <main>
      <h1>BugLab Calibration Report</h1>
      <p>{html.escape(summary.get('headline', 'BugLab calibration'))}</p>
      <section class="metrics">
        <div class="metric"><strong>{summary.get('findings', 0)}</strong>Findings</div>
        <div class="metric"><strong>{precision}</strong>Labeled precision</div>
        <div class="metric"><strong>{strict_precision}</strong>Strict precision</div>
        <div class="metric"><strong>{recall}</strong>Recall</div>
      </section>
      <section>
        <h2>Tightening Actions</h2>
        <ol>{actions}</ol>
      </section>
      <section>
        <h2>Iteration Metrics</h2>
        {per_run_rows}
      </section>
      <section>
        <h2>Classified Findings</h2>
        {classified_rows}
      </section>
    </main>
  </body>
</html>
"""


def metric(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1%}"


def simple_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "<p>No rows.</p>"
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def calibration_table(rows: list[dict[str, Any]]) -> str:
    columns = ["run_id", "repo_name", "target", "sector", "label", "rule_id", "signal_families", "reason"]
    if not rows:
        return "<p>No findings.</p>"
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(', '.join(row.get(column, [])) if column == 'signal_families' else str(row.get(column, '')))}</td>"
                for column in columns
            )
            + "</tr>"
        )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"
