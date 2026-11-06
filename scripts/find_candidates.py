import os
import sys
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal

import psycopg

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.services.ledger import reconcile_ledger


def main() -> None:
    cutoff = date(2026, 9, 23)
    start = cutoff - timedelta(days=7)
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://qdwork:qdwork@localhost:5432/qdwork",
    )
    connection = psycopg.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rider_id FROM riders ORDER BY rider_id")
            riders = [row[0] for row in cursor.fetchall()]

        for rider_id in riders:
            findings = []
            total = Decimal("0")
            current = start
            while current < cutoff:
                result = reconcile_ledger(
                    connection,
                    rider_id,
                    payout_date=current,
                )
                if result.difference > 0:
                    total += result.difference
                    findings.extend(result.findings)
                current += timedelta(days=1)

            separate_findings = {finding.trip_id or finding.date for finding in findings if finding.trip_id or finding.date}
            if (
                total == Decimal("200")
                or total == Decimal("201")
                or Decimal("190") <= total <= Decimal("210")
                or len(separate_findings) >= 2
            ):
                categories = []
                if total == Decimal("200"):
                    categories.append("exactly 200")
                if total == Decimal("201"):
                    categories.append("exactly 201")
                if Decimal("190") <= total <= Decimal("210"):
                    categories.append("190-210")
                if len(separate_findings) >= 2:
                    categories.append("2+ findings")
                print(
                    f"{rider_id}, total={total}, findings={len(separate_findings)}, "
                    f"{'; '.join(categories)}"
                )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
