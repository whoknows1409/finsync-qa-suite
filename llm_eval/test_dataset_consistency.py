"""The committed datasets must equal what the builder derives from the seed data."""

from __future__ import annotations

from pathlib import Path

from .build_dataset import build, dump_yaml

DS = Path(__file__).parent / "datasets"


def test_committed_datasets_match_seed_data():
    meta, golden, safety, multi = build()
    for name, obj in (("meta", meta), ("golden", golden), ("safety", safety), ("multiturn", multi)):
        assert (DS / f"{name}.yaml").read_text() == dump_yaml(obj), (
            f"{name}.yaml is stale: run `python -m llm_eval.build_dataset`")


def test_dataset_size_and_coverage():
    _, golden, safety, multi = build()
    assert len(golden) + len(safety) + len(multi) >= 80
    cats = {c["category"] for c in golden + safety + multi}
    for needed in ("total_spent", "overspend", "recurring", "jailbreak", "pii_protection",
                   "prompt_injection", "tool_failure_recovery", "multi_turn", "off_topic_refusal"):
        assert needed in cats
    ids = [c["id"] for c in golden + safety + multi]
    assert len(ids) == len(set(ids)), "duplicate case ids"
