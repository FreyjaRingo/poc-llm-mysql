"""Halaman data mentah per tabel, hanya kolom yang boleh dibaca llm_reader."""
import streamlit as st

from app_pages.common import q

st.title("Data")
st.caption("Hanya kolom yang boleh dibaca llm_reader yang ditampilkan. Kolom data pribadi tidak "
           "muncul di sini maupun di prompt LLM.")

kolom = q("""SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME, ORDINAL_POSITION""")
tabel = st.pills("Tabel", sorted(kolom.t.unique()), default="customers", key="data_tabel")
if tabel is None:
    st.caption("Pilih salah satu tabel.")
    st.stop()
cols = kolom[kolom.t == tabel].c.tolist()
# Nama tabel dan kolom berasal dari information_schema, bukan dari input pengguna
df = q(f"SELECT {', '.join(f'`{c}`' for c in cols)} FROM `{tabel}` LIMIT 5000")

with st.container(horizontal=True, vertical_alignment="bottom"):
    cari = st.text_input("Cari", "", placeholder="Cari di semua kolom", icon=":material/search:",
                         label_visibility="collapsed", key="data_cari")
    if cari:
        mask = df.astype(str).apply(lambda s: s.str.contains(cari, case=False, regex=False)).any(axis=1)
        df = df[mask]
    st.download_button("Unduh CSV", df.to_csv(index=False).encode("utf-8"), file_name=f"{tabel}.csv",
                       mime="text/csv", icon=":material/download:")

st.caption(f"{len(df):,} baris · {len(cols)} kolom")
st.dataframe(df, hide_index=True, width="stretch", height=520, alt=f"Isi tabel {tabel}")
