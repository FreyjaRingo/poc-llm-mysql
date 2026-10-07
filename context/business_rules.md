# Definisi bisnis classicmodels

Dikirim ke LLM saat INCLUDE_BUSINESS_RULES=true. Ini versi paling sederhana dari
"semantic layer": definisi istilah yang tidak bisa disimpulkan dari nama kolom saja.

- Semua nilai uang dalam USD.
- Data order mencakup 6 Januari 2003 sampai 31 Mei 2005. Tahun 2005 tidak penuh.
  Untuk istilah relatif seperti "tahun ini" atau "bulan lalu", acuannya tanggal order
  terakhir di data, bukan tanggal hari ini.
- "Penjualan" atau "pendapatan" berarti SUM(orderdetails.quantityOrdered * orderdetails.priceEach)
  dari order dengan status selain 'Cancelled'. Periodenya berdasarkan orders.orderDate.
- "Pembayaran" atau "kas masuk" berarti SUM(payments.amount), periodenya berdasarkan paymentDate.
  Jangan mencampur penjualan dengan pembayaran.
- "Laba kotor" berarti SUM(quantityOrdered * (priceEach - products.buyPrice)) dari order selain
  'Cancelled'. buyPrice adalah biaya saat ini, jadi angka ini perkiraan.
- "Piutang" atau "saldo belum dibayar" pelanggan berarti total penjualan pelanggan itu dikurangi
  total pembayarannya.
- "Pelanggan" berarti pelanggan yang punya minimal satu order dengan status selain 'Cancelled'.
  Tabel customers juga berisi calon pelanggan yang belum pernah order.
- Penjualan seorang sales rep berarti penjualan dari pelanggan yang salesRepEmployeeNumber-nya
  adalah sales rep tersebut. Penjualan sebuah kantor mengikuti kantor sales rep-nya.
- "Order terlambat" berarti shippedDate > requiredDate.
- Jika pertanyaan menyebut bulan tanpa tahun, tampilkan hasil per tahun yang tersedia.
- Nama karyawan ditampilkan sebagai CONCAT(firstName, ' ', lastName).
- Data tidak memuat biaya pengiriman, diskon, retur, atau data kontak pribadi.
