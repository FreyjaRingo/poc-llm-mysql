# PoC LLM + MySQL: classicmodels

PoC untuk memahami cara kerja LLM yang terhubung ke database MySQL tanpa bergantung pada vendor. LLM (DeepSeek) menerjemahkan pertanyaan bahasa biasa menjadi SQL, sistem memvalidasi dan menjalankannya dengan user read-only, lalu hasilnya ditampilkan di dashboard.

## Struktur folder

```
RAG LLM/
├── app.py                  Dashboard Streamlit: sidebar dan navigasi (yang dijalankan)
├── app_pages/
│   ├── common.py           Fungsi bersama: query, format angka, sidebar, penjelasan SQL
│   ├── ringkasan.py        Halaman Ringkasan
│   ├── pelanggan.py        Halaman Detail pelanggan
│   ├── rekomendasi.py      Halaman Rekomendasi
│   ├── data.py             Halaman Data
│   └── tanya_ai.py         Halaman Tanya AI (chat)
├── .streamlit/
│   └── config.toml         Tema dashboard (warna, font)
├── ask.py                  Bertanya ke DeepSeek dari terminal
├── evaluate.py             Mengukur akurasi text-to-SQL dengan soal uji
├── verify_db.py            Mengecek isi database dan hak akses llm_reader
├── evaluate_rec.py         Mengukur akurasi metode rekomendasi (split waktu)
├── evaluate_agent.py       Menguji apakah agent memilih alat yang tepat
├── core/
│   ├── config.py           Membaca .env, semua pengaturan ada di sini
│   ├── pipeline.py         Inti: skema, prompt, DeepSeek, validasi SQL, eksekusi, log
│   ├── charts.py           Memilih dan menggambar grafik untuk hasil Tanya AI
│   ├── features.py         Data, segmen (k-means), kemiripan produk, status kredit
│   ├── recommend.py        Lima metode rekomendasi dan evaluasinya
│   ├── agent.py            Agent tool calling: query database, rekomendasi, profil pelanggan
│   └── explain.py          Penjelasan SQL deterministik (parser, bukan LLM)
├── context/
│   └── business_rules.md   Definisi istilah bisnis yang dikirim ke LLM
├── evaluation/
│   ├── eval_questions.json 22 soal uji beserta SQL acuan
│   └── agent_questions.json 10 soal uji pemilihan alat
├── sql/
│   ├── 01_classicmodels.sql  Database contoh dari mysqltutorial.org
│   ├── 02_setup.example.sql  COMMENT kolom dan user read-only llm_reader (template)
│   └── 02_setup.sql          Salinan template berisi password Anda (tidak ikut ke GitHub)
├── docs/
│   ├── DATA_NOTES.md       Profil data, asumsi, keterbatasan
│   └── METODOLOGI.md       Aturan dan rumus setiap angka di dashboard
├── logs/                   (otomatis) catatan setiap pertanyaan ke LLM
├── reports/                (otomatis) hasil evaluasi per soal
├── .env                    Password database dan API key (rahasia)
├── .env.example            Contoh isi .env
└── requirements.txt        Daftar library Python
```

## Setup dari nol

1. Salin `sql/02_setup.example.sql` menjadi `sql/02_setup.sql`, lalu ganti `ganti_password_ini` dengan password pilihan Anda.
2. Di HeidiSQL (Laragon > Database), jalankan `sql/01_classicmodels.sql`, lalu `sql/02_setup.sql`. Lewat File > Load SQL file, lalu F9.
3. Salin `.env.example` menjadi `.env`. Isi `DB_READER_PASSWORD` dengan password yang sama dengan langkah 1, lalu isi `DEEPSEEK_API_KEY` dengan API key Anda sendiri.
4. `python -m pip install -r requirements.txt`
5. `python verify_db.py` untuk memastikan database dan hak akses sudah benar.

## Kolaborasi lewat GitHub

File berikut tidak ikut ke GitHub (diatur di `.gitignore`). Setiap orang membuat sendiri di laptopnya:

| File | Isi | Cara membuat |
|---|---|---|
| `.env` | Password database dan API key DeepSeek | Salin dari `.env.example` |
| `sql/02_setup.sql` | Password user `llm_reader` | Salin dari `sql/02_setup.example.sql` |
| `logs/`, `reports/` | Log pertanyaan dan hasil evaluasi | Dibuat otomatis saat program jalan |

Aturan kerja:

- Setiap orang memakai API key DeepSeek sendiri. Jangan berbagi key lewat chat atau commit.
- Hanya dataset publik `classicmodels`. Jangan pernah memasukkan data Danamon ke repo ini atau ke prompt DeepSeek.
- Kerjakan perubahan di branch sendiri (`git switch -c nama-fitur`), lalu buka Pull Request ke `main`. Minta teman mereview sebelum merge.
- Sebelum commit, jalankan `git status` dan pastikan `.env` serta `sql/02_setup.sql` tidak muncul.
- Jika mengubah COMMENT kolom atau hak akses, ubah `sql/02_setup.example.sql`, lalu beri tahu yang lain untuk menjalankan ulang file setup mereka.
- Jika mengubah logika di `core/features.py` yang memengaruhi model rekomendasi, naikkan `MODEL_VERSION` supaya cache Streamlit diganti.

## Menjalankan

| Tujuan | Perintah |
|---|---|
| Dashboard | `python -m streamlit run app.py` |
| Satu pertanyaan dari terminal | `python ask.py "Siapa sales rep dengan penjualan terbesar?"` |
| Lihat prompt lengkap yang dikirim | `python ask.py "Berapa jumlah pelanggan?" --show-prompt` |
| Evaluasi konfigurasi terbaik | `python evaluate.py --rules on --thinking on` |
| Evaluasi tanpa definisi bisnis | `python evaluate.py --rules off --thinking on` |
| Cek SQL acuan (tanpa biaya) | `python evaluate.py --check-gold` |
| Evaluasi rekomendasi (tanpa LLM, gratis) | `python evaluate_rec.py` |
| Evaluasi rekomendasi termasuk LLM | `python evaluate_rec.py --with-llm` |
| Uji pemilihan alat oleh agent | `python evaluate_agent.py --thinking on` |

## Grafik di halaman Tanya AI

Setiap hasil query otomatis diberi visualisasi jika bentuk tabelnya cocok:

| Bentuk hasil | Tampilan |
|---|---|
| Satu baris angka | Kartu KPI |
| Kolom waktu (bulan, tahun, tanggal) + angka | Grafik garis |
| Kategori + angka, maksimal 30 baris | Grafik batang |
| Dua kolom angka | Scatter |
| Pertanyaan tentang porsi atau komposisi (misal "porsi penjualan per wilayah"), semua nilai positif | Pie (donut) dengan persentase. Lebih dari 8 kategori: 7 terbesar ditampilkan, sisanya digabung jadi "Lainnya" |
| Lainnya | Tabel saja |

Toggle "AI memilih jenis grafik" di sidebar membuat DeepSeek ikut mengusulkan grafik dalam bentuk JSON. Usulan itu hanya dipakai jika jenisnya bar, line, scatter, atau pie dan kolomnya benar-benar ada di hasil query. Usulan pie untuk data dengan nilai negatif otomatis diganti grafik batang, dengan alasannya dicatat. Jika tidak, sistem kembali ke aturan otomatis. LLM tidak pernah menulis kode grafik. Asal pilihan grafik ditampilkan di bagian "SQL dan detail teknis".

## Penjelasan hasil (explainability)

Setiap hasil AI dan rekomendasi bisa ditelusuri. Penjelasan dibuat oleh kode dari data, bukan oleh LLM. Bagian yang berasal dari LLM selalu diberi label.

| Di mana | Yang ditampilkan |
|---|---|
| Tanya AI, "Bagaimana jawaban ini dihitung?" | Langkah perhitungan hasil uraian parser atas SQL (tabel, join, filter, kelompok, rumus, urutan), asumsi yang ditulis LLM, arti kolom dari COMMENT database, dan daftar pemeriksaan keamanan |
| Mode agent, setiap langkah | Alasan memilih alat (diberi label "menurut LLM"), argumen, hasil, dan penjelasan SQL |
| Rekomendasi, setiap metode | Cara kerja (aturan dan rumus) dan perhitungan untuk pelanggan itu. Contoh similarity: 19 / √(21 × 23) = 0,865 |
| Rekomendasi, aturan bisnis | Tabel penjualan, pembayaran, piutang, dan batas kredit yang menentukan apakah penawaran ditahan |
| Rekomendasi, metode LLM | Prompt lengkap yang dikirim, jawaban mentah, kode yang dibuang, dan data pendukung untuk mengecek alasan LLM |

Rincian semua rumus ada di `docs/METODOLOGI.md`.

## Mode agent di halaman Tanya AI

Saat toggle "Mode agent (tool calling)" aktif (default), DeepSeek tidak langsung menulis SQL. DeepSeek memilih alat:

| Alat | Kapan dipakai | Dijalankan oleh |
|---|---|---|
| `query_database` | Pertanyaan angka atau daftar data | Jalur text-to-SQL yang sama dengan evaluate.py |
| `get_recommendations` | Rekomendasi produk untuk seorang pelanggan, metode bisa dipilih | core/recommend.py |
| `get_customer_profile` | Segmen, porsi lini, piutang, status kredit | core/features.py |

Alurnya: pertanyaan, DeepSeek memilih alat, Python menjalankan alat, DeepSeek membaca hasil dan menjawab (atau memanggil alat lain, maksimal 5 langkah). Hasil alat (grafik dan tabel) tampil langsung di bawah jawaban. Setiap langkah bisa dibuka lewat "Cara kerja": argumen, alasan LLM memilih alat, dan penjelasan SQL, sehingga bisa diaudit.

Pengaman:
- Produk dan angka selalu berasal dari Python. LLM hanya memilih alat dan menjelaskan hasilnya.
- Nama pelanggan dicocokkan oleh Python. Jika lebih dari satu pelanggan cocok, agent menerima daftar kandidat dan harus bertanya balik.
- Peringatan aturan bisnis (piutang melebihi batas kredit, order On Hold atau Disputed) selalu disertakan di hasil alat.
- Pertanyaan lanjutan memakai 3 pertanyaan dan jawaban terakhir sebagai konteks.

Konsekuensi: setiap pertanyaan butuh minimal 2 panggilan DeepSeek, dan 3 panggilan jika memakai `query_database` (karena alat itu menulis SQL dengan panggilan terpisah). Latensi kira-kira dua sampai tiga kali mode SQL biasa.

`evaluate_agent.py` menguji 10 pertanyaan, termasuk pertanyaan tanpa kata "rekomendasi", pertanyaan dua langkah, dan nama pelanggan yang ambigu. Router berbasis kata kunci sederhana lulus 7/10, jadi DeepSeek perlu melampaui angka itu.

## Rekomendasi pelanggan (halaman Rekomendasi)

Untuk setiap pelanggan, lima metode merekomendasikan 10 produk yang belum pernah dibelinya:

| Metode | Cara kerja |
|---|---|
| Populer | Produk dengan pembeli terbanyak |
| Segmen | Pelanggan dikelompokkan dengan k-means berdasarkan porsi belanja per lini produk. Rekomendasinya produk terlaris di segmennya |
| Similarity | Kemiripan antar produk dihitung dari siapa yang membelinya (cosine). Skor = total kemiripan dengan produk milik pelanggan |
| Rule-based | R1 produk populer di lini utama pelanggan (maks 6), R2 lini kedua (maks 2), R3 satu produk dari tiap lini yang belum pernah dibeli, R4 sisanya populer |
| LLM | DeepSeek menerima profil pelanggan dan katalog produk yang belum dibeli, lalu memilih 10. Kode yang tidak ada di katalog dibuang |

Aturan bisnis di atas semua metode: penawaran baru ditandai "sebaiknya ditahan" jika piutang melebihi batas kredit atau pelanggan punya order berstatus On Hold atau Disputed.

Semua dihitung di memori dari data `llm_reader` (tidak ada tabel baru, tidak ada akses tulis). k-means dan cosine ditulis dengan numpy tanpa scikit-learn.

### Hasil evaluasi (latih s.d. 31 Des 2004, uji Jan sampai Mei 2005, 42 pelanggan)

| Metode | Hit rate@10 (selang 95%) | Kesimpulan |
|---|---|---|
| Acak (pembanding) | 58% (51% - 67%) | pembanding |
| Populer | 67% (52% - 81%) | tidak berbeda bermakna dari acak |
| Rule-based | 64% (48% - 79%) | tidak berbeda bermakna dari acak |
| Segmen | 31% (17% - 45%) | lebih buruk dari acak |
| Similarity | 31% (17% - 45%) | lebih buruk dari acak |

Tidak ada metode yang terbukti lebih baik dari rekomendasi acak di dataset ini. Produk yang benar-benar dibeli di 2005 bahkan punya skor kemiripan sedikit lebih rendah dari produk acak. Dugaan terkuat: `classicmodels` adalah data sintetis yang pola pembeliannya hampir acak, sehingga tidak ada sinyal perilaku yang bisa dipelajari. Mesin rekomendasi bekerja secara teknis, tetapi dataset ini tidak bisa membuktikan metode mana yang lebih baik. Evaluasi metode LLM perlu dijalankan dengan `python evaluate_rec.py --with-llm` (sekitar 42 panggilan DeepSeek).

## Hasil yang seharusnya muncul di verify_db.py

| Cek | Nilai |
|---|---|
| Baris per tabel | productlines 7, products 110, offices 7, employees 23, customers 122, payments 273, orders 326, orderdetails 2.996 |
| Pelanggan terdaftar vs pernah order | 122 vs 98 |
| Penjualan vs pembayaran 2004 | 4.344.182,02 vs 4.313.328,25 |
| Total piutang | 511.497,20 dari 16 pelanggan |
| Uji hak akses | Semua ditolak |

## Hasil evaluasi (7 Okt 2026, deepseek-flash, 22 soal, satu run per konfigurasi)

| | Thinking off | Thinking on |
|---|---|---|
| Definisi bisnis off | 18/22 | 19/22 |
| Definisi bisnis on | 20/22 | 22/22 |

Tiga mode gagal yang ditemukan: mengganti data yang tidak tersedia dengan data lain tanpa bilang (telepon pelanggan diganti telepon kantor), mengabaikan definisi bisnis di prompt, dan terlalu cepat menolak saat aturan diperketat. Angka ini tidak boleh dibaca sebagai akurasi umum. Dataset kecil, populer di tutorial, dan setiap konfigurasi baru diuji sekali.

## Pengaturan di .env

| Variabel | Fungsi |
|---|---|
| `DB_*` | Koneksi MySQL. Aplikasi hanya memakai `DB_READER_*` (read-only) |
| `DEEPSEEK_API_KEY`, `LLM_MODEL` | Akses DeepSeek. Model `deepseek-flash` atau `deepseek-v4-pro` |
| `LLM_THINKING` | `enabled` atau `disabled`. Bisa ditimpa dengan `--thinking` atau toggle di dashboard |
| `INCLUDE_BUSINESS_RULES` | Kirim `context/business_rules.md` atau tidak. Bisa ditimpa dengan `--rules` |
| `INCLUDE_COLUMN_COMMENTS` | Kirim COMMENT tabel dan kolom atau tidak |
| `MAX_ROWS`, `QUERY_TIMEOUT_MS` | Batas baris dan waktu setiap query |

## Keamanan

- DeepSeek menyimpan data di server di Tiongkok. Aman untuk dataset publik ini, tidak untuk data Danamon.
- Pengaman utama ada di database: `llm_reader` hanya bisa SELECT, dan tidak bisa membaca kolom nama kontak, telepon, alamat, atau email pelanggan dan karyawan.
- Lapisan kedua: validator SQL hanya menerima satu SELECT, menambahkan LIMIT, dan memblokir fungsi berbahaya.
- Jangan membagikan file `.env`.

## Troubleshooting

- `streamlit is not recognized`: pakai `python -m streamlit run app.py`.
- Error seperti `unexpected keyword argument 'type'` atau `'delta_arrow'`: versi Streamlit terlalu lama. Jalankan `pip install -U streamlit` (dashboard butuh versi 1.65 atau lebih baru).
- Font terlihat berbeda: tema memuat font Inter dari Google Fonts. Jika internet kantor memblokirnya, font bawaan dipakai dan dashboard tetap jalan.
- `ModuleNotFoundError: No module named 'core'`: jalankan perintah dari folder `RAG LLM`, bukan dari dalam subfolder.
- `Access denied for user 'llm_reader'`: password di `.env` tidak sama dengan di `sql/02_setup.sql`, atau `sql/02_setup.sql` belum dijalankan.
- `Can't connect to MySQL server`: nyalakan MySQL di Laragon.
- `DEEPSEEK_API_KEY belum diisi`: isi di `.env`.
- `Error code: 401` dari DeepSeek: API key salah. `402`: saldo habis. `400`: cek nama model dan `LLM_THINKING`.
