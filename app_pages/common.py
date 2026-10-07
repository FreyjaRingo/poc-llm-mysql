"""
Fungsi bersama untuk semua halaman dashboard: akses data, format angka, grafik batang,
sidebar pengaturan, dan penjelasan SQL.

Semua query memakai user read-only llm_reader, sama dengan yang dipakai LLM.
"""
import altair as alt
import mysql.connector
import pandas as pd
import streamlit as st

from core import agent, config, explain, features, pipeline, recommend

SERIES = "#2a78d6"  # satu warna untuk grafik satu seri
NON_CANCEL = "o.status <> 'Cancelled'"  # definisi penjualan, sama dengan business_rules.md
MONEY = st.column_config.NumberColumn(format="localized")


# ---------------------------------------------------------------------------
# Akses data
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Jalankan query read-only dan kembalikan DataFrame. Parameter selalu lewat %s."""
    conn = pipeline.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [tuple(pipeline.to_jsonable(v) for v in r) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=cols)


@st.cache_resource(show_spinner="Menghitung model rekomendasi...")
def _rec_model(version: str):
    data = features.load_data()
    return data, features.build_model(data)


@st.cache_resource(show_spinner="Menjalankan evaluasi split waktu...")
def _rec_eval(version: str):
    data, _ = _rec_model(version)
    return recommend.evaluate(data)


def rec_model():
    # Versi model menjadi bagian kunci cache: kode core/ berubah, cache ikut diganti
    return _rec_model(features.MODEL_VERSION)


def rec_eval():
    return _rec_eval(features.MODEL_VERSION)


# ---------------------------------------------------------------------------
# Format dan grafik
# ---------------------------------------------------------------------------
def usd(x) -> str:
    """Angka ringkas agar muat di kartu KPI, tanpa simbol mata uang: 9,37 jt / 511,5 rb."""
    if x is None or pd.isna(x):
        return "-"
    x = float(x)
    for batas, akhiran, des in ((1e9, "M", 2), (1e6, "jt", 2), (1e3, "rb", 1)):
        if abs(x) >= batas:
            return f"{x / batas:.{des}f} {akhiran}".replace(".", ",")
    return f"{x:,.0f}"


def bar(df: pd.DataFrame, x: str, y: str, x_title: str, y_title: str,
        horizontal: bool = False, sort=None, height: int = 300):
    """Grafik batang satu seri dengan tooltip."""
    enc_val = alt.X(f"{y}:Q", title=y_title) if horizontal else alt.Y(f"{y}:Q", title=y_title)
    enc_cat = (alt.Y(f"{x}:N", title=None, sort=sort or "-x", axis=alt.Axis(labelLimit=320))
               if horizontal
               else alt.X(f"{x}:O", title=None, sort=sort))
    chart = (alt.Chart(df)
             .mark_bar(color=SERIES, cornerRadiusEnd=4)
             .encode(enc_cat, enc_val,
                     tooltip=[alt.Tooltip(f"{x}", title=x_title),
                              alt.Tooltip(f"{y}:Q", title=y_title, format=",.0f")])
             .properties(height=height))
    st.altair_chart(chart, width="stretch", alt=f"{y_title} per {x_title.lower()}")


def card_title(text: str, caption: str | None = None):
    """Judul kecil di dalam kartu, opsional dengan keterangan."""
    st.markdown(f"**{text}**")
    if caption:
        st.caption(caption)


def first_upper(t: str) -> str:
    return t[:1].upper() + t[1:]


# ---------------------------------------------------------------------------
# Sidebar: status koneksi dan pengaturan AI (berlaku untuk semua halaman)
# ---------------------------------------------------------------------------
def sidebar():
    with st.sidebar:
        st.markdown("### :material/database: PoC LLM x MySQL")
        try:
            meta = q("SELECT MIN(orderDate) AS awal, MAX(orderDate) AS akhir FROM orders")
        except mysql.connector.Error as e:
            st.error(f"Gagal terhubung ke MySQL: {e.msg}", icon=":material/error:")
            st.caption("Pastikan MySQL di Laragon sudah menyala, lalu muat ulang halaman.")
            st.stop()
        st.badge(f"{config.DB_NAME} · {config.DB_READER_USER}", icon=":material/check_circle:",
                 color="green", help="Terhubung dengan user read-only")
        st.caption(f"Data order {meta.awal[0]} s.d. {meta.akhir[0]}. Nilai uang dalam USD (asumsi).")

        st.markdown("#### :material/tune: Pengaturan AI")
        agent_on = st.toggle("Mode agent (tool calling)", value=True, key="use_agent",
                             help="DeepSeek memilih alat: query database, rekomendasi produk, atau "
                                  "profil pelanggan. Jika mati, semua pertanyaan lewat jalur SQL saja")
        st.toggle("Kirim definisi bisnis", value=True, key="use_rules",
                  help="context/business_rules.md ikut dikirim ke DeepSeek")
        st.toggle("Mode thinking", value=True, key="use_thinking",
                  help="Lebih patuh pada aturan, sedikit lebih lambat")
        # Dua pengaturan ini hanya berlaku di mode SQL. Di mode agent, hasil query selalu
        # dikirim ke DeepSeek (agent butuh hasilnya untuk menjawab) dan grafik selalu
        # dipilih aturan otomatis.
        st.toggle("Kirim hasil query untuk dirangkum", value=True, key="use_summary",
                  disabled=agent_on,
                  help="Hanya untuk mode SQL. Di mode agent, maksimal 30 baris hasil query "
                       "selalu dikirim ke DeepSeek karena agent butuh hasilnya untuk menjawab")
        st.toggle("AI memilih jenis grafik", value=False, key="use_chart_ai", disabled=agent_on,
                  help="Hanya untuk mode SQL. Jika mati, grafik dipilih aturan otomatis dari bentuk "
                       "tabel. Jika hidup, DeepSeek mengusulkan grafik dan sistem memvalidasinya")
        if agent_on:
            st.caption(":material/info: Di mode agent, hasil query selalu dikirim ke DeepSeek "
                       "dan grafik dipilih aturan otomatis.")
        st.caption(f"Model `{config.LLM_MODEL}`")
        if st.button("Muat ulang data", icon=":material/refresh:", width="stretch"):
            st.cache_data.clear()
            st.cache_resource.clear()
            agent.reset_cache()
            st.rerun()


def settings() -> dict:
    """Nilai pengaturan dari sidebar."""
    s = st.session_state
    agent_on = s.get("use_agent", True)
    return {"agent": agent_on, "rules": s.get("use_rules", True),
            "thinking": s.get("use_thinking", True),
            "summary": s.get("use_summary", True),
            "chart_ai": s.get("use_chart_ai", False) and not agent_on}


def apply_llm_settings():
    """Terapkan pengaturan sidebar ke config sebelum memanggil DeepSeek."""
    s = settings()
    config.INCLUDE_BUSINESS_RULES = s["rules"]
    config.LLM_THINKING = "enabled" if s["thinking"] else "disabled"


# ---------------------------------------------------------------------------
# Penjelasan SQL (dibuat parser, bukan LLM)
# ---------------------------------------------------------------------------
def show_sql_explanation(sql: str):
    """Langkah perhitungan, asumsi LLM, arti kolom, dan pemeriksaan keamanan."""
    info = explain.explain_sql(sql)
    st.markdown("**Langkah perhitungan**")
    st.caption("Diurai otomatis dari SQL oleh parser, bukan oleh LLM.")
    st.markdown(explain.to_markdown(info))
    if info.get("asumsi"):
        st.markdown("**Asumsi yang ditulis LLM:** " + "; ".join(info["asumsi"]))
    if info.get("kolom_dipakai"):
        st.markdown("**Arti kolom**")
        st.caption("Dari COMMENT kolom di database.")
        st.dataframe(pd.DataFrame(info["kolom_dipakai"], columns=["kolom", "arti"]),
                     hide_index=True, width="stretch", alt="Arti kolom yang dipakai query")
    st.markdown("**Pemeriksaan sebelum dijalankan**")
    for label, ok in explain.validation_checklist(sql):
        icon = ":green[:material/check_circle:]" if ok else ":orange[:material/warning:]"
        st.markdown(f"{icon} {label}")
    st.code(sql, language="sql", wrap_lines=True)
