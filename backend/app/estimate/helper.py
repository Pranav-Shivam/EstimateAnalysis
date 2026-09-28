from app.estimate.schemas import DraftLine, Totals


def compute_totals(lines: list[DraftLine]) -> Totals:
    list_total = 0.0
    discount_total = 0.0
    for line in lines:
        if line.quantity is None or line.unit_price is None:
            continue
        gross = line.unit_price * line.quantity
        list_total += gross
        discount_total += gross * line.discount_pct / 100
    return Totals(
        list_total=round(list_total, 2), discount_total=round(discount_total, 2),
        net_total=round(list_total - discount_total, 2),
    )
