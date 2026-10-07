"""
Dashboard PoC LLM + MySQL (classicmodels).

Jalankan:  python -m streamlit run app.py

File ini hanya mengatur halaman, sidebar, dan navigasi. Isi setiap halaman ada di
app_pages/. Hanya halaman yang sedang dibuka yang dijalankan, jadi bertanya ke AI tidak
ikut menghitung ulang halaman lain.
"""
import streamlit as st

from app_pages import common

st.set_page_config(page_title="PoC LLM x MySQL", page_icon=":material/database:", layout="wide")

common.sidebar()

pg = st.navigation([
    st.Page("app_pages/ringkasan.py", title="Ringkasan", icon=":material/dashboard:", default=True),
    st.Page("app_pages/pelanggan.py", title="Detail pelanggan", icon=":material/person:"),
    st.Page("app_pages/rekomendasi.py", title="Rekomendasi", icon=":material/recommend:"),
    st.Page("app_pages/data.py", title="Data", icon=":material/table_chart:"),
    st.Page("app_pages/tanya_ai.py", title="Tanya AI", icon=":material/forum:"),
], position="top")
pg.run()
