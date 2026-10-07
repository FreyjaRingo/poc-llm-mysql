"""Halaman ringkasan: KPI, tren penjualan, lini produk, pelanggan dan sales rep teratas."""
import altair as alt
import streamlit as st

from app_pages.common import MONEY, NON_CANCEL, SERIES, bar, card_title, q, usd

head, filt = st.columns([3, 2], vertical_alignment="bottom")
head.title("Ringkasan penjualan")
years = q("SELECT DISTINCT YEAR(orderDate) AS y FROM orders ORDER BY y")["y"].tolist()
with filt.container(horizontal_alignment="right"):
    pilih = st.segmented_control("Tahun", ["Semua"] + [str(y) for y in years], default="Semua",
                                 key="tahun", label_visibility="collapsed")
if pilih in (None, "Semua"):
    f_year, p_year = "", ()
else:
    f_year, p_year = " AND YEAR(o.orderDate) = %s", (int(pilih),)

kpi = q(f"""
    SELECT SUM(d.quantityOrdered * d.priceEach) AS penjualan,
           COUNT(DISTINCT o.orderNumber) AS jml_order,
           COUNT(DISTINCT o.customerNumber) AS pelanggan_aktif
    FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
    WHERE {NON_CANCEL}{f_year}""", p_year).iloc[0]
piutang = q(f"""
    SELECT SUM(t.penjualan - COALESCE(p.bayar, 0)) AS piutang
    FROM (SELECT o.customerNumber, SUM(d.quantityOrdered * d.priceEach) AS penjualan
          FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
          WHERE {NON_CANCEL} GROUP BY o.customerNumber) t
    LEFT JOIN (SELECT customerNumber, SUM(amount) AS bayar FROM payments
               GROUP BY customerNumber) p ON p.customerNumber = t.customerNumber""").iloc[0]
bulanan = q(f"""
    SELECT DATE_FORMAT(o.orderDate, '%Y-%m') AS bulan,
           SUM(d.quantityOrdered * d.priceEach) AS penjualan,
           COUNT(DISTINCT o.orderNumber) AS jml_order
    FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
    WHERE {NON_CANCEL}{f_year} GROUP BY bulan ORDER BY bulan""", p_year)

avg = (kpi.penjualan / kpi.jml_order) if kpi.jml_order else None
k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.metric("Penjualan (USD)", usd(kpi.penjualan), border=True,
              chart_data=bulanan.penjualan.tolist(), chart_type="area",
              help="Total quantityOrdered × priceEach, tanpa order Cancelled. Grafik kecil: per bulan",
              height="stretch")
with k2:
    st.metric("Jumlah order", f"{int(kpi.jml_order or 0):,}", border=True,
              chart_data=bulanan.jml_order.tolist(), chart_type="bar", height="stretch")
with k3:
    st.metric("Pelanggan aktif", f"{int(kpi.pelanggan_aktif or 0):,}", border=True,
              help="Pelanggan dengan minimal satu order yang bukan Cancelled", height="stretch")
with k4:
    st.metric("Rata-rata nilai order (USD)", usd(avg), border=True, height="stretch")
with k5:
    st.metric("Piutang (USD)", usd(piutang.piutang), border=True,
              help="Seluruh periode: penjualan dikurangi pembayaran. Tidak ikut filter tahun karena pembayaran "
                   "tidak terikat ke order tertentu", height="stretch")

left, right = st.columns([3, 2])
with left.container(border=True, height="stretch"):
    card_title("Penjualan per bulan", "USD, tanpa order Cancelled")
    bar(bulanan, "bulan", "penjualan", "Bulan", "Penjualan (USD)")
with right.container(border=True, height="stretch"):
    card_title("Penjualan per lini produk", "USD")
    lini = q(f"""
        SELECT p.productLine AS lini, SUM(d.quantityOrdered * d.priceEach) AS penjualan
        FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
        JOIN products p ON p.productCode = d.productCode
        WHERE {NON_CANCEL}{f_year} GROUP BY lini""", p_year)
    bar(lini, "lini", "penjualan", "Lini produk", "Penjualan (USD)", horizontal=True)

left, right = st.columns(2)
with left.container(border=True, height="stretch"):
    card_title("10 pelanggan teratas")
    top_c = q(f"""
        SELECT c.customerName AS pelanggan, c.country AS negara,
               SUM(d.quantityOrdered * d.priceEach) AS penjualan
        FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
        JOIN customers c ON c.customerNumber = o.customerNumber
        WHERE {NON_CANCEL}{f_year}
        GROUP BY c.customerNumber, c.customerName, c.country
        ORDER BY penjualan DESC LIMIT 10""", p_year)
    st.dataframe(top_c, hide_index=True, width="stretch", alt="10 pelanggan dengan penjualan terbesar",
                 column_config={"penjualan": st.column_config.ProgressColumn(
                     "penjualan (USD)", format="localized", min_value=0,
                     max_value=float(top_c.penjualan.max() or 1))})
with right.container(border=True, height="stretch"):
    card_title("Sales rep")
    rep = q(f"""
        SELECT CONCAT(e.firstName, ' ', e.lastName) AS sales_rep, f.city AS kantor,
               COUNT(DISTINCT o.customerNumber) AS pelanggan,
               SUM(d.quantityOrdered * d.priceEach) AS penjualan
        FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
        JOIN customers c ON c.customerNumber = o.customerNumber
        JOIN employees e ON e.employeeNumber = c.salesRepEmployeeNumber
        JOIN offices f ON f.officeCode = e.officeCode
        WHERE {NON_CANCEL}{f_year}
        GROUP BY e.employeeNumber, e.firstName, e.lastName, f.city
        ORDER BY penjualan DESC""", p_year)
    st.dataframe(rep, hide_index=True, width="stretch", alt="Penjualan per sales rep",
                 column_config={"penjualan": MONEY})

with st.container(border=True):
    card_title("Status order", "Termasuk order Cancelled")
    status = q(f"""SELECT o.status, COUNT(*) AS jumlah FROM orders o
                   WHERE 1=1{f_year} GROUP BY o.status ORDER BY jumlah DESC""", p_year)
    chart = (alt.Chart(status).mark_bar(color=SERIES, cornerRadiusEnd=4)
             .encode(alt.Y("status:N", sort="-x", title=None), alt.X("jumlah:Q", title="Jumlah order"),
                     tooltip=["status", "jumlah"])
             .properties(height=max(120, 34 * len(status))))
    st.altair_chart(chart, width="stretch", alt="Jumlah order per status")
