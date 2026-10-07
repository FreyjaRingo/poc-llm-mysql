"""Halaman Tanya AI: mode agent (tool calling) atau mode SQL, dengan grafik dan penjelasan."""
from datetime import datetime

import mysql.connector
import pandas as pd
import streamlit as st

from app_pages.common import apply_llm_settings, settings, show_sql_explanation
from core import agent, charts, config, pipeline

S = settings()
TOOL_LABEL = {"query_database": ("Query database", ":material/database:"),
              "get_recommendations": ("Rekomendasi produk", ":material/recommend:"),
              "get_customer_profile": ("Profil pelanggan", ":material/person:")}

if "riwayat" not in st.session_state:
    st.session_state.riwayat = []      # urut dari yang paling lama
if "agent_hist" not in st.session_state:
    st.session_state.agent_hist = []   # pesan teks sebelumnya, untuk pertanyaan lanjutan

head, act = st.columns([4, 1], vertical_alignment="bottom")
head.title("Tanya AI")
with act.container(horizontal_alignment="right"):
    if st.button("Percakapan baru", icon=":material/add_comment:", disabled=not st.session_state.riwayat):
        st.session_state.riwayat = []
        st.session_state.agent_hist = []
        st.rerun()

if S["agent"]:
    st.caption(":blue-badge[:material/smart_toy: Mode agent] DeepSeek memilih alat (query database, "
               "rekomendasi produk, atau profil pelanggan), Python menjalankannya, lalu DeepSeek "
               "menjelaskan hasilnya.")
    contoh = ["Berapa total penjualan tahun 2004?",
              "Rekomendasi produk untuk AV Stores",
              "Bagaimana profil Mini Gifts Distributors?",
              "Pelanggan mana yang piutangnya terbesar, dan apa rekomendasi untuknya?"]
else:
    st.caption(":gray-badge[:material/code: Mode SQL] Pertanyaan diterjemahkan DeepSeek menjadi SQL, "
               "divalidasi, lalu dijalankan dengan user read-only.")
    contoh = ["Berapa total penjualan tahun 2004?",
              "Siapa sales rep dengan penjualan terbesar?",
              "Pelanggan mana yang piutangnya melebihi batas kredit?",
              "Produk apa yang paling sering dibeli pelanggan dari Prancis?"]
st.caption(":orange[:material/cloud_upload:] Pertanyaan dan hasil query dikirim ke server DeepSeek. "
           "Jangan dipakai untuk data internal.")


# ---------------------------------------------------------------------------
# Menjalankan pertanyaan
# ---------------------------------------------------------------------------
def run_agent(pertanyaan: str) -> dict:
    item = {"q": pertanyaan, "ts": datetime.now().strftime("%H:%M:%S"), "mode": "agent"}
    record = {"ts": datetime.now().isoformat(), "source": "dashboard_agent",
              "model": config.LLM_MODEL, "thinking": config.LLM_THINKING,
              "business_rules": config.INCLUDE_BUSINESS_RULES, "question": pertanyaan}
    try:
        res = agent.run(pertanyaan, st.session_state.agent_hist[-6:])
        for stp in res["steps"]:
            if stp["tool"] == "query_database" and stp["df"] is not None:
                stp["chart"] = charts.choose(stp["df"], None, stp["args"].get("pertanyaan", ""))
        item.update(answer=res["answer"], steps=res["steps"], usage=res["usage"],
                    latency=res["latency_s"])
        record.update(answer=res["answer"], usage=res["usage"], latency_s=res["latency_s"],
                      steps=[{"tool": s_["tool"], "args": s_["args"], "payload": s_["payload"]}
                             for s_ in res["steps"]])
        st.session_state.agent_hist += [{"role": "user", "content": pertanyaan},
                                        {"role": "assistant", "content": res["answer"]}]
    except Exception as e:
        item["error"] = str(e)
        record["error"] = str(e)
    finally:
        pipeline.write_log(record)
    return item


def run_sql(pertanyaan: str) -> dict:
    item = {"q": pertanyaan, "ts": datetime.now().strftime("%H:%M:%S")}
    record = {"ts": datetime.now().isoformat(), "source": "dashboard",
              "model": config.LLM_MODEL, "thinking": config.LLM_THINKING,
              "business_rules": config.INCLUDE_BUSINESS_RULES, "question": pertanyaan}
    conn = pipeline.get_connection()
    try:
        gen = pipeline.generate_sql(conn, pertanyaan, want_chart=S["chart_ai"])
        record.update({k: v for k, v in gen.items() if k != "system_prompt"})
        item.update(sql=gen["raw_sql"], usage=gen["usage"], latency=gen["llm_latency_s"])
        if gen["rejected"]:
            item["rejected"] = gen["rejected"]
        else:
            item["final_sql"] = gen["final_sql"]
            try:
                res = pipeline.execute_sql(conn, gen["final_sql"])
                item["df"] = pd.DataFrame(
                    [tuple(pipeline.to_jsonable(v) for v in r) for r in res["rows"]],
                    columns=res["columns"])
                record["row_count"] = len(res["rows"])
                item["chart"] = charts.choose(item["df"], gen.get("chart_spec"), pertanyaan)
                record["chart"] = item["chart"]
                if S["summary"]:
                    s = pipeline.summarize(pertanyaan, gen["final_sql"], res)
                    item["summary"] = s["text"]
                    record["summary"] = s["text"]
            except mysql.connector.Error as e:
                item["db_error"] = str(e)
                record["db_error"] = str(e)
    except Exception as e:  # API key kosong, jaringan, saldo habis, dsb.
        item["error"] = str(e)
        record["error"] = str(e)
    finally:
        conn.close()
        pipeline.write_log(record)
    return item


# ---------------------------------------------------------------------------
# Menampilkan jawaban
# ---------------------------------------------------------------------------
def show_result(df: pd.DataFrame, chart: dict | None, key: str):
    """Grafik di atas, tabel hasil lengkap di bawahnya."""
    if chart and chart["type"] not in ("none",):
        charts.render(st, df, chart)
        st.caption(f":material/bar_chart: {chart['type']} · {chart.get('source', 'aturan otomatis')}"
                   + (f" · {chart['reason']}" if chart.get("reason") else ""))
    if chart is not None and chart["type"] == "metric":
        return
    # Kolom desimal ditampilkan dengan pemisah ribuan. Kolom bilangan bulat (tahun, bulan, ID)
    # dibiarkan apa adanya supaya 2004 tidak tampil sebagai 2,004.
    cfg = {c: st.column_config.NumberColumn(format="localized")
           for c in df.columns if pd.api.types.is_float_dtype(df[c])}
    tabel = lambda: st.dataframe(df, hide_index=True, width="stretch", key=key, alt="Hasil query",
                                 column_config=cfg, height=min(400, 38 + 35 * len(df)))
    if chart and chart["type"] != "none":
        with st.expander(f"Tabel hasil ({len(df)} baris)", type="compact", icon=":material/table:"):
            tabel()
    else:
        tabel()


def usage_line(it: dict, extra: str = "") -> str:
    u = it.get("usage") or {}
    return (f"{it['ts']}{extra} · token input {u.get('input_tokens')} "
            f"(cache {u.get('cache_hit_tokens')}) · output {u.get('output_tokens')} · "
            f"{it.get('latency')} detik")


def show_agent(it: dict, idx: int):
    st.markdown(it["answer"] or "_(tidak ada jawaban teks)_")
    # Hasil alat tampil langsung karena itu bukti jawabannya
    for n, stp in enumerate(it["steps"]):
        pl = stp["payload"]
        if pl.get("peringatan_aturan_bisnis"):
            st.warning(pl["peringatan_aturan_bisnis"], icon=":material/block:")
        if stp["df"] is None:
            continue
        label, icon = TOOL_LABEL.get(stp["tool"], (stp["tool"], ":material/build:"))
        with st.container(border=True):
            if stp["tool"] == "query_database":
                show_result(stp["df"], stp.get("chart"), key=f"res_{idx}_{n}")
            else:
                st.markdown(f"{icon} **{label}**")
                # Tabel profil berisi campuran angka dan teks per baris: tampilkan sebagai teks
                show = stp["df"].astype({c: str for c in stp["df"].columns
                                         if stp["df"][c].dtype == object})
                st.dataframe(show, hide_index=True, width="stretch", key=f"res_{idx}_{n}",
                             alt=label, height=min(400, 38 + 35 * len(stp["df"])))
    if it["steps"]:
        with st.expander(f"Cara kerja · {len(it['steps'])} pemanggilan alat", type="compact",
                         icon=":material/account_tree:"):
            for n, stp in enumerate(it["steps"]):
                pl = stp["payload"]
                label, icon = TOOL_LABEL.get(stp["tool"], (stp["tool"], ":material/build:"))
                args = ", ".join(f"{k}={v}" for k, v in stp["args"].items())
                gagal = pl.get("status") in ("ambigu", "error", "TIDAK_BISA")
                with st.expander(f"{label} ({args})", type="step", icon=icon, expanded=True):
                    st.caption("Alasan memilih alat ini (menurut LLM): "
                               + (stp.get("alasan") or "tidak disebutkan"))
                    if gagal:
                        st.info(pl.get("pesan") or pl.get("alasan"), icon=":material/info:")
                        if pl.get("kandidat"):
                            st.write(pl["kandidat"])
                    if pl.get("sql"):
                        show_sql_explanation(pl["sql"])
    st.caption(usage_line(it, f" · {len(it['steps'])} pemanggilan alat"))


def show_sql_mode(it: dict, idx: int):
    if "rejected" in it:
        st.warning(f"Tidak dijalankan: {it['rejected']}", icon=":material/gpp_bad:")
    if "summary" in it:
        st.markdown(it["summary"])
    if "db_error" in it:
        st.error(f"Database menolak query: {it['db_error']}", icon=":material/error:")
    if "df" in it:
        with st.container(border=True):
            show_result(it["df"], it.get("chart"), key=f"res_{idx}")
    with st.expander("Bagaimana jawaban ini dihitung?", type="compact", icon=":material/account_tree:"):
        if it.get("final_sql"):
            show_sql_explanation(it["final_sql"])
        else:
            st.code(it.get("sql", ""), language="sql")
    st.caption(usage_line(it))


def show_item(it: dict, idx: int):
    with st.chat_message("user"):
        st.markdown(it["q"])
    with st.chat_message("assistant"):
        if "error" in it:
            st.error(it["error"], icon=":material/error:")
        elif it.get("mode") == "agent":
            show_agent(it, idx)
        else:
            show_sql_mode(it, idx)


# ---------------------------------------------------------------------------
# Halaman
# ---------------------------------------------------------------------------
def _pakai_saran():
    st.session_state.pending = st.session_state.saran
    st.session_state.saran = None


if not st.session_state.riwayat:
    with st.container(border=True):
        st.markdown("**Contoh pertanyaan**")
        st.pills("Contoh pertanyaan", contoh, key="saran", on_change=_pakai_saran,
                 label_visibility="collapsed")

for i, it in enumerate(st.session_state.riwayat):
    show_item(it, i)

pertanyaan = st.chat_input("Tulis pertanyaan tentang data...", submit_mode="disable") \
    or st.session_state.pop("pending", None)

if pertanyaan:
    with st.chat_message("user"):
        st.markdown(pertanyaan)
    with st.chat_message("assistant"):
        apply_llm_settings()
        pesan = "Agent sedang bekerja..." if S["agent"] else "DeepSeek sedang menulis SQL..."
        with st.spinner(pesan):
            item = run_agent(pertanyaan) if S["agent"] else run_sql(pertanyaan)
    st.session_state.riwayat.append(item)
    st.rerun()
