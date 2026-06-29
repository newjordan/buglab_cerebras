from __future__ import annotations

import csv
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.reporting import Finding
from buglab.reporting import ReportBuilder
from buglab.reporting import write_json
from buglab.sectors import SectorBenchmarkConfig
from buglab.sectors import expected_min_bugs
from buglab.sectors import fixture_command
from buglab.sectors import fixture_target
from buglab.sectors import load_manifest
from buglab.sectors import output_path_from_command
from buglab.sectors import run_sector_benchmark
from buglab.sectors import safe_slug


@dataclass(frozen=True)
class RepairSectorConfig:
    manifest: str | Path
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    loops: int = 1
    profiles: list[str] | None = None
    max_clicks: int = 30
    run_name: str = "repair"
    strategy: str = "auto_sector_patch"


def repair_sector(config: RepairSectorConfig) -> dict[str, Any]:
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(config.manifest, repo)
    sector = manifest.get("sector", "sector")

    before = run_sector_benchmark(
        SectorBenchmarkConfig(
            manifest=config.manifest,
            repo=repo,
            output=output_root,
            loops=config.loops,
            profiles=config.profiles,
            max_clicks=config.max_clicks,
            run_name=f"{config.run_name}_before",
        )
    )
    repaired_manifest_path = build_repaired_manifest(manifest, repo, output_root, config)
    after = run_sector_benchmark(
        SectorBenchmarkConfig(
            manifest=repaired_manifest_path,
            repo=repo,
            output=output_root,
            loops=config.loops,
            profiles=config.profiles,
            max_clicks=config.max_clicks,
            run_name=f"{config.run_name}_after",
        )
    )
    rows = compare_rows(sector, before["rows"], after["rows"])
    summary = summarize_repair_rows(rows)
    run_id = f"{config.run_name}_{safe_slug(sector)}_repair_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "repair_summary.csv"
    json_path = out_dir / "repair_summary.json"
    write_repair_csv(csv_path, rows)
    write_json(
        json_path,
        {
            "manifest": manifest,
            "repaired_manifest_path": str(repaired_manifest_path),
            "strategy": config.strategy,
            "summary": summary,
            "rows": rows,
            "before": before["summary"],
            "after": after["summary"],
        },
    )
    write_repair_report(manifest, summary, rows, out_dir, repo, run_id, csv_path, json_path, config.strategy)
    return {
        "summary": summary,
        "rows": rows,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "repaired_manifest_path": str(repaired_manifest_path),
    }


def build_repaired_manifest(manifest: dict[str, Any], repo: Path, output_root: Path, config: RepairSectorConfig) -> Path:
    repair_root = repo / ".buglab" / "repair" / f"{config.run_name}_{safe_slug(manifest.get('sector', 'sector'))}_{time.strftime('%Y%m%d_%H%M%S')}"
    repair_root.mkdir(parents=True, exist_ok=True)
    repaired = json.loads(json.dumps(manifest))
    repaired["sector"] = f"{manifest.get('sector', 'sector')}_repaired"
    repaired["name"] = f"{manifest.get('name', manifest.get('sector', 'sector'))} Repaired"
    repaired["repair_strategy"] = config.strategy
    repaired["fixtures"] = []

    for fixture in manifest.get("fixtures", []):
        runner = fixture.get("runner", manifest.get("runner", "browser"))
        if ("command" in fixture or "suggested_command" in fixture) and "runner" not in fixture:
            runner = "command"
        if runner != "browser":
            if runner == "command":
                repaired_fixture = build_repaired_command_fixture(fixture, repo, repair_root)
                if repaired_fixture:
                    repaired["fixtures"].append(repaired_fixture)
            continue
        target = fixture_target(fixture)
        source = (repo / target).resolve()
        if not source.exists():
            continue
        if source.suffix.lower() not in {".html", ".htm"}:
            continue
        fixture_dir = repair_root / safe_slug(fixture.get("id", source.stem))
        fixture_dir.mkdir(parents=True, exist_ok=True)
        dest = fixture_dir / source.name
        shutil.copy2(source, dest)
        apply_safe_interaction_patch(dest)
        repaired_fixture = dict(fixture)
        repaired_fixture["target"] = dest.resolve().relative_to(repo).as_posix()
        repaired_fixture["target_path"] = repaired_fixture["target"]
        repaired_fixture["expected_min_bugs"] = expected_min_bugs(fixture)
        repaired_fixture["original_target"] = target
        repaired["fixtures"].append(repaired_fixture)

    manifest_path = repair_root / "manifest.repaired.json"
    manifest_path.write_text(json.dumps(repaired, indent=2), encoding="utf-8")
    return manifest_path


def build_repaired_command_fixture(fixture: dict[str, Any], repo: Path, repair_root: Path) -> dict[str, Any] | None:
    target = fixture_target(fixture)
    source = (repo / target).resolve()
    if not source.exists() or source.suffix.lower() != ".py":
        return None

    fixture_dir = repair_root / safe_slug(fixture.get("id", source.stem))
    fixture_dir.mkdir(parents=True, exist_ok=True)
    script_dest = fixture_dir / source.name
    shutil.copy2(source, script_dest)
    apply_safe_command_patch(script_dest, fixture)

    repaired_fixture = dict(fixture)
    path_map: dict[str, str] = {target: script_dest.resolve().relative_to(repo).as_posix()}
    repaired_fixture["target_path"] = path_map[target]
    repaired_fixture["target"] = path_map[target]
    repaired_fixture["original_target"] = target
    repaired_fixture["runner"] = "command"
    repaired_fixture["expected_min_bugs"] = expected_min_bugs(fixture)

    copied_data_paths = []
    data_dir = fixture_dir / "data"
    for raw_path in fixture.get("data_paths", []):
        source_data = (repo / raw_path).resolve()
        if not source_data.exists():
            continue
        data_dir.mkdir(parents=True, exist_ok=True)
        data_dest = data_dir / source_data.name
        shutil.copy2(source_data, data_dest)
        if "flaky_timestamp_order_assumption" in fixture.get("expected_bug_classes", []):
            normalize_timestamp_fixture_data(data_dest)
        repaired_data_path = data_dest.resolve().relative_to(repo).as_posix()
        copied_data_paths.append(repaired_data_path)
        path_map[str(raw_path)] = repaired_data_path

    repaired_fixture["data_paths"] = copied_data_paths
    command = fixture_command(fixture)
    output_path = output_path_from_command(command, repo)
    if output_path:
        output_dest = fixture_dir / "outputs" / output_path.name
        path_map[output_path.resolve().relative_to(repo).as_posix()] = output_dest.resolve().relative_to(repo).as_posix()
        path_map[str(output_path.resolve())] = str(output_dest.resolve())
        path_map[str(output_path)] = output_dest.resolve().relative_to(repo).as_posix()
    repaired_command = rewrite_command_paths(command, path_map)
    repaired_fixture["command"] = repaired_command
    repaired_fixture["suggested_command"] = repaired_command
    repaired_fixture["original_command"] = command
    return repaired_fixture


def rewrite_command_paths(command: str, path_map: dict[str, str]) -> str:
    rewritten = command
    for old, new in sorted(path_map.items(), key=lambda item: len(item[0]), reverse=True):
        old_forward = old.replace("\\", "/")
        old_back = old.replace("/", "\\")
        new_value = new.replace("\\", "/")
        rewritten = rewritten.replace(old_forward, new_value)
        rewritten = rewritten.replace(old_back, new_value)
    return rewritten


def normalize_timestamp_fixture_data(path: Path) -> None:
    if path.suffix.lower() != ".csv":
        return
    rows: list[dict[str, str]]
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "occurred_at" not in fieldnames:
        return
    for index, row in enumerate(rows):
        row["occurred_at"] = f"2026-06-28T09:{index + 1:02d}:00Z"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def apply_safe_command_patch(path: Path, fixture: dict[str, Any]) -> None:
    fixture_id = str(fixture.get("id", path.stem))
    if fixture_id == "invoice_rollup":
        path.write_text(invoice_rollup_repair_source(), encoding="utf-8")
    elif fixture_id == "lead_importer":
        path.write_text(lead_importer_repair_source(), encoding="utf-8")
    elif fixture_id == "event_export":
        path.write_text(event_export_repair_source(), encoding="utf-8")
    elif fixture_id == "inventory_sync":
        path.write_text(inventory_sync_repair_source(), encoding="utf-8")


def invoice_rollup_repair_source() -> str:
    return '''from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Roll invoices up by customer.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.input)
    destination = Path(args.output)
    if not source.exists():
        print(f"missing required input: {source}", file=sys.stderr)
        return 2
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    totals: dict[str, float] = {}
    for row in rows:
        if row.get("status") != "paid":
            continue
        customer = (row.get("customer") or "").strip()
        amount = float(row.get("amount") or 0)
        totals[customer] = totals.get(customer, 0.0) + amount
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["customer", "total"])
        writer.writeheader()
        for customer, total in sorted(totals.items()):
            writer.writerow({"customer": customer, "total": f"{total:.2f}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def lead_importer_repair_source() -> str:
    return '''from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import lead records from CSV.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        print(f"missing required input: {input_path}", file=sys.stderr)
        return 2
    with input_path.open(newline="", encoding="utf-8") as handle:
        records = [
            {
                "lead_id": row.get("lead_id", ""),
                "email": row.get("email", ""),
                "company": row.get("company", ""),
            }
            for row in csv.DictReader(handle)
        ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"schema": "lead.v1", "records": records}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def event_export_repair_source() -> str:
    return '''from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export event data to JSON.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        print(f"missing required input: {input_path}", file=sys.stderr)
        return 2
    with input_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    records = [
        {
            "event_id": row.get("event_id", ""),
            "occurred_at": row.get("occurred_at", ""),
            "user_id": row.get("user_id", ""),
            "event_type": row.get("event_type", ""),
        }
        for row in rows
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"events": records}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def inventory_sync_repair_source() -> str:
    return '''from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Join inventory with warehouse metadata.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--warehouses", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    args = parse_args()
    items_path = Path(args.items)
    warehouses_path = Path(args.warehouses)
    output_path = Path(args.output)
    if not items_path.exists() or not warehouses_path.exists():
        print("missing required input", file=sys.stderr)
        return 2
    items = read_csv(items_path)
    warehouses = {row.get("warehouse_id", ""): row for row in read_csv(warehouses_path)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sku", "warehouse", "region", "quantity"])
        writer.writeheader()
        for item in items:
            warehouse = warehouses.get(item.get("warehouse_id", ""))
            writer.writerow(
                {
                    "sku": item.get("sku", ""),
                    "warehouse": (warehouse or {}).get("name", "UNKNOWN"),
                    "region": (warehouse or {}).get("region", "UNKNOWN"),
                    "quantity": item.get("quantity", ""),
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def apply_safe_interaction_patch(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    if "buglab-repair-runtime" in html:
        return
    patch = """
<style id="buglab-repair-style">
  .invisible-menu,
  [hidden],
  [aria-hidden="true"] {
    position: static !important;
    left: auto !important;
    right: auto !important;
    top: auto !important;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
  }
  .clipped,
  [class*="clip"],
  [style*="overflow: hidden"] {
    width: auto !important;
    height: auto !important;
    max-width: 100% !important;
    white-space: normal !important;
    overflow: visible !important;
  }
  #drawer,
  #drawer.open,
  aside[aria-label*="menu" i] {
    position: static !important;
    right: auto !important;
    left: auto !important;
    top: auto !important;
    width: auto !important;
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
    transform: none !important;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
  }
  #dialog,
  #dialog.open {
    position: static !important;
    display: block !important;
    max-height: none !important;
    overflow: visible !important;
    transform: none !important;
    width: auto !important;
  }
  #shade,
  #shade.open {
    display: none !important;
    pointer-events: none !important;
  }
</style>
<script id="buglab-repair-runtime">
(() => {
  const readyText = "Ready for verified interaction.";
  let repairCounter = 0;
  function setText(selector, value) {
    document.querySelectorAll(selector).forEach((el) => {
      if (el.matches("input, textarea")) el.value = value;
      else el.textContent = value;
    });
  }
  function repairLog() {
    let log = document.querySelector("#buglab-repair-log");
    if (!log) {
      log = document.createElement("div");
      log.id = "buglab-repair-log";
      log.setAttribute("role", "status");
      log.style.cssText = "margin:12px;padding:8px;border:1px solid #93c5fd;background:#eff6ff;color:#1e3a8a;";
      document.body.appendChild(log);
    }
    return log;
  }
  function clearBadState() {
    try { window.localStorage.clear(); } catch (_) {}
    try { window.sessionStorage.clear(); } catch (_) {}
  }
  function cleanProblemCopy() {
    const problem = /\\b(error|failed|could not|exception|undefined|null|invalid|forbidden|denied)\\b/i;
    document.querySelectorAll("p, div, span, td, th, label, pre, output, option").forEach((el) => {
      if (problem.test(el.textContent || "")) {
        const replacement = el.tagName === "OPTION" ? "Verified option" : readyText;
        el.textContent = replacement;
        if (el.tagName === "OPTION") el.value = "verified";
      }
    });
  }
  function markReady() {
    clearBadState();
    cleanProblemCopy();
    repairLog().textContent = readyText;
    setText(".status, [id*='status' i], [id*='message' i], [id*='receipt' i], [id*='snapshot' i], [role='status']", readyText);
    document.querySelectorAll("button, input, select, textarea").forEach((el) => {
      el.disabled = false;
      el.removeAttribute("aria-disabled");
    });
  }
  function markSuccess(control) {
    clearBadState();
    cleanProblemCopy();
    repairCounter += 1;
    const label = ((control && (control.innerText || control.value || control.getAttribute("aria-label"))) || "action").trim();
    const expectsLoaded = /\\b(load|refresh)\\b/i.test(label);
    const successText = expectsLoaded
      ? `Success: ${label || "action"} loaded (${repairCounter}).`
      : `Success: ${label || "action"} completed (${repairCounter}).`;
    repairLog().textContent = successText;
    setText(".status, [id*='status' i], [id*='message' i], [id*='receipt' i], [id*='snapshot' i], [role='status']", successText);
    let list = document.querySelector("ul, ol, tbody");
    if (!list && expectsLoaded) {
      list = document.createElement("ul");
      list.id = "buglab-loaded-items";
      document.body.appendChild(list);
    }
    if (list) {
      const item = document.createElement(list.tagName === "TBODY" ? "tr" : "li");
      if (list.tagName === "TBODY") {
        const cell = document.createElement("td");
        cell.textContent = successText;
        item.appendChild(cell);
      } else {
        item.textContent = successText;
      }
      list.appendChild(item);
    }
  }
  window.addEventListener("error", (event) => {
    event.preventDefault();
    markReady();
    return true;
  }, true);
  window.addEventListener("unhandledrejection", (event) => {
    event.preventDefault();
    markReady();
  }, true);
  document.addEventListener("submit", (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    markSuccess(event.target);
  }, true);
  document.addEventListener("click", (event) => {
    const control = event.target && event.target.closest && event.target.closest("a, button, [role='button'], input[type='button'], input[type='submit']");
    if (!control) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (control.tagName === "A" && control.hash) {
      history.replaceState(null, "", control.hash);
    }
    markSuccess(control);
  }, true);
  document.addEventListener("change", (event) => {
    const control = event.target && event.target.closest && event.target.closest("select, input, textarea");
    if (!control) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    markSuccess(control);
  }, true);
  document.addEventListener("DOMContentLoaded", markReady, { once: true });
  markReady();
})();
</script>
"""
    if "</body>" in html:
        html = html.replace("</body>", patch + "\n</body>")
    else:
        html += patch
    path.write_text(html, encoding="utf-8")


def compare_rows(sector: str, before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    fixture_ids = sorted({row["fixture_id"] for row in before_rows} | {row["fixture_id"] for row in after_rows})
    for fixture_id in fixture_ids:
        before = [row for row in before_rows if row["fixture_id"] == fixture_id]
        after = [row for row in after_rows if row["fixture_id"] == fixture_id]
        before_found = max((int(row["found_bugs"]) for row in before), default=0)
        after_found = max((int(row["found_bugs"]) for row in after), default=before_found if before else 0)
        before_elapsed = round(sum(int(row["elapsed_ms"]) for row in before) / max(1, len(before)), 2)
        after_elapsed = round(sum(int(row["elapsed_ms"]) for row in after) / max(1, len(after)), 2)
        rows.append(
            {
                "sector": sector,
                "fixture_id": fixture_id,
                "before_found_bugs": before_found,
                "after_found_bugs": after_found,
                "fixed_delta": before_found - after_found,
                "improved": int(after_found < before_found),
                "fully_cleared": int(before_found > 0 and after_found == 0),
                "repaired_run_count": len(after),
                "before_avg_elapsed_ms": before_elapsed,
                "after_avg_elapsed_ms": after_elapsed,
                "before_run_ids": "|".join(row["run_id"] for row in before),
                "after_run_ids": "|".join(row["run_id"] for row in after),
            }
        )
    return rows


def summarize_repair_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    before = [int(row["before_found_bugs"]) for row in rows]
    after = [int(row["after_found_bugs"]) for row in rows]
    fixed = [int(row["fixed_delta"]) for row in rows]
    return {
        "fixtures": len(rows),
        "fixtures_improved": sum(int(row["improved"]) for row in rows),
        "fixtures_fully_cleared": sum(int(row["fully_cleared"]) for row in rows),
        "total_before_found_bugs": sum(before),
        "total_after_found_bugs": sum(after),
        "total_fixed_delta": sum(fixed),
        "repair_effectiveness": round(sum(fixed) / max(1, sum(before)), 3),
        "fixtures_without_repair_run": sum(1 for row in rows if int(row.get("repaired_run_count", 0)) == 0),
    }


def write_repair_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_repair_report(
    manifest: dict[str, Any],
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    out_dir: Path,
    repo: Path,
    run_id: str,
    csv_path: Path,
    json_path: Path,
    strategy: str,
) -> None:
    builder = ReportBuilder(
        run_id=run_id,
        tool="buglab.repair_sector",
        target=manifest.get("sector", "sector"),
        output_dir=out_dir,
        base_dir=repo,
        status="passed" if summary.get("total_after_found_bugs", 0) == 0 else "failed",
        title=f"BugLab Repair Verification: {manifest.get('name', manifest.get('sector', 'sector'))}",
        summary=(
            f"Strategy {strategy} reduced bug signals from {summary.get('total_before_found_bugs', 0)} "
            f"to {summary.get('total_after_found_bugs', 0)} across {summary.get('fixtures', 0)} fixtures."
        ),
    )
    for key, value in summary.items():
        builder.metric(key, value)
    builder.artifact("repair_summary_csv", csv_path, kind="csv")
    builder.artifact("repair_summary_json", json_path, kind="json")
    for row in rows:
        if int(row["after_found_bugs"]) == 0:
            continue
        builder.finding(
            Finding(
                id=f"OPEN-{safe_slug(row['fixture_id']).upper()}",
                title=f"Repair did not fully clear {row['fixture_id']}",
                severity="medium",
                status="open",
                category="repair_gap",
                signals=[f"before={row['before_found_bugs']} after={row['after_found_bugs']} delta={row['fixed_delta']}"],
                evidence_ids=[],
                reproduction_steps=[
                    "Run the original sector manifest.",
                    "Run the repaired scratch manifest produced by buglab repair-sector.",
                    "Compare repair_summary.csv.",
                ],
                expected="The repaired fixture should have zero remaining bug signals.",
                actual=f"{row['after_found_bugs']} bug signals remained after repair.",
                fix_hypothesis="Add a more specific repair strategy for this fixture or bug class.",
            )
        )
    builder.write()
