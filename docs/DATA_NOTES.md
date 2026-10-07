# Catatan Data: classicmodels

Sumber: MySQL Sample Database dari mysqltutorial.org. Isinya perusahaan fiktif penjual model mobil skala.

## Isi

| Tabel | Baris | Isi |
|---|---|---|
| productlines | 7 | Lini produk |
| products | 110 | Katalog produk, termasuk harga beli (buyPrice) dan MSRP |
| offices | 7 | Kantor penjualan di 4 wilayah (NA, EMEA, APAC, Japan) |
| employees | 23 | Karyawan dan hierarki (reportsTo) |
| customers | 122 | Pelanggan, sales rep, dan batas kredit |
| payments | 273 | Pembayaran per pelanggan |
| orders | 326 | Header order, 6 Jan 2003 sampai 31 Mei 2005 |
| orderdetails | 2.996 | Baris item order |

## Temuan profiling

| Temuan | Angka | Dampak |
|---|---|---|
| Pelanggan tanpa order | 24 dari 122 | "Jumlah pelanggan" bisa 122 atau 98 |
| Pelanggan tanpa sales rep | 22 | Semuanya juga belum pernah order |
| Status order selain Shipped | 23 order (6 Cancelled, 6 In Process, 4 On Hold, 4 Resolved, 3 Disputed) | Penjualan perlu aturan status |
| Penjualan vs pembayaran 2004 | 4.344.182 vs 4.313.328 | "Pendapatan" ambigu |
| Total piutang | 511.497 dari 16 pelanggan | Butuh dua agregasi terpisah, rawan fan-out |
| Order terlambat | 1 (order 10165) | |
| Produk tidak pernah dipesan | 1 | |
| Harga jual di atas MSRP atau di bawah harga beli | 0 | Data bersih, tidak perlu cleaning |
| Order 2005 | 64 (hanya Jan sampai Mei) | Tahun 2005 tidak penuh |

## Keputusan

- Data dimuat apa adanya. Tidak ada pembersihan karena tidak ditemukan anomali.
- COMMENT ditambahkan ke tabel dan kolom penting lewat `02_setup.sql`.
- User `llm_reader` hanya diberi SELECT, dan untuk `customers`, `employees`, serta `productlines` hanya kolom tertentu. Nama kontak, telepon, alamat jalan, email, dan gambar biner tidak bisa dibaca. Kolom yang tidak diberikan juga tidak muncul di `information_schema`, sehingga otomatis tidak masuk ke prompt LLM.

## Asumsi yang belum terverifikasi

- Mata uang diasumsikan USD. Dataset tidak menyebutkannya. Dasarnya penggunaan istilah MSRP dan kantor pusat di San Francisco.
- `buyPrice` dianggap biaya pokok saat ini, bukan biaya historis saat order terjadi. Laba kotor adalah perkiraan.
- Penjualan sales rep mengikuti `salesRepEmployeeNumber` di tabel customers saat ini. Jika pelanggan pernah pindah sales rep, data ini tidak bisa menunjukkannya.

## Keterbatasan untuk PoC

- Dataset ini sangat populer di tutorial SQL. Kemungkinan besar LLM sudah sering melihat skemanya, sehingga akurasi bisa lebih tinggi daripada di data internal yang belum pernah dilihat model. Soal uji di PoC ini disusun sendiri dengan definisi bisnis yang spesifik untuk mengurangi efek tersebut, tapi tidak menghilangkannya.
- Data kecil: 98 pelanggan aktif dan 110 produk. Cukup untuk menunjukkan cara kerja rekomendasi, tapi terlalu kecil untuk membandingkan metode secara meyakinkan.
- Kolom `orders.comments` berisi teks bebas. Ini sumber insight kualitatif (alasan pembatalan, sengketa, batas kredit), sekaligus celah prompt injection jika isinya dikirim ke LLM.

## Temuan dari evaluasi rekomendasi (7 Okt 2026)

- 74% kombinasi pelanggan dan produk yang dibeli di 2005 adalah produk yang belum pernah dibeli pelanggan itu sebelumnya. Target rekomendasi karena itu adalah produk baru, bukan pembelian ulang.
- Rekomendasi acak menghasilkan hit rate@10 sebesar 58%. Populer (67%) dan Rule-based (64%) tidak berbeda bermakna dari acak. Similarity dan Segmen (31%) lebih buruk dari acak.
- Produk yang benar-benar dibeli di 2005 punya skor kemiripan rata-rata 4,36, sedikit di bawah produk acak (4,64). Median peringkat popularitasnya 47 dari 110.
- Interpretasi (dugaan, belum terverifikasi): data pembelian di classicmodels kemungkinan dibangkitkan secara hampir acak, sehingga tidak mengandung pola "sering dibeli bersama" maupun selera segmen. Dataset ini cukup untuk menunjukkan cara kerja mesin rekomendasi, tetapi tidak bisa dipakai untuk menilai metode mana yang lebih baik.
- Segmentasi berbasis RFM memberi silhouette 0,44 tetapi hanya memisahkan pelanggan besar dan kecil (satu segmen berisi 2 pelanggan). Segmentasi berbasis porsi lini produk dipakai karena lebih relevan untuk rekomendasi, dengan silhouette 0,25 (batas segmen tidak tegas).
- Nama produk "1980’s GM Manhattan Express" tersimpan ter-encode dua kali di file SQL sumber. Diperbaiki saat dibaca di core/features.py, data di database tidak diubah.
