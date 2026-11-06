import uuid

import httpx


BASE_URL = "http://localhost:8081"


def post(client: httpx.Client, rider_id: str, key: str | None = None) -> int:
    headers = {"Idempotency-Key": key} if key else {}
    response = client.post(
        f"{BASE_URL}/v1/payouts",
        headers=headers,
        json={
            "rider_id": rider_id,
            "amount": 25,
            "reference": f"probe {rider_id}",
        },
        timeout=10.0,
    )
    return response.status_code


def main() -> None:
    with httpx.Client() as client:
        normal_rider = f"PROBE-{uuid.uuid4().hex[:8]}"
        print("normal", post(client, normal_rider))

        duplicate_rider = f"PROBE-{uuid.uuid4().hex[:8]}"
        duplicate_key = f"probe-key-{uuid.uuid4().hex}"
        print("same key first", post(client, duplicate_rider, duplicate_key))
        print("same key second", post(client, duplicate_rider, duplicate_key))

        burst_rider = f"PROBE-{uuid.uuid4().hex[:8]}"
        for index in range(20):
            print(
                f"burst {index + 1:02}",
                post(client, burst_rider, f"burst-{uuid.uuid4().hex}"),
            )


if __name__ == "__main__":
    main()
