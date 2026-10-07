"""Halaman detail pelanggan: profil, nilai transaksi, produk favorit, riwayat order dan pembayaran."""
import streamlit as st

from app_pages.common import MONEY, NON_CANCEL, bar, card_title, q, usd

st.title("Detail pelanggan")

daftar = q("""
    SELECT c.customerNumber AS id, c.customerName AS nama,
           EXISTS (SELECT 1 FROM orders o WHERE o.customerNumber = c.customerNumber
                   AND o.status <> 'Cancelled') AS aktif
    FROM customers c ORDER BY c.customerName""")
pick, opt = st.columns([3, 1], vertical_alignment="bottom")
hanya_aktif = opt.toggle("Hanya yang pernah order", value=True, key="pel_aktif")
if hanya_aktif:
    daftar = daftar[daftar.aktif == 1]
label = {r.id: f"{r.nama} ({r.id})" for r in daftar.itertuples()}
cid = pick.selectbox("Pilih pelanggan", list(label), format_func=label.get, key="pel_cust",
                     placeholder="Ketik nama pelanggan")
if cid is None:
    st.stop()

prof = q("""
    SELECT c.customerName, c.city, c.state, c.country, c.creditLimit,
           CONCAT(e.firstName, ' ', e.lastName) AS sales_rep, f.city AS kantor
    FROM customers c
    LEFT JOIN employees e ON e.employeeNumber = c.salesRepEmployeeNumber
    LEFT JOIN offices f ON f.officeCode = e.officeCode
    WHERE c.customerNumber = %s""", (cid,)).iloc[0]
nilai = q(f"""
    SELECT COALESCE(SUM(d.quantityOrdered * d.priceEach), 0) AS penjualan,
           COUNT(DISTINCT o.orderNumber) AS jml_order, MAX(o.orderDate) AS terakhir
    FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
    WHERE o.customerNumber = %s AND {NON_CANCEL}""", (cid,)).iloc[0]
bayar = q("SELECT COALESCE(SUM(amount), 0) AS bayar FROM payments WHERE customerNumber = %s",
          (cid,)).iloc[0].bayar
sisa = (nilai.penjualan or 0) - (bayar or 0)
limit = float(prof.creditLimit or 0)

st.subheader(prof.customerName)
lokasi = ", ".join(str(v) for v in [prof.city, prof.state, prof.country] if v)
with st.container(horizontal=True, gap="small"):
    st.badge(lokasi, icon=":material/location_on:", color="gray")
    rep = (prof.sales_rep or "Tanpa sales rep") + (f" · {prof.kantor}" if prof.kantor else "")
    st.badge(rep, icon=":material/badge:", color="gray")
    st.badge(f"Batas kredit USD {limit:,.0f}", icon=":material/credit_card:", color="gray")

with st.container(horizontal=True):
    st.metric("Total penjualan (USD)", usd(nilai.penjualan), border=True)
    st.metric("Total pembayaran (USD)", usd(bayar), border=True)
    st.metric("Piutang (USD)", usd(sisa), border=True, help="Penjualan dikurangi pembayaran")
    st.metric("Jumlah order", f"{int(nilai.jml_order or 0)}", border=True)
    st.metric("Order terakhir", str(nilai.terakhir or "-"), border=True)
if sisa > limit > 0:
    st.warning(f"Piutang melebihi batas kredit sebesar USD {sisa - limit:,.0f}.", icon=":material/warning:")

orders = q("""
    SELECT o.orderNumber AS no_order, o.orderDate AS tanggal, o.status,
           SUM(d.quantityOrdered * d.priceEach) AS nilai, o.shippedDate AS dikirim,
           o.comments AS catatan
    FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
    WHERE o.customerNumber = %s
    GROUP BY o.orderNumber, o.orderDate, o.status, o.shippedDate, o.comments
    ORDER BY o.orderDate DESC""", (cid,))

left, right = st.columns(2)
with left.container(border=True, height="stretch"):
    card_title("Nilai per order", "USD, urut dari order paling awal")
    if orders.empty:
        st.caption("Pelanggan ini belum pernah order.")
    else:
        bar(orders.sort_values("tanggal"), "no_order", "nilai", "No. order", "Nilai (USD)", sort=None)
with right.container(border=True, height="stretch"):
    card_title("Produk yang paling banyak dibeli", "10 teratas menurut nilai, tanpa order Cancelled")
    prod = q(f"""
        SELECT p.productName AS produk, p.productLine AS lini,
               SUM(d.quantityOrdered) AS unit,
               SUM(d.quantityOrdered * d.priceEach) AS nilai
        FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
        JOIN products p ON p.productCode = d.productCode
        WHERE o.customerNumber = %s AND {NON_CANCEL}
        GROUP BY p.productCode, p.productName, p.productLine
        ORDER BY nilai DESC LIMIT 10""", (cid,))
    st.dataframe(prod, hide_index=True, width="stretch", alt="Produk yang paling banyak dibeli",
                 column_config={"nilai": MONEY})

pays = q("""SELECT checkNumber AS referensi, paymentDate AS tanggal, amount AS nilai
            FROM payments WHERE customerNumber = %s ORDER BY paymentDate DESC""", (cid,))
with st.container(border=True):
    t_order, t_bayar = st.tabs([f"Riwayat order ({len(orders)})", f"Riwayat pembayaran ({len(pays)})"])
    with t_order:
        st.dataframe(orders, hide_index=True, width="stretch", alt="Riwayat order",
                     column_config={"nilai": MONEY, "no_order": st.column_config.NumberColumn(format="%d")})
    with t_bayar:
        st.dataframe(pays, hide_index=True, width="stretch", alt="Riwayat pembayaran",
                     column_config={"nilai": MONEY})
