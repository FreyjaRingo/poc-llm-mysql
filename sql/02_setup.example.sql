-- SALIN file ini menjadi sql/02_setup.sql, lalu ganti password di bagian 2.
-- sql/02_setup.sql tidak ikut ke GitHub karena berisi password.

-- =====================================================================
-- Setup classicmodels untuk PoC LLM
-- Jalankan SETELAH sql/01_classicmodels.sql, sebagai root.
-- Aman dijalankan berulang kali.
--
-- Isi:
--   1. COMMENT pada tabel dan kolom. Pipeline membaca COMMENT ini dan
--      mengirimkannya ke LLM sebagai konteks.
--   2. User read-only llm_reader dengan hak akses per kolom. Kolom data
--      pribadi (nama kontak, telepon, alamat, email) tidak diberikan,
--      sehingga LLM tidak bisa melihat maupun meng-query kolom tersebut.
-- =====================================================================
USE classicmodels;

-- ---------------------------------------------------------------------
-- 1. COMMENT tabel
-- ---------------------------------------------------------------------
ALTER TABLE productlines COMMENT = 'Kategori produk (lini produk)';
ALTER TABLE products     COMMENT = 'Katalog produk model kendaraan skala';
ALTER TABLE offices      COMMENT = 'Kantor penjualan';
ALTER TABLE employees    COMMENT = 'Karyawan dan struktur organisasi. Nama lengkap = CONCAT(firstName, '' '', lastName)';
ALTER TABLE customers    COMMENT = 'Pelanggan (perusahaan toko). Sebagian pelanggan belum pernah order';
ALTER TABLE payments     COMMENT = 'Pembayaran yang diterima dari pelanggan. Tidak terhubung ke order tertentu, hanya ke pelanggan';
ALTER TABLE orders       COMMENT = 'Header order penjualan. Data order 6 Jan 2003 sampai 31 Mei 2005';
ALTER TABLE orderdetails COMMENT = 'Baris item per order. Nilai baris = quantityOrdered * priceEach';

-- ---------------------------------------------------------------------
-- 1b. COMMENT kolom. MODIFY wajib menyebut ulang definisi kolom persis
--     seperti aslinya agar tipe dan constraint tidak berubah.
-- ---------------------------------------------------------------------
ALTER TABLE products
  MODIFY productLine varchar(50) NOT NULL COMMENT 'FK ke productlines',
  MODIFY productScale varchar(10) NOT NULL COMMENT 'Skala model, contoh 1:10 atau 1:18',
  MODIFY productVendor varchar(50) NOT NULL COMMENT 'Pembuat model',
  MODIFY quantityInStock smallint NOT NULL COMMENT 'Stok saat ini (snapshot, bukan historis)',
  MODIFY buyPrice decimal(10,2) NOT NULL COMMENT 'Harga beli/biaya pokok per unit saat ini, dalam USD',
  MODIFY MSRP decimal(10,2) NOT NULL COMMENT 'Harga eceran yang disarankan pabrik per unit, dalam USD. Bukan harga jual aktual';

ALTER TABLE offices
  MODIFY territory varchar(10) NOT NULL COMMENT 'Wilayah penjualan: NA, EMEA, APAC, atau Japan';

ALTER TABLE employees
  MODIFY officeCode varchar(10) NOT NULL COMMENT 'Kantor tempat karyawan bekerja',
  MODIFY reportsTo int DEFAULT NULL COMMENT 'employeeNumber atasan langsung. NULL untuk President',
  MODIFY jobTitle varchar(50) NOT NULL COMMENT 'Jabatan. Penjual lapangan berjabatan Sales Rep';

ALTER TABLE customers
  MODIFY customerName varchar(50) NOT NULL COMMENT 'Nama perusahaan pelanggan',
  MODIFY country varchar(50) NOT NULL COMMENT 'Negara pelanggan',
  MODIFY salesRepEmployeeNumber int DEFAULT NULL COMMENT 'Sales rep yang menangani pelanggan saat ini. NULL jika tidak punya sales rep',
  MODIFY creditLimit decimal(10,2) DEFAULT NULL COMMENT 'Batas kredit dalam USD. 0 untuk pelanggan tanpa fasilitas kredit';

ALTER TABLE payments
  MODIFY checkNumber varchar(50) NOT NULL COMMENT 'Nomor cek/referensi pembayaran',
  MODIFY paymentDate date NOT NULL COMMENT 'Tanggal pembayaran diterima',
  MODIFY amount decimal(10,2) NOT NULL COMMENT 'Nilai pembayaran dalam USD';

ALTER TABLE orders
  MODIFY orderDate date NOT NULL COMMENT 'Tanggal order dibuat. Dasar periode penjualan',
  MODIFY requiredDate date NOT NULL COMMENT 'Tanggal pengiriman yang diminta pelanggan',
  MODIFY shippedDate date DEFAULT NULL COMMENT 'Tanggal dikirim. NULL jika belum dikirim. Terlambat jika shippedDate > requiredDate',
  MODIFY status varchar(15) NOT NULL COMMENT 'Shipped, Resolved, Cancelled, On Hold, Disputed, In Process. Order Cancelled tidak dihitung sebagai penjualan',
  MODIFY comments text COMMENT 'Catatan bebas dari staf. Teks bebas, bisa berisi apa saja';

ALTER TABLE orderdetails
  MODIFY quantityOrdered int NOT NULL COMMENT 'Jumlah unit dipesan',
  MODIFY priceEach decimal(10,2) NOT NULL COMMENT 'Harga jual aktual per unit dalam USD',
  MODIFY orderLineNumber smallint NOT NULL COMMENT 'Nomor urut baris dalam order';

-- ---------------------------------------------------------------------
-- 2. User read-only dengan hak akses per kolom
--    Ganti password, lalu samakan dengan DB_READER_PASSWORD di .env
-- ---------------------------------------------------------------------
DROP USER IF EXISTS 'llm_reader'@'localhost';
CREATE USER 'llm_reader'@'localhost' IDENTIFIED BY 'ganti_password_ini';

GRANT SELECT ON classicmodels.products     TO 'llm_reader'@'localhost';
GRANT SELECT ON classicmodels.orders       TO 'llm_reader'@'localhost';
GRANT SELECT ON classicmodels.orderdetails TO 'llm_reader'@'localhost';
GRANT SELECT ON classicmodels.payments     TO 'llm_reader'@'localhost';
GRANT SELECT ON classicmodels.offices      TO 'llm_reader'@'localhost';

-- productlines: htmlDescription dan image (gambar biner) tidak berguna untuk analisis
GRANT SELECT (productLine, textDescription) ON classicmodels.productlines TO 'llm_reader'@'localhost';

-- employees: email dan extension (nomor telepon internal) disembunyikan
GRANT SELECT (employeeNumber, lastName, firstName, officeCode, reportsTo, jobTitle)
  ON classicmodels.employees TO 'llm_reader'@'localhost';

-- customers: nama kontak, telepon, dan alamat jalan disembunyikan
GRANT SELECT (customerNumber, customerName, city, state, country,
              salesRepEmployeeNumber, creditLimit)
  ON classicmodels.customers TO 'llm_reader'@'localhost';

FLUSH PRIVILEGES;
