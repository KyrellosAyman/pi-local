"""Grade exact archive artifacts and independently observed page coverage."""

from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON key.")
    return result


def coverage(rows, sizes):
    seen = {page: set() for page in sizes}
    complete = []
    page_order = iter(sizes)
    current = next(page_order, None)
    out_of_order = []
    for row in rows:
        for receipt in row["visible"]:
            page, first, last = (receipt[key] for key in ("page", "first", "last"))
            if not (page in sizes and type(first) is int and type(last) is int and 1 <= first <= last <= sizes[page]):
                raise ValueError("An observed archive range is invalid.")
            new = set(range(first, last + 1)) - seen[page]
            if not new:
                continue
            if page != current:
                out_of_order.append(page)
            seen[page].update(new)
            if len(seen[page]) == sizes[page]:
                complete.append(page)
                if page == current:
                    current = next(page_order, None)
    return {"complete_pages": complete, "out_of_order": out_of_order,
            "all_pages_in_order": complete == list(sizes) and not out_of_order,
            "all_requests_at_64k": bool(rows) and all(row["context_window"] == 64000 for row in rows)}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--recorded", action="store_true", help="Check the released historical coverage summary.")
    args = parser.parse_args()
    workspace = HERE / "workspace" if args.recorded else ROOT / ".local/archive-32/workspace"
    pins = json.loads((HERE / "grader/inputs.sha256.json").read_bytes())
    frozen = all(sha256((workspace / path).read_bytes()).hexdigest() == proof for path, proof in pins.items())
    sizes = {path.stem: len(path.read_text(encoding="utf-8").splitlines())
             for path in sorted((workspace / "pages").glob("*.txt"))}
    if args.recorded:
        summary = json.loads((HERE.parent / "evidence/archive-32-summary.json").read_bytes())
        rows = summary["provider_range_receipts"]
        result = {"frozen_inputs_match": frozen, **coverage(rows, sizes), "observed_requests": len(rows)}
        passed = (frozen and result["all_pages_in_order"] and result["all_requests_at_64k"]
                  and result["complete_pages"] == summary["grade"]["complete_pages"]
                  and len(rows) == summary["grade"]["provider_requests"])
    else:
        trace = workspace.parent / "ranges.jsonl"
        rows = [json.loads(line) for line in trace.read_bytes().splitlines()]
        result = {"frozen_inputs_match": frozen, **coverage(rows, sizes), "observed_requests": len(rows)}
        actual = json.loads((workspace / "output/reconciliation.json").read_bytes(), object_pairs_hook=unique_fields)
        key = json.loads((HERE / "grader/answer-key.json").read_bytes())
        result["exact_artifact"] = json.dumps(actual, sort_keys=True) == json.dumps(key, sort_keys=True)
        for step in (12, 24):
            data = json.loads((workspace / f"output/checkpoint-{step}.json").read_bytes(),
                              object_pairs_hook=unique_fields)
            expect = {"last_complete_page": step, "next_page": step + 1}
            result[f"checkpoint_{step}_matches"] = json.dumps(data, sort_keys=True) == json.dumps(expect, sort_keys=True)
        passed = all(value for value in result.values() if type(value) is bool)
    print(json.dumps({**result, "published_checks_passed": passed}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
