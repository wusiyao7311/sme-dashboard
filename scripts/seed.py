from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models import Base, Product, Customer, Order, OrderItem, Invoice, Setting
from app.db import get_engine


def make_products(rng: random.Random) -> list[Product]:
    categories = ["Kaffee", "Tee", "Zubehör", "Geschenksets"]
    names = [
        "Arabica Röstung", "Entkoffeiniert", "Espresso Blend", "Filterkaffee",
        "Grüner Tee", "Oolong", "Kamille", "Ingwer-Zitrone",
        "Kaffeemühle", "Espressokanne", "Kaffeebecher", "Teezylinder",
        "Kaffeeservice", "Tee-Set", "Geschenkbox Kaffee", "Geschenkbox Tee",
        "Kaffee-Abonnement", "Tee-Abonnement", "Kaffee-Filter", "Tee-Filter",
        "Kaffee-Beutel", "Tee-Beutel", "Kaffee-Box", "Tee-Box", "Kaffee-Geschenk",
    ]
    products = []
    for i in range(25):
        cat = categories[i % 4]
        price = round(rng.uniform(5, 120), 2)
        threshold = rng.randint(10, 25)
        stock = rng.randint(0, 200)
        products.append(Product(
            id=i + 1,
            name=f"{names[i]} {i+1}",
            sku=f"SKU-{i+1:03d}",
            category=cat,
            price=price,
            stock_qty=stock,
            low_stock_threshold=threshold,
        ))
    # Ensure exactly 4 products are below threshold
    below = [p for p in products if p.stock_qty < p.low_stock_threshold]
    if len(below) < 4:
        for p in products:
            if p in below:
                continue
            p.stock_qty = p.low_stock_threshold - 1
            below.append(p)
            if len(below) == 4:
                break
    elif len(below) > 4:
        for p in below[4:]:
            p.stock_qty = p.low_stock_threshold + rng.randint(1, 50)
    return products


def make_customers(rng: random.Random, end_date: date) -> list[Customer]:
    first_names = ["Anna", "Lukas", "Maria", "Felix", "Julia", "Max", "Sophie", "Leon", "Emma", "Paul",
                   "Lena", "Jonas", "Mia", "Ben", "Hannah", "David", "Clara", "Tim", "Marie", "Nico"]
    last_names = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker",
                  "Schulz", "Hoffmann", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Neumann",
                  "Schwarz", "Zimmermann", "Braun", "Krüger"]
    cities = ["Berlin", "Hamburg", "München", "Köln", "Frankfurt", "Stuttgart", "Düsseldorf",
              "Dortmund", "Essen", "Leipzig", "Bremen", "Dresden", "Hannover", "Nürnberg", "Bonn"]
    customers = []
    start_date = end_date - timedelta(days=365)
    for i in range(120):
        first = rng.choice(first_names)
        last = rng.choice(last_names)
        city = rng.choice(cities)
        created = start_date + timedelta(days=0 if i < 30 else rng.randint(0, 330))
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        customers.append(Customer(
            id=i + 1,
            name=f"{first} {last}",
            email=email,
            city=city,
            created_at=datetime(created.year, created.month, created.day, 12, 0, 0),
        ))
    return customers


def make_orders(rng: random.Random, products: list[Product], customers: list[Customer],
                end_date: date) -> list[Order]:
    orders = []
    start_date = end_date - timedelta(days=365)
    # Weighted customer selection: some customers buy more
    customer_weights = [1] * 120
    for _ in range(30):
        idx = rng.randint(0, 119)
        customer_weights[idx] += rng.randint(2, 5)
    total_weight = sum(customer_weights)
    customer_probs = [w / total_weight for w in customer_weights]

    # Seasonality weights by month (1-12)
    month_weights = [1.2, 1.0, 0.9, 0.8, 0.7, 0.6, 0.6, 0.7, 0.8, 1.0, 1.3, 1.5]
    # Weekday weights (Mon-Sun)
    weekday_weights = [1.2, 1.2, 1.2, 1.2, 1.3, 1.1, 0.7]

    order_count = 1500
    while len(orders) < order_count:
        # Pick a random day in the 12-month range
        day_offset = rng.randint(0, 365)
        order_date = start_date + timedelta(days=day_offset)
        # Apply seasonality and weekday bias by rejection sampling
        for _ in range(10):
            month = order_date.month
            weekday = order_date.weekday()
            prob = month_weights[month - 1] * weekday_weights[weekday]
            if rng.random() < prob / 1.5:
                break
            day_offset = rng.randint(0, 365)
            order_date = start_date + timedelta(days=day_offset)

        # Pick customer weighted
        # Only customers who already signed up can order
        eligible = [i for i, c in enumerate(customers) if c.created_at.date() <= order_date]
        cust_idx = rng.choices(eligible, weights=[customer_probs[i] for i in eligible], k=1)[0]
        customer = customers[cust_idx]

        # 3% cancelled
        status = "cancelled" if rng.random() < 0.03 else "completed"

        # 1-4 items
        num_items = rng.randint(1, 4)
        items = []
        total = Decimal("0.00")
        for _ in range(num_items):
            prod = rng.choice(products)
            qty = rng.randint(1, 3)
            unit_price = prod.price
            total += Decimal(str(unit_price)) * qty
            items.append((prod.id, qty, unit_price))
        total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        orders.append(Order(
            id=len(orders) + 1,
            customer_id=customer.id,
            order_date=order_date,
            total=float(total),
            status=status,
        ))
        # Store items temporarily
        orders[-1]._items = items  # type: ignore
    return orders


def make_invoices(rng: random.Random, orders: list[Order], end_date: date) -> list[Invoice]:
    invoices = []
    completed_orders = [o for o in orders if o.status == "completed"]
    # Determine overdue and open counts
    overdue_count = rng.randint(6, 10)
    open_count = max(5, rng.randint(5, 10))

    # Sort completed orders by order_date
    completed_sorted = sorted(completed_orders, key=lambda o: o.order_date)

    # Identify orders that are old (>30 days) vs recent
    old_orders = [o for o in completed_sorted if (end_date - o.order_date).days > 30]
    recent_orders = [o for o in completed_sorted if (end_date - o.order_date).days <= 30]

    # Choose overdue from old orders
    overdue_indices = set()
    if old_orders:
        num_overdue = min(overdue_count, len(old_orders))
        selected = rng.sample(range(len(old_orders)), num_overdue)
        for idx in selected:
            overdue_indices.add(id(old_orders[idx]))

    # Choose open from recent orders (due_date in future)
    open_indices = set()
    future_due = [o for o in recent_orders if (o.order_date + timedelta(days=14)) > end_date]
    if future_due:
        num_open = min(open_count, len(future_due))
        selected = rng.sample(range(len(future_due)), num_open)
        for idx in selected:
            open_indices.add(id(future_due[idx]))

    for order in completed_sorted:
        issue_date = order.order_date
        due_date = order.order_date + timedelta(days=14)
        oid = id(order)

        if oid in overdue_indices:
            status = "overdue"
            reminder_sent_at = None
        elif oid in open_indices:
            status = "open"
            reminder_sent_at = None
        elif due_date > end_date:
            status = "open"
            reminder_sent_at = None
        else:
            status = "paid"
            reminder_sent_at = None

        invoices.append(Invoice(
            order_id=order.id,
            issue_date=issue_date,
            due_date=due_date,
            amount=order.total,
            status=status,
            reminder_sent_at=reminder_sent_at,
        ))
    return invoices


def make_settings() -> list[Setting]:
    return [
        Setting(key="summary_email_recipients", value="owner@example.com"),
        Setting(key="summary_schedule", value="weekly"),
        Setting(key="default_low_stock_threshold", value="10"),
        Setting(key="language", value="de"),
    ]


def main() -> None:
    rng = random.Random(42)
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    end_date = date.today()
    products = make_products(rng)
    customers = make_customers(rng, end_date)
    orders = make_orders(rng, products, customers, end_date)
    invoices = make_invoices(rng, orders, end_date)
    settings = make_settings()

    with Session(engine) as session:
        session.bulk_save_objects(products)
        session.bulk_save_objects(customers)
        session.bulk_save_objects(orders)
        # Create order items
        order_items = []
        for order in orders:
            for prod_id, qty, unit_price in order._items:  # type: ignore
                order_items.append(OrderItem(
                    order_id=order.id,
                    product_id=prod_id,
                    qty=qty,
                    unit_price=unit_price,
                ))
        session.bulk_save_objects(order_items)
        session.bulk_save_objects(invoices)
        session.bulk_save_objects(settings)
        session.commit()

    print(f"Products: {len(products)}")
    print(f"Customers: {len(customers)}")
    print(f"Orders: {len(orders)}")
    print(f"Order Items: {len(order_items)}")
    print(f"Invoices: {len(invoices)}")
    print(f"Settings: {len(settings)}")


if __name__ == "__main__":
    main()
