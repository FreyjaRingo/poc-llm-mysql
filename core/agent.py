"""
Agent dengan tool calling: DeepSeek memilih alat, Python menjalankannya.

Alat yang tersedia:
  query_database        pertanyaan data biasa, lewat jalur text-to-SQL yang sudah dievaluasi
  get_recommendations   rekomendasi produk dari core/recommend.py
  get_customer_profile  segmen, lini utama, status kredit pelanggan

Prinsip: LLM hanya memilih alat dan menjelaskan hasilnya. Angka dan daftar produk
selalu berasal dari Python. Nama pelanggan dicocokkan oleh Python, bukan oleh LLM.
"""
import difflib
import json
import time

import pandas as pd

from core import config, features, pipeline, recommend

MAX_STEPS = 5

# Setiap alat menerima argumen tambahan ini supaya pemilihan alat bisa diaudit.
# Isinya laporan diri LLM, bukan hasil perhitungan, dan ditampilkan dengan label itu.
REASON_PARAM = {"alasan_pemilihan": {
    "type": "string",
    "description": "Satu kalimat: kenapa alat ini dipilih untuk pertanyaan pengguna."}}

TOOLS = [
    {"type": "function", "function": {
        "name": "query_database",
        "description": ("Menjawab pertanyaan data dari database penjualan (penjualan, order, "
                        "pembayaran, piutang, produk, karyawan, kantor). Gunakan untuk semua "
                        "pertanyaan berbasis angka atau daftar data. Tidak bisa membuat rekomendasi."),
        "parameters": {"type": "object", "properties": {**REASON_PARAM,
            "pertanyaan": {"type": "string",
                           "description": "Pertanyaan data dalam bahasa biasa, satu topik."}},
            "required": ["pertanyaan"]}}},
    {"type": "function", "function": {
        "name": "get_recommendations",
        "description": ("Rekomendasi 10 produk yang belum pernah dibeli seorang pelanggan. "
                        "Metode: populer, segmen, similarity, rule (aturan bisnis), llm, atau "
                        "semua (5 teratas dari empat metode non-LLM). Hasil sudah termasuk "
                        "peringatan aturan bisnis jika penawaran sebaiknya ditahan."),
        "parameters": {"type": "object", "properties": {**REASON_PARAM,
            "pelanggan": {"type": "string", "description": "Nama atau nomor pelanggan."},
            "metode": {"type": "string",
                       "enum": ["populer", "segmen", "similarity", "rule", "llm", "semua"],
                       "description": "Default 'semua' jika pengguna tidak menyebut metode."}},
            "required": ["pelanggan"]}}},
    {"type": "function", "function": {
        "name": "get_customer_profile",
        "description": ("Profil seorang pelanggan: segmen, porsi belanja per lini produk, "
                        "jumlah order, total belanja, piutang, batas kredit, dan apakah "
                        "penawaran sebaiknya ditahan."),
        "parameters": {"type": "object", "properties": {**REASON_PARAM,
            "pelanggan": {"type": "string", "description": "Nama atau nomor pelanggan."}},
            "required": ["pelanggan"]}}},
]

SYSTEM = """Anda asisten analis data penjualan. Jawab dalam Bahasa Indonesia, singkat dan jelas.

Aturan:
- Gunakan alat untuk setiap fakta. Jangan menyebut angka, produk, atau nama yang tidak ada di hasil alat.
- Untuk rekomendasi produk, selalu panggil get_recommendations. Jangan membuat rekomendasi sendiri.
- Jika hasil alat berisi peringatan_aturan_bisnis, sampaikan peringatan itu di awal jawaban.
- Jika alat mengembalikan beberapa kandidat pelanggan, minta pengguna memilih. Jangan menebak.
- Jika alat mengembalikan error atau TIDAK_BISA, sampaikan apa adanya.
- Jelaskan metode yang dipakai dalam satu kalimat, tanpa istilah teknis berlebihan.
- Selalu isi alasan_pemilihan saat memanggil alat.
- Nilai uang dalam USD."""


# ---------------------------------------------------------------------------
# Data rekomendasi dimuat sekali per proses
# ---------------------------------------------------------------------------
_cache = {}


def _model():
    if "model" not in _cache:
        data = features.load_data()
        _cache["data"], _cache["model"] = data, features.build_model(data)
    return _cache["data"], _cache["model"]


def reset_cache():
    _cache.clear()


def resolve_customer(text: str) -> dict:
    """Cocokkan nama atau nomor ke customerNumber. Hasil: {'id'} atau {'kandidat'} atau {'error'}."""
    data, _ = _model()
    cust = data["customers"]
    t = str(text).strip()
    if t.isdigit() and int(t) in cust.index:
        return {"id": int(t)}
    names = cust["customerName"]
    low = t.casefold()
    exact = names[names.str.casefold() == low]
    if len(exact) == 1:
        return {"id": int(exact.index[0])}
    contains = names[names.str.casefold().str.contains(low, regex=False)]
    if len(contains) == 1:
        return {"id": int(contains.index[0])}
    if len(contains) > 1:
        return {"kandidat": [f"{n} ({i})" for i, n in contains.head(8).items()]}
    close = difflib.get_close_matches(t, names.tolist(), n=5, cutoff=0.6)
    if len(close) == 1:
        return {"id": int(names[names == close[0]].index[0])}
    if close:
        return {"kandidat": [f"{n} ({names[names == n].index[0]})" for n in close]}
    return {"error": f"Pelanggan '{t}' tidak ditemukan."}


# ---------------------------------------------------------------------------
# Implementasi alat. Setiap alat mengembalikan (payload_untuk_LLM, tabel_untuk_ditampilkan)
# ---------------------------------------------------------------------------
def tool_query_database(pertanyaan: str):
    conn = pipeline.get_connection()
    try:
        gen = pipeline.generate_sql(conn, pertanyaan)
        if gen["rejected"]:
            return {"status": "TIDAK_BISA", "alasan": gen["rejected"]}, None, gen
        res = pipeline.execute_sql(conn, gen["final_sql"])
    except Exception as e:
        return {"status": "error", "pesan": str(e)}, None, None
    finally:
        conn.close()
    df = pd.DataFrame([tuple(pipeline.to_jsonable(v) for v in r) for r in res["rows"]],
                      columns=res["columns"])
    payload = {"sql": gen["final_sql"], "jumlah_baris": len(df),
               "hasil": df.head(config.ROWS_SENT_TO_LLM).to_dict("records")}
    return payload, df, gen


def _customer_or_error(pelanggan: str):
    r = resolve_customer(pelanggan)
    if "id" in r:
        return r["id"], None
    if "kandidat" in r:
        return None, {"status": "ambigu", "pesan": "Ada beberapa pelanggan yang cocok.",
                      "kandidat": r["kandidat"]}
    return None, {"status": "error", "pesan": r["error"]}


def tool_get_customer_profile(pelanggan: str):
    cid, err = _customer_or_error(pelanggan)
    if err:
        return err, None, None
    data, model = _model()
    c = data["customers"].loc[cid]
    stat = features.credit_status(data, cid)
    out = {"pelanggan": f"{c.customerName} ({cid})", "negara": c.country,
           "produk_sudah_dibeli": len(model.owned.get(cid, set())),
           "total_belanja": round(stat["penjualan"], 2), "piutang": round(stat["piutang"], 2),
           "batas_kredit": stat["limit"]}
    if cid in model.seg_labels.index:
        out["segmen"] = model.seg_profile.loc[model.seg_labels[cid], "nama"]
        sp = model.line_spend.loc[cid]
        sp = sp[sp > 0].sort_values(ascending=False)
        out["porsi_belanja_per_lini"] = {k: f"{v / sp.sum():.0%}" for k, v in sp.items()}
        cl = model.lines[model.lines.customerNumber == cid]
        out["jumlah_order"] = int(cl.orderNumber.nunique())
        out["order_terakhir"] = str(cl.orderDate.max().date())
    else:
        out["segmen"] = "belum ada riwayat pembelian"
    if stat["tahan"]:
        out["peringatan_aturan_bisnis"] = "Penawaran baru sebaiknya ditahan: " + "; ".join(stat["alasan"])
    df = pd.DataFrame([{"atribut": k, "nilai": json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v}
                       for k, v in out.items()])
    return out, df, None


def tool_get_recommendations(pelanggan: str, metode: str = "semua"):
    cid, err = _customer_or_error(pelanggan)
    if err:
        return err, None, None
    data, model = _model()
    metode = metode if metode in list(recommend.NON_LLM) + ["llm", "semua"] else "semua"
    c = data["customers"].loc[cid]
    stat = features.credit_status(data, cid)
    out = {"pelanggan": f"{c.customerName} ({cid})", "metode": metode}
    if stat["tahan"]:
        out["peringatan_aturan_bisnis"] = "Penawaran baru sebaiknya ditahan: " + "; ".join(stat["alasan"])
    extra = None
    if metode == "semua":
        frames = []
        for m in recommend.NON_LLM:
            d = recommend.with_details(model, recommend.recommend(model, cid, m)).head(5)
            frames.append(d.assign(metode=recommend.METHODS[m]))
        df = pd.concat(frames, ignore_index=True)
    elif metode == "llm":
        r = recommend.rec_llm(model, cid)
        df = recommend.with_details(model, r["df"]).assign(metode="LLM")
        out["kode_tidak_valid_dibuang"] = r["invalid"]
        extra = {"usage": r["usage"]}
    else:
        df = recommend.with_details(model, recommend.recommend(model, cid, metode)) \
                      .assign(metode=recommend.METHODS[metode])
    out["rekomendasi"] = df[["metode", "peringkat", "produk", "lini", "alasan"]].to_dict("records")
    out["catatan_evaluasi"] = ("Di dataset ini tidak ada metode yang terbukti lebih baik dari "
                               "rekomendasi acak (lihat evaluasi di tab Rekomendasi).")
    return out, df[["metode", "peringkat", "produk", "lini", "skala", "alasan"]], extra


TOOL_FUNCS = {"query_database": tool_query_database,
              "get_recommendations": tool_get_recommendations,
              "get_customer_profile": tool_get_customer_profile}


# ---------------------------------------------------------------------------
# Loop agent
# ---------------------------------------------------------------------------
def _usage_add(total: dict, u) -> None:
    if not u:
        return
    for k_src, k_dst in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"),
                         ("prompt_cache_hit_tokens", "cache_hit_tokens")):
        v = getattr(u, k_src, None) if not isinstance(u, dict) else u.get(k_dst)
        total[k_dst] = total.get(k_dst, 0) + (v or 0)


def run(question: str, history: list | None = None) -> dict:
    """
    Jalankan satu pertanyaan. history: daftar pesan sebelumnya
    [{'role': 'user'|'assistant', 'content': str}] untuk percakapan lanjutan.
    """
    client = pipeline._get_client()
    messages = [{"role": "system", "content": SYSTEM}] + (history or []) + \
               [{"role": "user", "content": question}]
    steps, usage, start = [], {}, time.time()
    for _ in range(MAX_STEPS):
        kwargs = dict(model=config.LLM_MODEL, messages=messages, tools=TOOLS,
                      max_tokens=8192 if config.LLM_THINKING == "enabled" else 2048,
                      extra_body={"thinking": {"type": config.LLM_THINKING}})
        if config.LLM_TEMPERATURE is not None and config.LLM_THINKING != "enabled":
            kwargs["temperature"] = config.LLM_TEMPERATURE
        resp = client.chat.completions.create(**kwargs)
        _usage_add(usage, resp.usage)
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        assistant = {"role": "assistant", "content": msg.content or ""}
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            # Wajib dikirim balik saat memakai tools dalam mode thinking (aturan DeepSeek)
            assistant["reasoning_content"] = reasoning
        if not calls:
            return {"answer": msg.content or "", "steps": steps, "usage": usage,
                    "latency_s": round(time.time() - start, 2), "messages": messages}
        assistant["tool_calls"] = [{"id": c.id, "type": "function",
                                    "function": {"name": c.function.name,
                                                 "arguments": c.function.arguments}} for c in calls]
        messages.append(assistant)
        for c in calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            alasan = args.pop("alasan_pemilihan", None)
            func = TOOL_FUNCS.get(name)
            if func is None:
                payload, df, extra = {"status": "error", "pesan": f"Alat '{name}' tidak ada."}, None, None
            else:
                try:
                    payload, df, extra = func(**args)
                except TypeError as e:
                    payload, df, extra = {"status": "error", "pesan": f"Argumen salah: {e}"}, None, None
            if isinstance(extra, dict) and "usage" in extra:
                _usage_add(usage, extra["usage"])
            steps.append({"tool": name, "args": args, "alasan": alasan, "payload": payload, "df": df,
                          "sql_gen": extra if name == "query_database" else None})
            messages.append({"role": "tool", "tool_call_id": c.id,
                             "content": json.dumps(payload, ensure_ascii=False, default=str)})
    return {"answer": "Agent berhenti karena mencapai batas langkah. Coba pecah pertanyaan Anda.",
            "steps": steps, "usage": usage, "latency_s": round(time.time() - start, 2),
            "messages": messages}
