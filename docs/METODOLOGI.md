# Metodologi: aturan, perhitungan, dan cara membaca hasil

Dokumen ini menjelaskan bagaimana setiap angka di dashboard dihasilkan. Prinsipnya: semua penjelasan dibuat oleh kode dari data, bukan oleh LLM. Bagian yang ditulis LLM selalu diberi label.

## 1. Tanya AI (mode SQL)

### Alur
1. Skema database (tabel, kolom, COMMENT) dibaca dengan user `llm_reader`. Kolom data pribadi tidak terlihat oleh user ini, jadi tidak masuk prompt.
2. Jika diaktifkan, definisi bisnis dari `context/business_rules.md` ditambahkan ke prompt.
3. DeepSeek menulis satu query SELECT. Asumsinya ditulis sebagai komentar SQL.
4. Validator (sqlglot) memeriksa: tepat satu statement, hanya SELECT, tanpa fungsi berbahaya. LIMIT ditambahkan.
5. Query dijalankan dengan `llm_reader` dan batas waktu 10 detik.
6. Jika diaktifkan, maksimal 30 baris hasil dikirim ke DeepSeek untuk dirangkum.

### Penjelasan "Bagaimana jawaban ini dihitung?"
- **Langkah perhitungan:** SQL diurai oleh parser sqlglot menjadi urutan: sumber data, penggabungan tabel, filter, pengelompokan, rumus hitungan, urutan, dan batas baris. Subquery dijelaskan terpisah, mulai dari yang paling dalam. Karena dibuat parser, penjelasan ini selalu sesuai dengan SQL yang benar-benar dijalankan.
- **Asumsi:** diambil dari komentar `-- asumsi:` yang ditulis LLM. Ini satu-satunya bagian yang berasal dari LLM.
- **Arti kolom:** diambil dari COMMENT kolom di database (`sql/02_setup.sql`).
- **Pemeriksaan:** daftar pengaman yang sudah dilewati query.

Yang tetap perlu dicek manusia: apakah langkah perhitungan sesuai dengan maksud pertanyaan. Parser bisa menjelaskan apa yang dihitung, tetapi tidak bisa menilai apakah itu yang dimaksud penanya.

## 2. Tanya AI (mode agent)

DeepSeek memilih satu atau beberapa alat: `query_database`, `get_recommendations`, `get_customer_profile`. Setiap pemanggilan menampilkan:
- argumen yang dipakai;
- **alasan memilih alat menurut LLM** (laporan diri LLM, bukan hasil perhitungan);
- hasil alat (tabel, peringatan, atau daftar kandidat jika nama pelanggan ambigu);
- penjelasan SQL jika alatnya `query_database`.

Nama pelanggan dicocokkan oleh Python: nomor pelanggan, nama persis, nama yang mengandung teks, lalu kemiripan ejaan (difflib, ambang 0,6). Jika lebih dari satu cocok, agent menerima daftar kandidat.

## 3. Rekomendasi

Semua metode memakai data `llm_reader` yang sama, menghitung di memori, dan tidak merekomendasikan produk yang sudah pernah dibeli pelanggan.

### Aturan bisnis (berlaku di atas semua metode)
- Piutang = total penjualan (tanpa order Cancelled) dikurangi total pembayaran.
- Penawaran ditandai "sebaiknya ditahan" jika piutang > batas kredit, atau pelanggan punya order berstatus On Hold atau Disputed.
- Dashboard menampilkan tabel perhitungannya: penjualan, pembayaran, piutang, batas kredit.

### Populer
- Skor = jumlah pelanggan berbeda yang pernah membeli produk.
- Jika sama, diurutkan dari nilai penjualan.
- Ditampilkan: jumlah pembeli, nilai penjualan, peringkat global.

### Segmen
1. Setiap pelanggan diubah menjadi porsi belanja per lini produk (7 angka, total 100%).
2. Porsi distandarkan (z-score), lalu dikelompokkan dengan k-means (inisialisasi k-means++, 10 kali percobaan, seed 42).
3. k dipilih dari 3 sampai 6 berdasarkan silhouette tertinggi. Tabel k vs silhouette ditampilkan.
4. Nama segmen: "Condong <lini>", dengan lini = lini yang porsinya naik paling besar dibanding rata-rata semua pelanggan. Contohnya "Condong Ships": porsi Ships rata-rata 26% di segmen itu, dibanding 7% pada semua pelanggan (3,7x). Lini tersebut belum tentu yang belanjanya terbesar di segmen itu; Classic Cars tetap dominan di hampir semua segmen sehingga tidak membedakan. Jika porsi lini pembeda di bawah 10%, segmen diberi nama "Beragam lini". Tambahan "belanja besar/menengah/kecil" berasal dari peringkat rata-rata nilai belanja segmen.
5. Skor produk = jumlah anggota segmen yang membelinya.

Ditampilkan: porsi pelanggan vs rata-rata segmen vs rata-rata semua, dan jumlah pembeli di segmen per produk.

Catatan: segmentasi berbasis RFM memberi silhouette 0,44, tetapi hanya memisahkan pelanggan besar dan kecil (satu segmen berisi 2 pelanggan). Porsi lini dipakai karena lebih relevan untuk rekomendasi produk. Silhouette 0,25 berarti batas antar segmen tidak tegas.

### Similarity (item-based cosine)
- Kemiripan produk A dan B = (pelanggan yang membeli keduanya) / akar(pembeli A × pembeli B).
- Skor kandidat = jumlah kemiripannya dengan setiap produk yang sudah dibeli pelanggan.
- Kandidat dengan skor 0 tidak direkomendasikan.

Ditampilkan untuk produk yang dipilih: skor total, tiga kontributor terbesar beserta jumlah pembeli masing-masing, dan contoh hitung. Contoh untuk Signal Gift Stores: 19 / √(21 × 23) = 0,865.

### Rule-based
- R1: dari lini dengan belanja terbesar, ambil produk terpopuler yang belum dibeli (maksimal 6).
- R2: dari lini kedua (maksimal 2).
- R3: satu produk terlaris dari setiap lini yang belum pernah dibeli (cross-sell), diurutkan dari lini dengan penjualan global terbesar.
- R4: sisa slot diisi produk terpopuler.

Ditampilkan: belanja dan porsi per lini, peran setiap lini dalam aturan, dan aturan yang memicu setiap produk.

### LLM
- DeepSeek menerima profil pelanggan (porsi lini, jumlah order, segmen, 15 produk yang paling banyak dibeli) dan katalog produk yang belum dibeli (kode, nama, lini, skala, pembuat, MSRP, peringkat popularitas).
- DeepSeek membalas JSON berisi 10 kode produk, alasan, dan ringkasan.
- Python membuang kode yang tidak ada di katalog dan kode ganda.

Ditampilkan: prompt lengkap yang dikirim, jawaban mentah, kode yang dibuang, dan **data pendukung** untuk setiap pilihan (porsi pelanggan di lini produk itu, jumlah produk dengan skala sama yang sudah dimiliki, peringkat popularitas). Data pendukung dihitung Python, sehingga alasan LLM bisa dicek. Contohnya, jika LLM menulis "sesuai fokus pelanggan di Classic Cars" tetapi porsi pelanggan di lini itu 0%, alasan tersebut keliru.

## 4. Evaluasi rekomendasi

- Model dilatih hanya dengan transaksi sebelum 1 Januari 2005.
- Uji: produk BARU yang benar-benar dibeli pelanggan pada Januari sampai Mei 2005. Ada 42 pelanggan yang memenuhi syarat.
- Hit rate@10 = persen pelanggan yang minimal 1 dari 10 rekomendasinya dibeli.
- Precision@10 = rata-rata (rekomendasi yang dibeli / 10).
- Recall@10 = rata-rata (rekomendasi yang dibeli / produk baru yang dibeli).
- Selang kepercayaan 95% dari bootstrap 1.000 kali.
- Pembanding acak: rata-rata 200 kali memilih 10 produk secara acak dari produk yang belum dibeli.
- Kesimpulan otomatis:
  - "lebih baik dari acak" jika batas bawah selang > hit rate acak;
  - "lebih buruk" jika batas atas < hit rate acak;
  - selain itu "tidak berbeda bermakna".

Hasil 7 Oktober 2026: tidak ada metode yang terbukti lebih baik dari acak. Lihat `docs/DATA_NOTES.md` untuk interpretasinya.

## 5. Evaluasi text-to-SQL

- 22 soal dengan SQL acuan (`evaluation/eval_questions.json`).
- Hasil SQL dari LLM dan SQL acuan sama-sama dijalankan, lalu hasilnya dibandingkan (execution accuracy). Teks SQL tidak dibandingkan.
- **Strict:** himpunan baris sama.
- **Lenient:** kolom tambahan diizinkan.
- **Angka cocok, label beda:** tidak dihitung benar, perlu dicek manual.
