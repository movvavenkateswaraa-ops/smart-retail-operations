# Smart Retail Operations

A simple base project for managing a retail store: inventory, billing, low-stock alerts and sales reports.

## Features
- Inventory management (add, list and restock products)
- Billing / point of sale with automatic stock updates and printed receipts
- Low-stock alerts with reorder suggestions
- Sales reports: daily summary, top sellers, revenue by category

## Requirements
- Python 3.8 or newer
- No extra packages (uses only the standard library, including SQLite)

## How to run
Interactive menu (creates `retail.db` in the same folder):

    python smart_retail.py

Demo mode (loads sample data, prints all reports, saves nothing):

    python smart_retail.py --demo

## Project files
- `smart_retail.py` : the complete application
- `README.md` : this file
