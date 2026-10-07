"""
Verifikasi classicmodels setelah sql/02_setup.sql. Memakai user read-only llm_reader,
jadi sekaligus menguji hak akses: boleh membaca, tidak boleh mengubah, dan tidak
boleh melihat kolom data pribadi.

Jalankan:  python verify_db.py
"""
import sys

import mysql.connector

from core import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHECKS = [
    ("Jumlah baris per tabel", """
        SELECT 'productlines' AS tabel, COUNT(*) AS baris FROM productlines
        UNION ALL SELECT 'products', COUNT(*) FROM products
        UNION ALL SELECT 'offices', COUNT(*) FROM offices
        UNION ALL SELECT 'employees', COUNT(*) FROM employees
        UNION ALL SELECT 'customers', COUNT(*) FROM customers
        UNION ALL SELECT 'payments', COUNT(*) FROM payments
        UNION ALL SELECT 'orders', COUNT(*) FROM orders
        UNION ALL SELECT 'orderdetails', COUNT(*) FROM orderdetails"""),

    ("Rentang tanggal order dan pembayaran", """
        SELECT 'orders', MIN(orderDate), MAX(orderDate) FROM orders
        UNION ALL SELECT 'payments', MIN(paymentDate), MAX(paymentDate) FROM payments"""),

    ("Status order", "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY 2 DESC"),

    ("Pelanggan: terdaftar vs pernah order (contoh soal ambigu)", """
        SELECT COUNT(*) AS terdaftar,
               (SELECT COUNT(DISTINCT customerNumber) FROM orders WHERE status <> 'Cancelled') AS pernah_order
        FROM customers"""),

    ("Penjualan vs pembayaran tahun 2004 (contoh 'pendapatan' yang ambigu)", """
        SELECT (SELECT ROUND(SUM(d.quantityOrdered * d.priceEach), 2) FROM orderdetails d
                JOIN orders o ON o.orderNumber = d.orderNumber
                WHERE o.status <> 'Cancelled' AND YEAR(o.orderDate) = 2004) AS penjualan_2004,
               (SELECT ROUND(SUM(amount), 2) FROM payments WHERE YEAR(paymentDate) = 2004) AS pembayaran_2004"""),

    ("Total piutang (penjualan dikurangi pembayaran)", """
        SELECT ROUND(SUM(t.penjualan - COALESCE(p.bayar, 0)), 2) AS piutang,
               SUM(t.penjualan - COALESCE(p.bayar, 0) > 0.01) AS pelanggan_berpiutang
        FROM (SELECT o.customerNumber, SUM(d.quantityOrdered * d.priceEach) AS penjualan
              FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
              WHERE o.status <> 'Cancelled' GROUP BY o.customerNumber) t
        LEFT JOIN (SELECT customerNumber, SUM(amount) AS bayar FROM payments
                   GROUP BY customerNumber) p ON p.customerNumber = t.customerNumber"""),

    ("Kolom customers yang terlihat oleh llm_reader", """
        SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'customers'"""),
]

FORBIDDEN = [
    ("DELETE", "DELETE FROM payments WHERE customerNumber = -1"),
    ("SELECT kolom telepon pelanggan", "SELECT phone FROM customers LIMIT 1"),
    ("SELECT email karyawan", "SELECT email FROM employees LIMIT 1"),
    ("SELECT * pada customers", "SELECT * FROM customers LIMIT 1"),
]


def fmt(v):
    return float(v) if hasattr(v, "is_finite") else v


def main():
    conn = mysql.connector.connect(
        host=config.DB_HOST, port=config.DB_PORT, database=config.DB_NAME,
        user=config.DB_READER_USER, password=config.DB_READER_PASSWORD,
    )
    cur = conn.cursor()
    for title, sql in CHECKS:
        cur.execute(sql)
        print(f"\n== {title}")
        for row in cur.fetchall():
            print("  ", tuple(fmt(v) for v in row))

    print("\n== Uji hak akses llm_reader (semua harus DITOLAK)")
    all_ok = True
    for label, sql in FORBIDDEN:
        try:
            cur.execute(sql)
            cur.fetchall()
            all_ok = False
            print(f"   GAGAL, diizinkan: {label}")
        except mysql.connector.Error as e:
            print(f"   OK, ditolak: {label}  ({e.msg})")
    print("\nSemua uji hak akses lolos." if all_ok else "\nPeriksa GRANT di sql/02_setup.sql.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
