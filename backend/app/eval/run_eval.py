"""Eval harness: run Guardian AI against violation_content_samples.json and
score per-rule precision/recall.

Run:  python -m app.eval.run_eval
"""
from __future__ import annotations

import json
from collections import defaultdict

from app.agents.intake import run_intake
from app.agents.critics import CRITICS
from app.models.schemas import IntakeMetadata, ToolCallTrace
from app.skills import _data


def _run_one_iteration_critics(content: str, intake: IntakeMetadata) -> set[str]:
    audit: list[ToolCallTrace] = []
    found: set[str] = set()
    for name, fn in CRITICS.items():
        verdict = fn(content=content, intake=intake, audit=audit, iteration=1)
        for v in verdict.violations:
            found.add(v.rule_id)
    return found


def evaluate() -> dict:
    import sys, time
    samples = _data.violation_samples().get("samples", [])
    per_rule = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    per_sample = []
    overall_tp = overall_fp = overall_fn = 0

    for i, s in enumerate(samples, 1):
        t0 = time.time()
        print(f"[eval] {i}/{len(samples)} {s['sample_id']} ...",
              file=sys.stderr, flush=True)
        content = s["content"]
        intake = run_intake(
            content,
            channel_hint=s.get("channel"),
            audience_hint=s.get("target_audience"),
            offer_id_hint=s.get("associated_offer_id"),
        )
        expected = {v["rule_id"] for v in s.get("planted_violations", [])}
        found = _run_one_iteration_critics(content, intake)
        tp = expected & found
        fp = found - expected
        fn = expected - found
        for rid in tp:
            per_rule[rid]["tp"] += 1
        for rid in fp:
            per_rule[rid]["fp"] += 1
        for rid in fn:
            per_rule[rid]["fn"] += 1
        overall_tp += len(tp)
        overall_fp += len(fp)
        overall_fn += len(fn)
        per_sample.append({
            "sample_id": s["sample_id"],
            "channel": s.get("channel"),
            "expected": sorted(expected),
            "found": sorted(found),
            "tp": sorted(tp),
            "fp": sorted(fp),
            "fn": sorted(fn),
        })
        print(f"[eval]   done in {time.time()-t0:.1f}s "
              f"tp={len(tp)} fp={len(fp)} fn={len(fn)}",
              file=sys.stderr, flush=True)

    def f1(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        f = 2 * p * r / (p + r) if p + r else 0
        return round(p, 3), round(r, 3), round(f, 3)

    p, r, f = f1(overall_tp, overall_fp, overall_fn)
    rule_summary = {
        rid: {**c, **dict(zip(["precision", "recall", "f1"],
                              f1(c["tp"], c["fp"], c["fn"])))}
        for rid, c in per_rule.items()
    }
    return {
        "overall": {"tp": overall_tp, "fp": overall_fp, "fn": overall_fn,
                    "precision": p, "recall": r, "f1": f},
        "per_rule": rule_summary,
        "per_sample": per_sample,
    }


if __name__ == "__main__":
    import sys
    result = evaluate()
    json.dump(result, sys.stdout, indent=2, default=str)
    print()
