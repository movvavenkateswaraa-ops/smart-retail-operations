"""
Smart Retail Operations - simple base project
---------------------------------------------
Features:
  1. Inventory management (add / list / restock products)
  2. Billing / point of sale (multi-item bills, stock auto-update)
  3. Low-stock alerts and reorder suggestions
  4. Sales reports (daily summary, top sellers, revenue)

Run:   python smart_retail.py          (interactive menu)
Demo:  python smart_retail.py --demo   (loads sample data and prints reports)
Needs only the Python 3.8+ standard library.
"""

import sqlite3
import sys
from datetime import datetime, date

DB_FILE = "retail.db"
LOW_STOCK_LEVEL = 10  # default threshold for alerts


# ----------------------------------------------------------------------
# Database setup
# ----------------------------------------------------------------------
def get_conn(db_file=DB_FILE):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            category    TEXT DEFAULT 'General',
            price       REAL NOT NULL CHECK (price >= 0),
            stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
            reorder_lvl INTEGER NOT NULL DEFAULT 10
        );

        CREATE TABLE IF NOT EXISTS sales (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_time  TEXT NOT NULL,
            customer   TEXT DEFAULT 'Walk-in',
            total      REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sale_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id    INTEGER NOT NULL REFERENCES sales(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            qty        INTEGER NOT NULL CHECK (qty > 0),
            unit_price REAL NOT NULL
        );
        """
    )
    conn.commit()


# ----------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------
def add_product(conn, name, price, stock=0, category="General", reorder_lvl=LOW_STOCK_LEVEL):
    try:
        cur = conn.execute(
            "INSERT INTO products (name, category, price, stock, reorder_lvl) VALUES (?,?,?,?,?)",
            (name.strip(), category.strip(), float(price), int(stock), int(reorder_lvl)),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"Product '{name}' already exists or has invalid values.")


def restock(conn, product_id, qty):
    if qty <= 0:
        raise ValueError("Restock quantity must be positive.")
    cur = conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (qty, product_id))
    if cur.rowcount == 0:
        raise ValueError("Product not found.")
    conn.commit()


def list_products(conn):
    return conn.execute("SELECT * FROM products ORDER BY category, name").fetchall()


def print_products(conn):
    rows = list_products(conn)
    if not rows:
        print("No products yet.")
        return
    print(f"\n{'ID':<4}{'Name':<24}{'Category':<14}{'Price':>9}{'Stock':>7}")
    print("-" * 58)
    for r in rows:
        flag = "  <-- LOW" if r["stock"] <= r["reorder_lvl"] else ""
        print(f"{r['id']:<4}{r['name']:<24}{r['category']:<14}{r['price']:>9.2f}{r['stock']:>7}{flag}")


# ----------------------------------------------------------------------
# Billing
# ----------------------------------------------------------------------
def create_sale(conn, items, customer="Walk-in"):
    """
    items: list of (product_id, qty)
    Validates stock, writes the bill, and reduces inventory in one transaction.
    Returns the new sale id.
    """
    if not items:
        raise ValueError("Cart is empty.")

    try:
        total = 0.0
        priced = []
        for pid, qty in items:
            p = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if p is None:
                raise ValueError(f"Product id {pid} not found.")
            if qty <= 0:
                raise ValueError("Quantity must be positive.")
            if p["stock"] < qty:
                raise ValueError(f"Not enough stock for '{p['name']}' (have {p['stock']}, need {qty}).")
            total += p["price"] * qty
            priced.append((pid, qty, p["price"]))

        cur = conn.execute(
            "INSERT INTO sales (sale_time, customer, total) VALUES (?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), customer, round(total, 2)),
        )
        sale_id = cur.lastrowid
        for pid, qty, price in priced:
            conn.execute(
                "INSERT INTO sale_items (sale_id, product_id, qty, unit_price) VALUES (?,?,?,?)",
                (sale_id, pid, qty, price),
            )
            conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, pid))
        conn.commit()
        return sale_id
    except Exception:
        conn.rollback()
        raise


def print_bill(conn, sale_id):
    sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    lines = conn.execute(
        """SELECT p.name, si.qty, si.unit_price
           FROM sale_items si JOIN products p ON p.id = si.product_id
           WHERE si.sale_id = ?""",
        (sale_id,),
    ).fetchall()
    print("\n" + "=" * 44)
    print(f"  SMART RETAIL - BILL #{sale['id']}")
    print(f"  {sale['sale_time']}   Customer: {sale['customer']}")
    print("=" * 44)
    for l in lines:
        print(f"  {l['name']:<20}{l['qty']:>3} x {l['unit_price']:>7.2f} = {l['qty'] * l['unit_price']:>8.2f}")
    print("-" * 44)
    print(f"  {'TOTAL':<30}{sale['total']:>12.2f}")
    print("=" * 44)


# ----------------------------------------------------------------------
# Alerts and reorder suggestions
# ----------------------------------------------------------------------
def low_stock(conn):
    return conn.execute(
        "SELECT * FROM products WHERE stock <= reorder_lvl ORDER BY stock"
    ).fetchall()


def reorder_suggestions(conn, days=30):
    """Suggest quantity to order = (units sold in last `days`) - current stock, min reorder_lvl*2."""
    rows = conn.execute(
        """SELECT p.id, p.name, p.stock, p.reorder_lvl,
                  COALESCE(SUM(si.qty), 0) AS sold
           FROM products p
           LEFT JOIN sale_items si ON si.product_id = p.id
           LEFT JOIN sales s ON s.id = si.sale_id
                AND s.sale_time >= datetime('now', ?)
           WHERE p.stock <= p.reorder_lvl
           GROUP BY p.id""",
        (f"-{days} days",),
    ).fetchall()
    out = []
    for r in rows:
        need = max(r["sold"] - r["stock"], r["reorder_lvl"] * 2 - r["stock"])
        out.append((r["name"], r["stock"], r["sold"], need))
    return out


def print_alerts(conn):
    items = low_stock(conn)
    if not items:
        print("\nAll products are sufficiently stocked.")
        return
    print("\n!! LOW STOCK ALERTS !!")
    for p in items:
        print(f"  - {p['name']}: {p['stock']} left (reorder level {p['reorder_lvl']})")
    print("\nSuggested reorders:")
    for name, stock, sold, need in reorder_suggestions(conn):
        print(f"  - {name}: order ~{need} units (stock {stock}, sold last 30d {sold})")


# ----------------------------------------------------------------------
# Reports
# ----------------------------------------------------------------------
def daily_report(conn, day=None):
    day = day or date.today().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) AS bills, COALESCE(SUM(total),0) AS revenue FROM sales WHERE sale_time LIKE ?",
        (day + "%",),
    ).fetchone()
    print(f"\n--- Daily report for {day} ---")
    print(f"Bills: {row['bills']}   Revenue: {row['revenue']:.2f}")
    if row["bills"]:
        print(f"Average bill: {row['revenue'] / row['bills']:.2f}")


def top_sellers(conn, limit=5):
    rows = conn.execute(
        """SELECT p.name, SUM(si.qty) AS units, SUM(si.qty * si.unit_price) AS revenue
           FROM sale_items si JOIN products p ON p.id = si.product_id
           GROUP BY p.id ORDER BY units DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    print("\n--- Top sellers ---")
    if not rows:
        print("No sales yet.")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['name']:<22} {r['units']:>4} units   {r['revenue']:>9.2f}")


def category_report(conn):
    rows = conn.execute(
        """SELECT p.category, SUM(si.qty * si.unit_price) AS revenue
           FROM sale_items si JOIN products p ON p.id = si.product_id
           GROUP BY p.category ORDER BY revenue DESC"""
    ).fetchall()
    print("\n--- Revenue by category ---")
    if not rows:
        print("No sales yet.")
    for r in rows:
        print(f"{r['category']:<16}{r['revenue']:>10.2f}")


# ----------------------------------------------------------------------
# Demo data
# ----------------------------------------------------------------------
def load_demo(conn):
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
        return
    sample = [
        ("Rice 1kg", 62.0, 50, "Grocery", 15),
        ("Milk 1L", 28.0, 30, "Dairy", 10),
        ("Bread", 35.0, 20, "Bakery", 8),
        ("Soap", 40.0, 25, "Personal Care", 10),
        ("Notebook", 55.0, 12, "Stationery", 10),
        ("Pen (pack)", 90.0, 8, "Stationery", 10),
    ]
    for n, p, s, c, r in sample:
        add_product(conn, n, p, s, c, r)
    create_sale(conn, [(1, 3), (2, 2), (3, 1)], "Anita")
    create_sale(conn, [(5, 4), (6, 2)], "Ravi")
    create_sale(conn, [(4, 2), (2, 5)])


# ----------------------------------------------------------------------
# Interactive menu
# ----------------------------------------------------------------------
def ask_int(prompt):
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Please enter a whole number.")


def ask_float(prompt):
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Please enter a number.")


def billing_flow(conn):
    print_products(conn)
    customer = input("\nCustomer name (Enter for Walk-in): ").strip() or "Walk-in"
    cart = []
    while True:
        pid = input("Product ID (blank to finish): ").strip()
        if not pid:
            break
        if not pid.isdigit():
            print("Enter a valid product ID.")
            continue
        qty = ask_int("Quantity: ")
        cart.append((int(pid), qty))
    try:
        sale_id = create_sale(conn, cart, customer)
        print_bill(conn, sale_id)
    except ValueError as e:
        print(f"Could not create bill: {e}")


def menu(conn):
    options = """
===== SMART RETAIL OPERATIONS =====
1. View products
2. Add product
3. Restock product
4. New bill (sale)
5. Low-stock alerts
6. Daily sales report
7. Top sellers & category revenue
0. Exit
"""
    while True:
        print(options)
        choice = input("Choose: ").strip()
        try:
            if choice == "1":
                print_products(conn)
            elif choice == "2":
                name = input("Name: ")
                cat = input("Category: ") or "General"
                price = ask_float("Price: ")
                stock = ask_int("Opening stock: ")
                lvl = ask_int("Reorder level: ")
                add_product(conn, name, price, stock, cat, lvl)
                print("Product added.")
            elif choice == "3":
                print_products(conn)
                restock(conn, ask_int("Product ID: "), ask_int("Quantity to add: "))
                print("Stock updated.")
            elif choice == "4":
                billing_flow(conn)
            elif choice == "5":
                print_alerts(conn)
            elif choice == "6":
                daily_report(conn)
            elif choice == "7":
                top_sellers(conn)
                category_report(conn)
            elif choice == "0":
                print("Goodbye!")
                break
            else:
                print("Invalid choice.")
        except ValueError as e:
            print(f"Error: {e}")


def main():
    demo = "--demo" in sys.argv
    conn = get_conn(":memory:" if demo else DB_FILE)
    init_db(conn)
    if demo:
        load_demo(conn)
        print_products(conn)
        print_bill(conn, 1)
        daily_report(conn)
        top_sellers(conn)
        category_report(conn)
        print_alerts(conn)
    else:
        menu(conn)
    conn.close()


if __name__ == "__main__":
    main()
