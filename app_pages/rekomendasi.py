"""Halaman rekomendasi: lima metode, perbandingan, perhitungan per metode, segmen, dan evaluasi."""
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from app_pages.common import (MONEY, SERIES, bar, card_title, first_upper, rec_eval, rec_model,
                              apply_llm_settings, usd)
from core import features, pipeline, recommend

METODE = ["populer", "segmen", "similarity", "rule", "llm"]

st.title("Rekomendasi produk")
st.caption("Lima metode merekomendasikan 10 produk yang belum pernah dibeli pelanggan. Empat metode "
           "dihitung di laptop Anda tanpa AI. Metode LLM memanggil DeepSeek dan hanya boleh memilih "
           "dari katalog.")

data, model = rec_model()

cust_df = data["customers"].reset_index()
cust_df["aktif"] = cust_df.customerNumber.isin(model.owned.keys())
pick, opt = st.columns([3, 1], vertical_alignment="bottom")
if opt.toggle("Hanya yang pernah order", value=True, key="rek_aktif"):
    cust_df = cust_df[cust_df.aktif]
cust_df = cust_df.sort_values("customerName")
labels = {r.customerNumber: f"{r.customerName} ({r.customerNumber})" for r in cust_df.itertuples()}
cid = pick.selectbox("Pilih pelanggan", list(labels), format_func=labels.get, key="rek_cust",
                     placeholder="Ketik nama pelanggan")
if cid is None:
    st.stop()

# ---------------------------------------------------------------------------
# Profil singkat dan aturan bisnis
# ---------------------------------------------------------------------------
stat = features.credit_status(data, cid)
owned_n = len(model.owned.get(cid, set()))
punya_segmen = cid in model.seg_labels.index
if punya_segmen:
    seg_row = model.seg_profile.loc[model.seg_labels[cid]]
    seg_nama = seg_row["nama"]
    seg_help = seg_row["ciri"] if "ciri" in model.seg_profile.columns else None
else:
    seg_nama, seg_help = "Belum ada", "Pelanggan belum punya riwayat pembelian"
if cid in model.line_spend.index:
    sp = model.line_spend.loc[cid]
    utama, utama_pct = sp.idxmax(), f"{sp.max() / sp.sum():.0%} dari belanja"
else:
    utama, utama_pct = "-", None

with st.container(horizontal=True):
    st.metric("Segmen", seg_nama.split(" · ")[0], border=True, help=seg_help,
              delta=(seg_nama.split(" · ")[1] if " · " in seg_nama else None), delta_color="off",
              delta_arrow="off")
    st.metric("Lini utama", utama, border=True, delta=utama_pct, delta_color="off", delta_arrow="off")
    st.metric("Produk sudah dibeli", f"{owned_n} dari {len(model.products)}", border=True,
              delta=f"{len(model.products) - owned_n} kandidat", delta_color="off", delta_arrow="off")
    st.metric("Piutang (USD)", usd(stat["piutang"]), border=True,
              delta=f"batas kredit {usd(stat['limit'])}", delta_color="off", delta_arrow="off")

if stat["tahan"]:
    st.warning("**Aturan bisnis: penawaran baru sebaiknya ditahan.** "
               + first_upper("; ".join(stat["alasan"]))
               + ". Rekomendasi di bawah tetap ditampilkan sebagai referensi.", icon=":material/block:")

with st.expander("Perhitungan aturan bisnis (kapan penawaran ditahan)", icon=":material/gavel:"):
    st.markdown("Penawaran ditahan jika **piutang > batas kredit** atau pelanggan punya order "
                "berstatus **On Hold** atau **Disputed**. Piutang = total penjualan (tanpa order "
                "Cancelled) dikurangi total pembayaran.")
    st.dataframe(pd.DataFrame([
        {"komponen": "Total penjualan", "nilai_usd": round(stat["penjualan"], 2)},
        {"komponen": "Total pembayaran", "nilai_usd": round(stat["bayar"], 2)},
        {"komponen": "Piutang (penjualan - pembayaran)", "nilai_usd": round(stat["piutang"], 2)},
        {"komponen": "Batas kredit", "nilai_usd": round(stat["limit"], 2)}]),
        hide_index=True, width="stretch", column_config={"nilai_usd": MONEY},
        alt="Perhitungan piutang dan batas kredit")
    st.markdown("Hasil: " + ("; ".join(stat["alasan"]) if stat["tahan"]
                             else "tidak ada aturan yang terpicu, penawaran boleh dilakukan."))

hasil = {m: recommend.with_details(model, recommend.recommend(model, cid, m))
         for m in recommend.NON_LLM}

# ---------------------------------------------------------------------------
# Metode LLM (dijalankan hanya jika diminta)
# ---------------------------------------------------------------------------
key_llm = f"llm_{cid}"
with st.container(horizontal=True, vertical_alignment="center"):
    if st.button("Buat rekomendasi LLM", key=f"btn_{cid}", type="primary", icon=":material/auto_awesome:"):
        apply_llm_settings()
        try:
            with st.spinner("DeepSeek sedang memilih produk..."):
                st.session_state[key_llm] = recommend.rec_llm(model, cid)
            pipeline.write_log({"ts": datetime.now().isoformat(), "source": "rekomendasi_llm",
                                "customerNumber": int(cid),
                                **{k: v for k, v in st.session_state[key_llm].items() if k != "df"},
                                "rekomendasi": st.session_state[key_llm]["df"].to_dict("records")})
        except Exception as e:
            st.session_state[key_llm] = {"error": str(e)}
    st.caption("Memakai model dan mode thinking dari sidebar. Profil pelanggan dan katalog "
               "dikirim ke DeepSeek.")
llm_res = st.session_state.get(key_llm)
if llm_res and "df" in llm_res:
    hasil["llm"] = recommend.with_details(model, llm_res["df"])

# ---------------------------------------------------------------------------
# Perbandingan dan konsensus
# ---------------------------------------------------------------------------
with st.container(border=True):
    card_title("Perbandingan 10 rekomendasi teratas")
    comp = pd.DataFrame({"peringkat": range(1, 11)})
    for m, label in recommend.METHODS.items():
        if m == "acak":
            continue
        names = hasil[m]["produk"].tolist() if m in hasil else []
        comp[label] = names + ["-"] * (10 - len(names))
    # Lebar kolom dikunci supaya kelima metode muat berdampingan tanpa scroll
    st.dataframe(comp, hide_index=True, width="stretch", row_height=38, alt="Perbandingan rekomendasi",
                 column_config={"peringkat": st.column_config.NumberColumn("#", width=40),
                                **{c: st.column_config.TextColumn(c, width=178)
                                   for c in comp.columns if c != "peringkat"}})

    votes = {}
    for m, df in hasil.items():
        for p in df["productCode"]:
            votes.setdefault(p, []).append(recommend.METHODS[m])
    kons = pd.DataFrame([{"produk": model.products.loc[p, "productName"],
                          "lini": model.products.loc[p, "productLine"],
                          "jumlah_metode": len(v), "metode": ", ".join(v)}
                         for p, v in votes.items() if len(v) >= 2])
    if not kons.empty:
        card_title("Disepakati lebih dari satu metode")
        st.dataframe(kons.sort_values("jumlah_metode", ascending=False), hide_index=True,
                     width="stretch", alt="Produk yang disepakati beberapa metode",
                     column_config={"jumlah_metode": st.column_config.ProgressColumn(
                         "jumlah metode", min_value=0, max_value=len(hasil), format="%d")})

# ---------------------------------------------------------------------------
# Detail per metode
# ---------------------------------------------------------------------------
st.subheader("Detail dan alasan per metode")
tabs = st.tabs([recommend.METHODS[m] for m in METODE])
for t, m in zip(tabs, METODE):
    with t:
        st.info(recommend.FORMULA[m], icon=":material/functions:")
        if m == "llm":
            if not llm_res:
                st.caption("Klik **Buat rekomendasi LLM** di atas untuk menjalankan metode ini.")
                continue
            if "error" in llm_res:
                st.error(llm_res["error"], icon=":material/error:")
                continue
            if llm_res["ringkasan"]:
                st.markdown(f"**Ringkasan dari DeepSeek:** {llm_res['ringkasan']}")
            if llm_res["invalid"]:
                st.warning(f"{len(llm_res['invalid'])} kode dari LLM dibuang karena tidak ada "
                           f"di katalog: {', '.join(llm_res['invalid'][:5])}", icon=":material/filter_alt:")
            u = llm_res["usage"] or {}
            st.caption(f"Token input {u.get('input_tokens')} · output {u.get('output_tokens')} · "
                       f"{llm_res['latency_s']} detik")
        if m not in hasil:
            continue
        st.dataframe(hasil[m], hide_index=True, width="stretch", column_config={"MSRP": MONEY},
                     alt=f"Rekomendasi metode {recommend.METHODS[m]}")
        if len(hasil[m]) < 10:
            st.caption(f"Hanya {len(hasil[m])} produk yang memenuhi syarat metode ini.")

        st.markdown("**Perhitungan untuk pelanggan ini**")
        if m == "populer":
            st.dataframe(recommend.explain_populer(model, hasil[m]), hide_index=True,
                         width="stretch", column_config={"nilai_penjualan": MONEY},
                         alt="Perhitungan metode populer")
        elif m == "segmen":
            ex = recommend.explain_segmen(model, cid, hasil[m])
            if "segmen" not in ex:
                st.caption("Pelanggan belum punya riwayat, jadi belum masuk segmen. Dipakai produk populer.")
            else:
                st.markdown(f"Pelanggan masuk segmen **{ex['segmen']}** ({ex['ukuran']} pelanggan). "
                            "Porsi belanjanya (%) dibanding rata-rata segmen dan semua pelanggan:")
                st.dataframe(ex["porsi"], hide_index=True, width="stretch", alt="Porsi belanja per lini")
                st.markdown("Skor setiap produk = berapa anggota segmen yang membelinya:")
                st.dataframe(ex["produk"], hide_index=True, width="stretch", alt="Skor produk di segmen")
            st.markdown("Pemilihan jumlah segmen (k): dipilih silhouette tertinggi.")
            st.dataframe(ex["k_scores"].round(3), hide_index=True, width="stretch",
                         alt="Silhouette per jumlah segmen")
        elif m == "similarity":
            pilihan = st.selectbox("Rincikan skor untuk produk", hasil[m]["productCode"].tolist(),
                                   format_func=lambda c: model.products.loc[c, "productName"],
                                   key=f"simx_{cid}")
            ex = recommend.explain_similarity(model, cid, pilihan)
            if ex["kontributor"].empty:
                st.caption("Pelanggan belum punya riwayat pembelian, jadi tidak ada produk pembanding. "
                           "Metode ini memakai produk populer sebagai gantinya.")
                continue
            st.markdown(f"Skor total **{ex['skor_total']:.3f}** = jumlah kemiripan produk ini dengan "
                        f"{ex['dari_produk']} produk yang sudah dibeli pelanggan. Tiga kontributor terbesar:")
            st.dataframe(ex["kontributor"], hide_index=True, width="stretch", alt="Kontributor skor kemiripan")
            r0 = ex["kontributor"].iloc[0]
            st.markdown(f"Contoh hitung baris pertama: {r0.pembeli_keduanya} / "
                        f"√({r0.pembeli_kandidat} × {r0.pembeli_produk_dimiliki}) = **{r0.kemiripan:.3f}**")
        elif m == "rule":
            st.markdown("Belanja pelanggan per lini dan peran setiap lini dalam aturan:")
            st.dataframe(recommend.explain_rule(model, cid), hide_index=True, width="stretch",
                         column_config={"belanja": MONEY}, alt="Belanja per lini dan peran aturan")
            st.caption("Aturan yang memicu setiap produk tertulis di kolom 'alasan' pada tabel di atas.")
        elif m == "llm":
            st.markdown("Data pendukung untuk mengecek alasan LLM (dihitung Python dari data):")
            st.dataframe(recommend.check_llm_claims(model, cid, llm_res["df"]),
                         hide_index=True, width="stretch", alt="Data pendukung alasan LLM")
            with st.expander("Apa yang dikirim ke DeepSeek", icon=":material/upload:"):
                st.code(llm_res.get("prompt_system", ""), language="text")
                st.code(llm_res.get("prompt_user", ""), language="text")
            with st.expander("Jawaban mentah DeepSeek", icon=":material/data_object:"):
                st.code(llm_res.get("raw", ""), language="json")

# ---------------------------------------------------------------------------
# Segmen dan evaluasi
# ---------------------------------------------------------------------------
st.subheader("Tentang model")
with st.expander("Segmen pelanggan", icon=":material/groups:"):
    st.caption(f"Segmen dibentuk dengan k-means dari porsi belanja per lini produk. "
               f"Silhouette {model.silhouette:.2f} (0 = tumpang tindih, 1 = terpisah jelas). "
               "Nilai di bawah 0,3 berarti batas antar segmen tidak tegas.")
    prof = model.seg_profile.reset_index(drop=True)
    bar(prof[["nama", "pelanggan"]], "nama", "pelanggan", "Segmen", "Jumlah pelanggan",
        horizontal=True, height=220)
    st.dataframe(prof.round(2), hide_index=True, width="stretch", alt="Profil segmen")

with st.expander("Seberapa bagus metodenya? (evaluasi)", icon=":material/fact_check:"):
    st.caption("Model dilatih dengan transaksi sampai 31 Des 2004, lalu diuji: dari 10 rekomendasi, "
               "berapa yang benar-benar dibeli pelanggan pada Jan sampai Mei 2005. Angka dalam "
               "kurung adalah selang kepercayaan 95%. Metode LLM dievaluasi lewat "
               "`python evaluate_rec.py --with-llm`.")
    summ, _ = rec_eval()
    base = summ.loc[summ.metode.str.startswith("Acak"), "hit"].iloc[0]

    def verdict(r):
        if r.metode.startswith("Acak"):
            return "pembanding"
        if r.hit_ci_low > base:
            return "lebih baik dari acak"
        if r.hit_ci_high < base:
            return "lebih buruk dari acak"
        return "tidak berbeda bermakna dari acak"

    tampil = pd.DataFrame({
        "metode": summ.metode,
        "hit rate": summ.apply(lambda r: f"{r.hit:.0%} ({r.hit_ci_low:.0%} - {r.hit_ci_high:.0%})", axis=1),
        "precision@10": summ.apply(lambda r: f"{r.precision:.1%}", axis=1),
        "recall@10": summ.apply(lambda r: f"{r.recall:.1%}", axis=1),
        "kesimpulan": summ.apply(verdict, axis=1)})
    st.dataframe(tampil, hide_index=True, width="stretch", alt="Hasil evaluasi rekomendasi")
    ev = summ.assign(hit_pct=summ.hit * 100, lo=summ.hit_ci_low * 100, hi=summ.hit_ci_high * 100,
                     peran=summ.metode.map(lambda m: "pembanding" if m.startswith("Acak") else "metode"))
    bars = alt.Chart(ev).mark_bar(cornerRadiusEnd=4).encode(
        alt.Y("metode:N", title=None, sort=None),
        alt.X("hit_pct:Q", title="Hit rate (%)", scale=alt.Scale(domain=[0, 100])),
        alt.Color("peran:N", scale=alt.Scale(domain=["metode", "pembanding"],
                                             range=[SERIES, "#9b9a95"]), legend=None),
        tooltip=[alt.Tooltip("metode"), alt.Tooltip("hit_pct:Q", title="hit rate (%)", format=".1f"),
                 alt.Tooltip("lo:Q", title="batas bawah", format=".1f"),
                 alt.Tooltip("hi:Q", title="batas atas", format=".1f")])
    err = alt.Chart(ev).mark_rule(color="#52514e", strokeWidth=2).encode(
        alt.Y("metode:N", sort=None), alt.X("lo:Q"), alt.X2("hi:Q"))
    st.altair_chart((bars + err).properties(height=240), width="stretch",
                    alt="Hit rate per metode dengan selang kepercayaan")
    st.caption("Garis hitam adalah selang kepercayaan. Bar abu-abu adalah rekomendasi acak. "
               "Metode yang selangnya mencakup nilai acak belum terbukti lebih baik dari menebak.")
