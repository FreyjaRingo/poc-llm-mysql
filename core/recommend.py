"""
Lima metode rekomendasi produk untuk satu pelanggan.

  populer     produk dengan pembeli terbanyak (baseline)
  segmen      produk terlaris di segmen pelanggan (k-means)
  similarity  produk yang mirip dengan produk yang sudah dibeli (item-based cosine)
  rule        aturan bisnis eksplisit berbasis lini produk utama pelanggan
  llm         DeepSeek memilih dari katalog, hasilnya divalidasi

Aturan bersama: produk yang sudah pernah dibeli pelanggan tidak direkomendasikan.
Setiap fungsi mengembalikan DataFrame: productCode, skor, alasan.
"""
import json

import numpy as np
import pandas as pd

from core import pipeline
from core.features import Model

METHODS = {"populer": "Populer", "segmen": "Segmen", "similarity": "Similarity",
           "rule": "Rule-based", "llm": "LLM", "acak": "Acak (pembanding)"}
K = 10


def _not_owned(model: Model, cust: int) -> list:
    owned = model.owned.get(cust, set())
    return [p for p in model.popularity.index if p not in owned]


def _frame(rows: list) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["productCode", "skor", "alasan"])


def _name(model: Model, code: str) -> str:
    return model.products.loc[code, "productName"]


# ---------------------------------------------------------------------------
# Metode 1: populer
# ---------------------------------------------------------------------------
def rec_populer(model: Model, cust: int, k: int = K) -> pd.DataFrame:
    pop = model.popularity
    rows = [(p, float(pop.loc[p, "pembeli"]),
             f"Produk ke-{int(pop.loc[p, 'peringkat'])} terpopuler, dibeli "
             f"{int(pop.loc[p, 'pembeli'])} pelanggan")
            for p in _not_owned(model, cust)[:k]]
    return _frame(rows)


# ---------------------------------------------------------------------------
# Metode 2: segmen
# ---------------------------------------------------------------------------
def rec_segmen(model: Model, cust: int, k: int = K) -> pd.DataFrame:
    if cust not in model.seg_labels.index:
        df = rec_populer(model, cust, k)
        df["alasan"] = "Belum punya riwayat, belum masuk segmen. " + df["alasan"]
        return df
    sid = model.seg_labels[cust]
    members = model.seg_labels.index[model.seg_labels == sid]
    seg_lines = model.lines[model.lines.customerNumber.isin(members)]
    seg_pop = (seg_lines.groupby("productCode")
                        .agg(pembeli=("customerNumber", "nunique"), nilai=("nilai", "sum"))
                        .sort_values(["pembeli", "nilai"], ascending=False))
    owned = model.owned.get(cust, set())
    nama = model.seg_profile.loc[sid, "nama"]
    rows = []
    for p, r in seg_pop.iterrows():
        if p in owned:
            continue
        rows.append((p, float(r.pembeli),
                     f"Dibeli {int(r.pembeli)} dari {len(members)} pelanggan di segmen '{nama}'"))
        if len(rows) == k:
            break
    if len(rows) < k:  # segmen kecil: lengkapi dengan populer global
        have = {r[0] for r in rows}
        for _, r in rec_populer(model, cust, k * 2).iterrows():
            if r.productCode not in have:
                rows.append((r.productCode, 0.0, "Pelengkap: " + r.alasan))
            if len(rows) == k:
                break
    return _frame(rows)


# ---------------------------------------------------------------------------
# Metode 3: similarity
# ---------------------------------------------------------------------------
def rec_similarity(model: Model, cust: int, k: int = K) -> pd.DataFrame:
    owned = [p for p in model.owned.get(cust, set()) if p in model.item_sim.columns]
    if not owned:
        df = rec_populer(model, cust, k)
        df["alasan"] = "Belum punya riwayat. " + df["alasan"]
        return df
    sim = model.item_sim[owned]                 # kandidat x produk yang dimiliki
    skor = sim.sum(axis=1).drop(index=owned, errors="ignore")
    skor = skor[skor > 0].sort_values(ascending=False)   # tanpa kemiripan = bukan rekomendasi
    rows = []
    for p in skor.index[:k]:
        top = sim.loc[p].idxmax()
        rows.append((p, float(skor[p]),
                     f"Mirip dengan '{_name(model, top)}' yang sudah dibeli "
                     f"(kemiripan {sim.loc[p, top]:.2f})"))
    return _frame(rows)


# ---------------------------------------------------------------------------
# Metode 4: rule-based
# ---------------------------------------------------------------------------
RULE_QUOTA_MAIN = 6     # maksimal dari lini utama
RULE_QUOTA_SECOND = 2   # maksimal dari lini kedua


def rec_rule(model: Model, cust: int, k: int = K) -> pd.DataFrame:
    """
    Aturan:
      R1  Lini utama (belanja terbesar): produk terpopuler yang belum dibeli, maks 6.
      R2  Lini kedua: produk terpopuler yang belum dibeli, maks 2.
      R3  Lini yang belum pernah dibeli (cross-sell): produk terlaris tiap lini, satu per lini.
      R4  Sisa slot diisi produk terpopuler global.
    """
    not_owned = _not_owned(model, cust)
    prods = model.products
    if cust not in model.line_spend.index:
        df = rec_populer(model, cust, k)
        df["alasan"] = "R4 (belum punya riwayat): " + df["alasan"]
        return df
    spend = model.line_spend.loc[cust]
    spend = spend[spend > 0].sort_values(ascending=False)
    total = spend.sum()
    rows, used = [], set()

    def take(line, quota, label):
        n = 0
        for p in not_owned:
            if len(rows) >= k or n >= quota:
                break
            if p not in used and prods.loc[p, "productLine"] == line:
                rows.append((p, float(model.popularity.loc[p, "pembeli"]), label))
                used.add(p)
                n += 1

    lines_by_spend = spend.index.tolist()
    if lines_by_spend:
        l1 = lines_by_spend[0]
        take(l1, RULE_QUOTA_MAIN, f"R1: lini utama pelanggan ({l1}, {spend[l1] / total:.0%} belanja)")
    if len(lines_by_spend) > 1:
        l2 = lines_by_spend[1]
        take(l2, RULE_QUOTA_SECOND, f"R2: lini kedua pelanggan ({l2}, {spend[l2] / total:.0%} belanja)")
    line_rev = model.lines.merge(prods[["productLine"]], left_on="productCode", right_index=True) \
                          .groupby("productLine")["nilai"].sum().sort_values(ascending=False)
    for line in line_rev.index:
        if line not in spend.index:
            take(line, 1, f"R3: cross-sell, pelanggan belum pernah membeli lini {line}")
    for p in not_owned:
        if len(rows) >= k:
            break
        if p not in used:
            rows.append((p, float(model.popularity.loc[p, "pembeli"]), "R4: pelengkap dari produk terpopuler"))
            used.add(p)
    return _frame(rows[:k])


# ---------------------------------------------------------------------------
# Metode 5: LLM
# ---------------------------------------------------------------------------
LLM_SYSTEM = """Anda analis penjualan untuk perusahaan grosir model kendaraan skala.
Tugas: pilih produk yang paling mungkin dibeli pelanggan berikutnya.

Aturan:
- Pilih tepat {k} produk, HANYA dari KATALOG_KANDIDAT. Jangan mengarang kode produk.
- Dasarkan pilihan pada pola belanja pelanggan (lini produk, skala, pembuat, kisaran harga)
  dan popularitas produk. Jangan memakai pengetahuan di luar data yang diberikan.
- Alasan harus spesifik dan merujuk ke data pelanggan, maksimal 25 kata.
- Balas HANYA dengan JSON:
{{"rekomendasi": [{{"kode": "<productCode>", "alasan": "<alasan>"}}], "ringkasan": "<2 kalimat pola pelanggan>"}}"""


def _llm_context(model: Model, cust: int) -> str:
    prods = model.products
    c = model.customers.loc[cust]
    owned = model.owned.get(cust, set())
    parts = [f"PELANGGAN: {c.customerName} ({c.country})"]
    if cust in model.line_spend.index:
        spend = model.line_spend.loc[cust]
        spend = spend[spend > 0].sort_values(ascending=False)
        parts.append("Porsi belanja per lini: " + ", ".join(
            f"{l} {v / spend.sum():.0%}" for l, v in spend.items()))
        cl = model.lines[model.lines.customerNumber == cust]
        parts.append(f"Jumlah order: {cl.orderNumber.nunique()}, total belanja USD {cl.nilai.sum():,.0f}, "
                     f"order terakhir {cl.orderDate.max().date()}")
        if cust in model.seg_labels.index:
            parts.append(f"Segmen: {model.seg_profile.loc[model.seg_labels[cust], 'nama']}")
        top = cl.groupby("productCode")["quantityOrdered"].sum().sort_values(ascending=False).head(15)
        parts.append("Produk yang paling banyak dibeli (kode | nama | lini | skala | pembuat | unit):")
        parts += [f"- {p} | {prods.loc[p, 'productName']} | {prods.loc[p, 'productLine']} | "
                  f"{prods.loc[p, 'productScale']} | {prods.loc[p, 'productVendor']} | {int(q)}"
                  for p, q in top.items()]
    else:
        parts.append("Pelanggan belum punya riwayat pembelian.")
    parts.append("\nKATALOG_KANDIDAT (belum pernah dibeli pelanggan ini; "
                 "kode | nama | lini | skala | pembuat | MSRP | peringkat popularitas):")
    for p in _not_owned(model, cust):
        r = prods.loc[p]
        parts.append(f"- {p} | {r.productName} | {r.productLine} | {r.productScale} | "
                     f"{r.productVendor} | {r.MSRP:.0f} | {int(model.popularity.loc[p, 'peringkat'])}")
    return "\n".join(parts)


def rec_llm(model: Model, cust: int, k: int = K) -> dict:
    """Kembalikan {'df', 'ringkasan', 'invalid', 'usage', 'latency_s', 'raw', 'prompt_system', 'prompt_user'}."""
    allowed = set(_not_owned(model, cust))
    system, user = LLM_SYSTEM.format(k=k), _llm_context(model, cust)
    res = pipeline.call_llm(system, user, json_mode=True)
    out = {"ringkasan": "", "invalid": [], "usage": res["usage"],
           "latency_s": res["latency_s"], "raw": res["text"], "df": _frame([]),
           "prompt_system": system, "prompt_user": user}
    try:
        txt = res["text"].strip()
        txt = txt[txt.find("{"): txt.rfind("}") + 1]
        payload = json.loads(txt)
    except (json.JSONDecodeError, ValueError):
        out["invalid"].append("jawaban bukan JSON yang valid")
        return out
    rows, seen = [], set()
    for i, item in enumerate(payload.get("rekomendasi", [])):
        code = str(item.get("kode", "")).strip()
        if code not in allowed:
            out["invalid"].append(code or "(kosong)")
            continue
        if code in seen:
            continue
        seen.add(code)
        rows.append((code, float(k - i), str(item.get("alasan", "")).strip()))
        if len(rows) == k:
            break
    out["df"] = _frame(rows)
    out["ringkasan"] = str(payload.get("ringkasan", "")).strip()
    return out


# ---------------------------------------------------------------------------
# Penjelasan perhitungan (deterministik, bisa dicek ulang manual)
# ---------------------------------------------------------------------------
FORMULA = {
    "populer": ("Skor = jumlah pelanggan berbeda yang pernah membeli produk. Jika sama, "
                "diurutkan dari nilai penjualan. Produk yang sudah dibeli pelanggan dilewati."),
    "segmen": ("1) Setiap pelanggan diubah menjadi porsi belanja per lini produk (7 angka, total 100%). "
               "2) Porsi itu distandarkan lalu dikelompokkan dengan k-means; k dipilih dari 3 sampai 6 "
               "berdasarkan silhouette tertinggi. 3) Skor produk = jumlah anggota segmen yang membelinya."),
    "similarity": ("Kemiripan dua produk A dan B = (pelanggan yang membeli keduanya) / "
                   "akar(pembeli A x pembeli B), yaitu cosine similarity. Skor kandidat = jumlah "
                   "kemiripannya dengan setiap produk yang sudah dibeli pelanggan. Kandidat dengan "
                   "skor 0 tidak direkomendasikan."),
    "rule": (f"R1: dari lini dengan belanja terbesar, ambil produk terpopuler yang belum dibeli "
             f"(maks {RULE_QUOTA_MAIN}). R2: dari lini kedua (maks {RULE_QUOTA_SECOND}). R3: satu produk "
             "terlaris dari setiap lini yang belum pernah dibeli (cross-sell), urut dari lini dengan "
             "penjualan global terbesar. R4: sisa slot diisi produk terpopuler."),
    "llm": ("DeepSeek menerima profil pelanggan dan katalog produk yang belum dibelinya, lalu memilih "
            "10 produk beserta alasannya. Python hanya memeriksa bahwa kode produk ada di katalog. "
            "Alasan ditulis oleh LLM dan tidak dihitung, jadi perlu dicek dengan data di bawah."),
}


def explain_populer(model: Model, recs: pd.DataFrame) -> pd.DataFrame:
    pop = model.popularity
    return pd.DataFrame([{"produk": _name(model, p), "pembeli": int(pop.loc[p, "pembeli"]),
                          "nilai_penjualan": round(float(pop.loc[p, "nilai"]), 2),
                          "peringkat_global": int(pop.loc[p, "peringkat"])}
                         for p in recs["productCode"]])


def explain_segmen(model: Model, cust: int, recs: pd.DataFrame) -> dict:
    out = {"k_scores": pd.DataFrame(model.k_scores, columns=["k", "silhouette", "ukuran_segmen"])}
    if cust not in model.seg_labels.index:
        return out
    sid = model.seg_labels[cust]
    members = model.seg_labels.index[model.seg_labels == sid]
    sp = model.line_spend
    share = sp.div(sp.sum(axis=1), axis=0)
    out["segmen"] = model.seg_profile.loc[sid, "nama"]
    out["ukuran"] = len(members)
    out["porsi"] = pd.DataFrame({"pelanggan_ini": share.loc[cust], "rata_rata_segmen": share.loc[members].mean(),
                                 "rata_rata_semua": share.mean()}).mul(100).round(1).reset_index()                      .rename(columns={"productLine": "lini"})
    out["produk"] = pd.DataFrame([{"produk": _name(model, p),
                                   "pembeli_di_segmen": len(model.buyers.get(p, set()) & set(members)),
                                   "ukuran_segmen": len(members)} for p in recs["productCode"]])
    return out


def explain_similarity(model: Model, cust: int, code: str, top: int = 3) -> dict:
    """Rincian skor similarity satu produk: kontributor terbesar beserta hitungan pembelinya."""
    owned = [p for p in model.owned.get(cust, set()) if p in model.item_sim.columns]
    if not owned:
        return {"skor_total": 0.0, "dari_produk": 0, "kontributor": pd.DataFrame()}
    a = model.buyers.get(code, set())
    rows = []
    for b in owned:
        bb = model.buyers.get(b, set())
        both = len(a & bb)
        sim = both / (len(a) * len(bb)) ** 0.5 if a and bb else 0.0
        rows.append({"produk_yang_dimiliki": _name(model, b), "pembeli_kandidat": len(a),
                     "pembeli_produk_dimiliki": len(bb), "pembeli_keduanya": both,
                     "kemiripan": round(sim, 3)})
    df = pd.DataFrame(rows).sort_values("kemiripan", ascending=False)
    return {"skor_total": round(float(df["kemiripan"].sum()), 3), "dari_produk": len(df),
            "kontributor": df.head(top).reset_index(drop=True)}


def explain_rule(model: Model, cust: int) -> pd.DataFrame:
    if cust not in model.line_spend.index:
        return pd.DataFrame()
    sp = model.line_spend.loc[cust]
    df = pd.DataFrame({"lini": sp.index, "belanja": sp.values.round(2)})
    df["porsi_persen"] = (df.belanja / df.belanja.sum() * 100).round(1)
    df = df.sort_values("belanja", ascending=False).reset_index(drop=True)
    df["peran_dalam_aturan"] = ["R1 lini utama" if i == 0 else "R2 lini kedua" if i == 1 and b > 0
                                else ("R3 cross-sell" if b == 0 else "-")
                                for i, b in enumerate(df.belanja)]
    return df


def check_llm_claims(model: Model, cust: int, recs: pd.DataFrame) -> pd.DataFrame:
    """Data pendukung untuk setiap pilihan LLM, supaya alasannya bisa dicek."""
    if recs.empty:
        return pd.DataFrame()
    share = {}
    if cust in model.line_spend.index:
        sp = model.line_spend.loc[cust]
        share = (sp / sp.sum() * 100).round(1).to_dict()
    owned = model.owned.get(cust, set())
    owned_scales = model.products.loc[list(owned), "productScale"].value_counts() if owned else pd.Series(dtype=int)
    rows = []
    for p in recs["productCode"]:
        r = model.products.loc[p]
        rows.append({"produk": r.productName, "lini": r.productLine,
                     "porsi_pelanggan_di_lini_ini_%": share.get(r.productLine, 0.0),
                     "skala": r.productScale,
                     "produk_dimiliki_dengan_skala_sama": int(owned_scales.get(r.productScale, 0)),
                     "peringkat_popularitas": int(model.popularity.loc[p, "peringkat"])})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Antarmuka bersama
# ---------------------------------------------------------------------------
NON_LLM = {"populer": rec_populer, "segmen": rec_segmen,
           "similarity": rec_similarity, "rule": rec_rule}


def recommend(model: Model, cust: int, method: str, k: int = K) -> pd.DataFrame:
    if method == "llm":
        return rec_llm(model, cust, k)["df"]
    return NON_LLM[method](model, cust, k)


def with_details(model: Model, df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan nama, lini, skala, dan MSRP produk untuk ditampilkan."""
    if df.empty:
        return df.assign(peringkat=[], produk=[], lini=[], skala=[], MSRP=[])
    d = df.join(model.products[["productName", "productLine", "productScale", "MSRP"]],
                on="productCode")
    d.insert(0, "peringkat", range(1, len(d) + 1))
    return d.rename(columns={"productName": "produk", "productLine": "lini",
                             "productScale": "skala"})[
        ["peringkat", "productCode", "produk", "lini", "skala", "MSRP", "alasan"]]


# ---------------------------------------------------------------------------
# Evaluasi split waktu
# ---------------------------------------------------------------------------
def evaluate(data: dict, cutoff: str = "2005-01-01", k: int = K, methods=None,
             llm: bool = False, n_boot: int = 1000, progress=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Latih dengan data sebelum cutoff, uji dengan produk BARU yang dibeli setelah cutoff.
    Kembalikan (ringkasan per metode, detail per pelanggan).
    """
    from core.features import build_model
    model = build_model(data, cutoff)
    test = data["lines"][data["lines"]["orderDate"] >= pd.Timestamp(cutoff)]
    truth = {}
    for cust, g in test.groupby("customerNumber"):
        if cust not in model.owned:
            continue  # tanpa riwayat latih, tidak bisa dinilai secara adil
        new = set(g.productCode) - model.owned[cust]
        if new:
            truth[cust] = new
    methods = ["acak"] + list(methods or NON_LLM) + (["llm"] if llm else [])
    rng_rand = np.random.default_rng(7)
    rows = []
    for i, (cust, actual) in enumerate(sorted(truth.items())):
        # Baseline acak: rata-rata dari 200 kali memilih 10 produk secara acak.
        # Metode yang tidak lebih baik dari ini berarti tidak menangkap pola apa pun.
        cand = _not_owned(model, cust)
        draws = [set(rng_rand.choice(cand, min(k, len(cand)), replace=False)) for _ in range(200)]
        h = [len(d & actual) for d in draws]
        rows.append({"customerNumber": cust, "metode": "acak",
                     "hit": float(np.mean([x > 0 for x in h])), "precision": float(np.mean(h)) / k,
                     "recall": float(np.mean(h)) / len(actual), "jumlah_rek": k,
                     "produk_baru_dibeli": len(actual)})
        for m in methods[1:]:
            if m == "llm":
                r = rec_llm(model, cust, k)
                recs, extra = r["df"].productCode.tolist(), {"invalid": len(r["invalid"])}
            else:
                recs, extra = recommend(model, cust, m, k).productCode.tolist(), {}
            hits = len(set(recs) & actual)
            rows.append({"customerNumber": cust, "metode": m, "hit": int(hits > 0),
                         "precision": hits / k, "recall": hits / len(actual),
                         "jumlah_rek": len(recs), "produk_baru_dibeli": len(actual), **extra})
        if progress:
            progress(i + 1, len(truth))
    detail = pd.DataFrame(rows)
    rng = np.random.default_rng(42)
    summary = []
    for m in methods:
        d = detail[detail.metode == m]
        row = {"metode": METHODS[m], "pelanggan_diuji": len(d)}
        for metric in ("hit", "precision", "recall"):
            v = d[metric].to_numpy()
            boots = [rng.choice(v, len(v)).mean() for _ in range(n_boot)]
            row[metric] = v.mean()
            row[f"{metric}_ci_low"], row[f"{metric}_ci_high"] = np.percentile(boots, [2.5, 97.5])
        summary.append(row)
    return pd.DataFrame(summary), detail
