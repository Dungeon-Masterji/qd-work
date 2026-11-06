# conversations should run on a fresh system, so we use before/after diffs and
# unique message ids so reruns do not break.
import argparse
import json
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).parents[1]


def payout_list(base_url: str, rider_id: str) -> list[dict]:
    response = httpx.get(
        f"{base_url}/v1/payouts",
        params={"rider_id": rider_id},
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return []


def payout_total(items: list[dict]) -> int:
    return sum(int(item.get("amount", 0)) for item in items if item.get("status") != "rejected")


def pending_for(rider_id: str, service_url: str) -> list[dict]:
    response = httpx.get(f"{service_url.rstrip('/')}/ops/pending", timeout=10.0)
    response.raise_for_status()
    return [item for item in response.json() if item["rider_id"] == rider_id]


def normalize_payouts(items: list[dict]) -> set[tuple]:
    return {
        (
            item.get("payout_id") or item.get("id"),
            item.get("reference"),
            item.get("amount"),
            item.get("status"),
        )
        for item in items
    }


def amounts_match(expected: int, actual: int, expected_options: list[int] | None = None) -> bool:
    if expected_options is not None:
        return actual in expected_options
    return actual == expected


def escalation_matches(required: object, escalation_count: int) -> bool:
    if required == "required":
        return escalation_count > 0
    if required == "optional":
        return True
    return escalation_count == 0


def run_scenarios(service_url: str, payswift_url: str, cases: list[dict], group: str, index: int | None) -> tuple[int, int, list[list[str]]]:
    passed = 0
    rows = []
    start = 0 if index is None else index
    end = len(cases) if index is None else index + 1
    for case_index in range(start, end):
        case = cases[case_index]
        rider_id = case["rider_id"]
        before_payouts = payout_list(payswift_url, rider_id)
        before_pending = pending_for(rider_id, service_url)
        replies = []
        try:
            for turn in case["turns"]:
                if turn.get("from") != "rider":
                    continue
                payload = {
                    "message_id": f"{turn['message_id']}-eval-{case_index}-{group}",
                    "rider_id": rider_id,
                    "text": turn["text"],
                    "received_at": turn["received_at"],
                }
                response = httpx.post(
                    f"{service_url.rstrip('/')}/messages",
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
                replies.append(response.json()["reply"])
        except Exception as error:
            rows.append([group, case["scenario"], "FAIL", str(case.get("expected", {})), f"request failed: {error}"])
            continue

        after_payouts = payout_list(payswift_url, rider_id)
        new_payouts = normalize_payouts(after_payouts) - normalize_payouts(before_payouts)
        actual_payout = sum(
            int(item.get("amount", 0))
            for item in after_payouts
            if (
                item.get("payout_id") or item.get("id"),
                item.get("reference"),
                item.get("amount"),
                item.get("status"),
            ) in new_payouts
        )
        after_pending = pending_for(rider_id, service_url)
        actual_pending = sum(
            item["amount"] or 0
            for item in after_pending
            if item not in before_pending
        )

        expected = case.get("expected", {})
        payout_expected = expected.get("payout")
        approval_expected = expected.get("approval")
        expected_options = None
        if isinstance(expected.get("one_of"), list):
            possible = expected["one_of"]
            payout_expected = actual_payout
            approval_expected = actual_pending
            payout_options = [option["payout"] for option in possible]
            approval_options = [option["approval"] for option in possible]
            valid = (actual_payout in payout_options and actual_pending in approval_options) or (actual_pending in payout_options and actual_payout in approval_options)
            payout_ok = valid
        else:
            payout_ok = payout_expected is None or actual_payout == payout_expected
            approval_ok = approval_expected is None or actual_pending == approval_expected

        if isinstance(expected.get("one_of"), list):
            approval_ok = payout_ok
        mentions_ok = all(
            mention in (replies[-1] if replies else "")
            for mention in expected.get("reply_mentions", [])
        )
        if "escalation" in expected:
            escalation_ok = escalation_matches(
                expected["escalation"],
                sum(item["type"] == "escalation" for item in after_pending if item not in before_pending),
            )
        else:
            escalation_ok = True
        ok = payout_ok and approval_ok and mentions_ok and escalation_ok
        actual_text = f"payout={actual_payout}, approval={actual_pending}"
        if ok:
            passed += 1
        rows.append([group, case["scenario"], "PASS" if ok else "FAIL", str(expected), actual_text])
    return passed, end - start, rows


def print_table(rows: list[list[str]]) -> None:
    headers = ["group", "scenario", "result", "expected", "actual"]
    widths = [max(len(headers[i]), *(len(str(row[i])) for row in rows)) for i in range(len(headers))]
    print(" | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("service_url")
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    payswift_url = __import__("os").environ.get("PAYSWIFT_BASE_URL", "http://localhost:8081")

    files = [(ROOT / "data/conversations.json", "conversations"), (ROOT / "evals/extra_cases.json", "extra_cases")]
    rows = []
    passed = total = 0
    for path, group in files:
        cases = json.loads(path.read_text())
        group_passed, group_total, group_rows = run_scenarios(args.service_url, payswift_url, cases, group, args.index)
        passed += group_passed
        total += group_total
        rows.extend(group_rows)
    print_table(rows)
    print(f"Score: {passed}/{total}")
    return 0 if passed == total and total else 1


if __name__ == "__main__":
    sys.exit(main())
