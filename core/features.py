"""
Data dan fitur untuk rekomendasi. Semua query memakai llm_reader (read-only).

Fungsi utama:
  load_data()              ambil order, produk, pelanggan, pembayaran dari MySQL
  build_model(data, cutoff) hitung popularitas, matriks pelanggan x produk, kemiripan
                           produk, dan segmen pelanggan. cutoff dipakai saat evaluasi
                           supaya model hanya melihat data sebelum tanggal tersebut.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core import pipeline

SEED = 42
# Naikkan angka ini setiap kali isi Model berubah. Dashboard memakai angka ini sebagai
# kunci cache, sehingga model lama di memori Streamlit otomatis dibangun ulang.
MODEL_VERSION = "3"


# ---------------------------------------------------------------------------
# 1. Ambil data
# ---------------------------------------------------------------------------
def _query(conn, sql: str) -> pd.DataFrame:
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = [tuple(pipeline.to_jsonable(v) for v in r) for r in cur.fetchall()]
    cur.close()
    return pd.DataFrame(rows, columns=cols)


def _fix_text(s):
    """Perbaiki teks yang ter-encode dua kali di data sumber, misal 'â€™' menjadi '’'."""
    if isinstance(s, str) and "â" in s:
        try:
            return s.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def load_data() -> dict:
    conn = pipeline.get_connection()
    try:
        lines = _query(conn, """
            SELECT o.orderNumber, o.orderDate, o.customerNumber, d.productCode,
                   d.quantityOrdered, d.priceEach,
                   d.quantityOrdered * d.priceEach AS nilai
            FROM orders o JOIN orderdetails d ON d.orderNumber = o.orderNumber
            WHERE o.status <> 'Cancelled'""")
        products = _query(conn, """
            SELECT productCode, productName, productLine, productScale, productVendor,
                   buyPrice, MSRP, quantityInStock FROM products""")
        customers = _query(conn, """
            SELECT customerNumber, customerName, country, creditLimit FROM customers""")
        payments = _query(conn, """
            SELECT customerNumber, SUM(amount) AS bayar FROM payments GROUP BY customerNumber""")
        issues = _query(conn, """
            SELECT customerNumber, status, COUNT(*) AS jumlah FROM orders
            WHERE status IN ('On Hold', 'Disputed') GROUP BY customerNumber, status""")
    finally:
        conn.close()
    lines["orderDate"] = pd.to_datetime(lines["orderDate"])
    for c in ("buyPrice", "MSRP"):
        products[c] = products[c].astype(float)
    products["productName"] = products["productName"].map(_fix_text)
    customers["customerName"] = customers["customerName"].map(_fix_text)
    customers["creditLimit"] = customers["creditLimit"].astype(float)
    return {"lines": lines, "products": products.set_index("productCode"),
            "customers": customers.set_index("customerNumber"),
            "payments": payments.set_index("customerNumber")["bayar"].astype(float),
            "issues": issues}


# ---------------------------------------------------------------------------
# 2. K-means sederhana dengan numpy (tanpa scikit-learn)
# ---------------------------------------------------------------------------
def _kmeans(X: np.ndarray, k: int, seed: int = SEED, n_init: int = 10, iters: int = 100):
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(n_init):
        # Inisialisasi k-means++: pusat berikutnya dipilih jauh dari pusat yang sudah ada
        centers = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d2 = np.min(((X[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
            centers.append(X[rng.choice(len(X), p=d2 / d2.sum())])
        C = np.array(centers)
        for _ in range(iters):
            labels = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
            newC = np.array([X[labels == j].mean(0) if (labels == j).any() else C[j]
                             for j in range(k)])
            if np.allclose(newC, C):
                break
            C = newC
        inertia = ((X - C[labels]) ** 2).sum()
        if best is None or inertia < best[2]:
            best = (labels, C, inertia)
    return best[0], best[1]


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    """Rata-rata silhouette: mendekati 1 = segmen terpisah jelas, mendekati 0 = tumpang tindih."""
    D = np.sqrt(((X[:, None, :] - X[None]) ** 2).sum(-1))
    s = []
    for i in range(len(X)):
        same = labels == labels[i]
        if same.sum() <= 1:
            s.append(0.0)
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, labels == j].mean() for j in set(labels) if j != labels[i])
        s.append((b - a) / max(a, b))
    return float(np.mean(s))


# ---------------------------------------------------------------------------
# 3. Model
# ---------------------------------------------------------------------------
@dataclass
class Model:
    cutoff: pd.Timestamp | None
    lines: pd.DataFrame                 # transaksi yang dilihat model
    products: pd.DataFrame
    customers: pd.DataFrame
    owned: dict                         # customerNumber -> set produk yang sudah dibeli
    popularity: pd.DataFrame            # produk diurutkan dari jumlah pembeli terbanyak
    line_spend: pd.DataFrame            # pelanggan x lini produk, nilai belanja
    item_sim: pd.DataFrame              # produk x produk, cosine similarity
    seg_labels: pd.Series               # customerNumber -> id segmen
    seg_profile: pd.DataFrame           # ringkasan per segmen
    silhouette: float
    seg_features: pd.DataFrame = field(repr=False, default=None)
    k_scores: list = field(default_factory=list)   # [(k, silhouette, ukuran segmen)]
    buyers: dict = field(default_factory=dict)     # productCode -> set pelanggan pembeli


def build_model(data: dict, cutoff: str | None = None, k_range=range(3, 7)) -> Model:
    lines = data["lines"]
    cut = pd.Timestamp(cutoff) if cutoff else None
    if cut is not None:
        lines = lines[lines["orderDate"] < cut]
    products = data["products"]
    all_codes = products.index.tolist()

    owned = lines.groupby("customerNumber")["productCode"].apply(set).to_dict()

    # Popularitas: jumlah pelanggan berbeda yang membeli, lalu nilai penjualan
    pop = (lines.groupby("productCode")
                .agg(pembeli=("customerNumber", "nunique"), nilai=("nilai", "sum"))
                .reindex(all_codes, fill_value=0)
                .sort_values(["pembeli", "nilai"], ascending=False))
    pop["peringkat"] = range(1, len(pop) + 1)

    # Matriks biner pelanggan x produk, lalu cosine similarity antar produk
    M = (lines.assign(v=1).pivot_table(index="customerNumber", columns="productCode",
                                       values="v", aggfunc="max", fill_value=0)
              .reindex(columns=all_codes, fill_value=0))
    A = M.to_numpy(dtype=float)
    norm = np.linalg.norm(A, axis=0)
    norm[norm == 0] = 1.0
    S = (A.T @ A) / np.outer(norm, norm)
    np.fill_diagonal(S, 0.0)
    item_sim = pd.DataFrame(S, index=all_codes, columns=all_codes)

    # Segmen dibentuk dari PORSI BELANJA PER LINI PRODUK (selera pelanggan), bukan RFM.
    # Alasan: tujuan segmen di sini adalah rekomendasi produk. Uji coba dengan RFM memberi
    # silhouette lebih tinggi (sekitar 0,44) tetapi hanya memisahkan pelanggan besar vs kecil,
    # dengan satu segmen berisi 2 pelanggan. RFM tetap dipakai untuk profil segmen.
    lp = lines.merge(products[["productLine"]], left_on="productCode", right_index=True)
    line_spend = lp.pivot_table(index="customerNumber", columns="productLine",
                                values="nilai", aggfunc="sum", fill_value=0.0)
    ref = lines["orderDate"].max()
    rfm = lines.groupby("customerNumber").agg(
        recency=("orderDate", lambda d: (ref - d.max()).days),
        frequency=("orderNumber", "nunique"),
        monetary=("nilai", "sum"))
    share = line_spend.div(line_spend.sum(axis=1), axis=0)
    feats = share.add_prefix("porsi_")
    X = ((feats - feats.mean()) / feats.std(ddof=0).replace(0, 1)).to_numpy()

    best, k_scores = None, []
    for k in k_range:
        labels, _ = _kmeans(X, k)
        sil = _silhouette(X, labels)
        k_scores.append((k, sil, sorted(np.bincount(labels).tolist(), reverse=True)))
        if best is None or sil > best[1]:
            best = (labels, sil)
    labels, sil = best
    seg = pd.Series(labels, index=feats.index, name="segmen")

    # Profil dan nama segmen yang bisa dibaca manusia
    prof = rfm.join(share).assign(segmen=seg).groupby("segmen").agg(
        pelanggan=("frequency", "size"), rata_order=("frequency", "mean"),
        rata_belanja=("monetary", "mean"), rata_recency_hari=("recency", "mean"),
        **{f"porsi_{c}": (c, "mean") for c in share.columns})
    porsi_cols = [c for c in prof.columns if c.startswith("porsi_")]
    overall = share.mean()
    tiers = prof["rata_belanja"].rank(ascending=False, method="first")
    names, ciri = {}, {}
    for sid, row in prof.iterrows():
        # Nama memakai lini dengan kenaikan porsi terbesar dibanding rata-rata semua pelanggan,
        # karena Classic Cars dominan di hampir semua segmen dan tidak membedakan
        lift = {c.replace("porsi_", ""): row[c] / overall[c.replace("porsi_", "")]
                for c in porsi_cols if overall[c.replace("porsi_", "")] > 0}
        top_line = max(lift, key=lift.get)
        porsi_top = row["porsi_" + top_line]
        if porsi_top < 0.10:
            # Kenaikan besar dari angka kecil (misal 2% ke 4%) bukan ciri yang berarti
            label = "Beragam lini"
            ciri[sid] = (f"Tidak ada lini yang menonjol: lini dengan kenaikan terbesar ({top_line}) "
                         f"hanya {porsi_top:.0%} dari belanja. Belanja tersebar di banyak lini.")
        else:
            label = f"Condong {top_line}"
            ciri[sid] = (f"Porsi belanja {top_line} rata-rata {porsi_top:.0%}, dibanding "
                         f"{overall[top_line]:.0%} pada semua pelanggan ({lift[top_line]:.1f}x). "
                         f"Nama segmen memakai lini yang paling membedakan, bukan lini dengan "
                         f"belanja terbesar.")
        tier = ("belanja besar" if tiers[sid] == 1 else
                "belanja kecil" if tiers[sid] == len(prof) else "belanja menengah")
        names[sid] = f"{label} · {tier}"
    # Nama kembar diberi nomor
    seen = {}
    for sid in sorted(names):
        n = names[sid]
        seen[n] = seen.get(n, 0) + 1
        if list(names.values()).count(n) > 1:
            names[sid] = f"{n} ({seen[n]})"
    prof.insert(0, "nama", prof.index.map(names))
    prof.insert(1, "ciri", prof.index.map(ciri))

    return Model(cutoff=cut, lines=lines, products=products, customers=data["customers"],
                 owned=owned, popularity=pop, line_spend=line_spend, item_sim=item_sim,
                 seg_labels=seg, seg_profile=prof, silhouette=sil, seg_features=feats,
                 k_scores=k_scores,
                 buyers=lines.groupby("productCode")["customerNumber"].apply(set).to_dict())


def credit_status(data: dict, cust: int) -> dict:
    """Status kredit dan alasan penahanan penawaran. Selalu memakai seluruh data (kondisi terkini)."""
    lines = data["lines"]
    penjualan = float(lines.loc[lines.customerNumber == cust, "nilai"].sum())
    bayar = float(data["payments"].get(cust, 0.0))
    piutang = penjualan - bayar
    limit = float(data["customers"].loc[cust, "creditLimit"] or 0.0)
    alasan = []
    if limit > 0 and piutang > limit:
        alasan.append(f"piutang USD {piutang:,.0f} melebihi batas kredit USD {limit:,.0f}")
    iss = data["issues"][data["issues"].customerNumber == cust]
    for r in iss.itertuples():
        alasan.append(f"punya {r.jumlah} order berstatus {r.status}")
    return {"penjualan": penjualan, "bayar": bayar, "piutang": piutang, "limit": limit,
            "tahan": bool(alasan), "alasan": alasan}
