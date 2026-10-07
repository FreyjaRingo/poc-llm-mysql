"""
Memilih dan menggambar grafik untuk hasil query di tab Tanya AI.

Dua sumber keputusan:
  1. Spesifikasi dari LLM (opsional). Hanya dipakai jika jenis grafiknya diizinkan dan
     kolomnya benar-benar ada di hasil query. LLM tidak pernah menulis kode grafik.
  2. Aturan otomatis berdasarkan bentuk tabel. Dipakai jika (1) tidak ada atau tidak valid.
"""
import re

import altair as alt
import pandas as pd

SERIES = "#2a78d6"
ALLOWED = {"bar", "line", "scatter", "pie"}
# Palet kategorikal untuk irisan pie, urutan tetap (sudah divalidasi aman untuk buta warna)
PIE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#9b9a95"
OTHER_LABEL = "Lainnya"
# Lebih dari 8 kategori: 7 terbesar ditampilkan, sisanya digabung jadi "Lainnya"
PIE_MAX_SLICES = len(PIE_COLORS)
LABEL_MIN_PCT = 3.0  # irisan di bawah 3% tidak diberi label agar tidak bertumpuk
# Kata di pertanyaan yang menandakan pengguna ingin melihat porsi dari keseluruhan
SHARE_HINT = re.compile(r"(pie|porsi|proporsi|komposisi|persentase|pangsa|kontribusi|share|distribusi)", re.I)
TIME_HINT = re.compile(r"(bulan|month|tahun|year|tanggal|date|periode|quarter|kuartal|minggu|week)", re.I)
TIME_VALUE = re.compile(r"^\d{4}(-\d{2}){0,2}$")


def _numeric(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _is_time(df: pd.DataFrame, col: str) -> bool:
    if TIME_HINT.search(str(col)):
        return True
    sample = df[col].dropna().astype(str).head(20)
    return len(sample) > 0 and sample.str.match(TIME_VALUE).all()


def pie_problem(df: pd.DataFrame, x: str, y: str) -> str | None:
    """Alasan pie tidak layak, atau None jika layak."""
    if len(df) < 2:
        return "pie butuh minimal 2 kategori"
    vals = df[y].dropna()
    if (vals < 0).any():
        return "ada nilai negatif, pie tidak bisa menampilkannya"
    if vals.sum() <= 0:
        return "total nilai nol"
    if df[x].duplicated().any():
        return "kategori duplikat"
    return None


TIME_ORDER = [("tahun|year", 0), ("quarter|kuartal", 1), ("bulan|month", 2),
              ("minggu|week", 3), ("tanggal|date|periode", 4)]
MAX_SERIES = len(PIE_COLORS)


def _time_rank(col: str) -> int:
    for pat, rank in TIME_ORDER:
        if re.search(pat, str(col), re.I):
            return rank
    return 5


def _line_spec(df: pd.DataFrame, x: str, y: str, others: list[str]) -> dict:
    """Spec grafik garis yang menjamin satu titik per nilai x (per seri).

    Masalah yang dicegah: hasil query berisi tahun DAN bulan, lalu hanya 'tahun' dipakai
    sebagai sumbu x. Semua bulan menumpuk di satu tahun dan tergambar sebagai garis vertikal.
    """
    # Kolom waktu tambahan hanya dikenali dari namanya. Nilai 4 digit seperti jumlah 1500
    # tidak boleh ikut dianggap tahun.
    times = sorted({x} | {c for c in df.columns if c != y and TIME_HINT.search(str(c))}, key=_time_rank)
    # 1. Beberapa kolom waktu (tahun + bulan): gabung jadi satu sumbu "tahun-bulan"
    if len(times) > 1 and not df.duplicated(times).any():
        name = "periode" if "periode" not in df.columns else "periode_gabungan"
        return {"type": "line", "x": name, "x_parts": times, "y": y,
                "reason": f"kolom waktu {', '.join(times)} digabung jadi satu sumbu"}
    if not df[x].duplicated().any():
        return {"type": "line" if len(df) > 2 else "bar", "x": x, "y": y,
                "reason": f"'{x}' terlihat seperti waktu"}
    # 2. Nilai x berulang karena ada kolom kategori: satu garis per kategori
    cats = [c for c in others if c != x and not _is_time(df, c)
            and 1 < df[c].nunique() <= MAX_SERIES and not df.duplicated([x, c]).any()]
    if cats:
        return {"type": "line", "x": x, "y": y, "color": cats[-1],
                "reason": f"satu garis per {cats[-1]}"}
    # 3. Tidak bisa dipastikan satu titik per x: lebih jujur tanpa grafik
    return {"type": "none", "reason": f"'{x}' muncul lebih dari sekali dan tidak ada kolom pembeda"}


def rule_based(df: pd.DataFrame, question: str = "") -> dict:
    """Pilih grafik dari bentuk tabel. Mengembalikan spec dengan type 'metric', 'none', atau grafik."""
    if df.empty:
        return {"type": "none", "reason": "hasil kosong"}
    num = _numeric(df)
    if len(df) == 1 and num:
        return {"type": "metric", "cols": num[:4], "reason": "satu baris angka"}
    if not num:
        return {"type": "none", "reason": "tidak ada kolom angka"}
    others = [c for c in df.columns if c not in num]
    # Kolom waktu yang berupa angka (misal MONTH() atau YEAR()) dipakai sebagai sumbu x
    time_num = [c for c in num if _is_time(df, c)]
    if others or time_num:
        x = next((c for c in others + time_num if _is_time(df, c)), None)
        if x is not None:
            # Nilai = kolom angka terakhir yang bukan waktu (hindari memplot YEAR atau MONTH)
            ys = [c for c in num if c != x and not _is_time(df, c)] or [c for c in num if c != x]
            if not ys:
                return {"type": "none", "reason": "tidak ada kolom nilai"}
            return _line_spec(df, x, ys[-1], others)
        if len(df) <= 30:
            # Pakai kolom teks terakhir sebelum angka, biasanya nama (bukan ID)
            x, y = others[-1], num[-1]
            if SHARE_HINT.search(question or ""):
                masalah = pie_problem(df, x, y)
                if masalah is None:
                    alasan = "pertanyaan menanyakan porsi"
                    if len(df) > PIE_MAX_SLICES:
                        alasan += f", {len(df) - PIE_MAX_SLICES + 1} kategori terkecil digabung jadi {OTHER_LABEL}"
                    return {"type": "pie", "x": x, "y": y, "reason": alasan}
                return {"type": "bar", "x": x, "y": y, "reason": f"pie tidak dipakai: {masalah}"}
            if df[x].duplicated().any():
                return {"type": "none", "reason": f"'{x}' muncul lebih dari sekali"}
            return {"type": "bar", "x": x, "y": y, "reason": "kategori dengan nilai angka"}
        return {"type": "none", "reason": "terlalu banyak kategori untuk grafik"}
    if len(num) >= 2 and len(df) > 2:
        return {"type": "scatter", "x": num[0], "y": num[1], "reason": "dua kolom angka"}
    return {"type": "none", "reason": "bentuk tabel tidak cocok digrafikkan"}


def choose(df: pd.DataFrame, llm_spec: dict | None, question: str = "") -> dict:
    """Pakai spec LLM jika valid, selain itu aturan otomatis. Field 'source' mencatat asalnya."""
    if llm_spec:
        t = str(llm_spec.get("type", "")).lower()
        x, y = llm_spec.get("x"), llm_spec.get("y")
        if t == "none":
            spec = rule_based(df, question)
            if spec["type"] == "metric":
                return {**spec, "source": "aturan otomatis (LLM memilih tanpa grafik)"}
            return {"type": "none", "source": "LLM", "reason": "LLM memilih tanpa grafik"}
        if (t in ALLOWED and x in df.columns and y in df.columns
                and pd.api.types.is_numeric_dtype(df[y]) and x != y):
            if t == "pie":
                masalah = pie_problem(df, x, y)
                if masalah:
                    # Data tidak cocok untuk pie: tampilkan sebagai batang, dengan alasannya
                    return {"type": "bar", "x": x, "y": y, "title": llm_spec.get("title"),
                            "source": "LLM, pie diganti batang", "reason": masalah}
            if t in ("line", "bar") and df[x].duplicated().any():
                # Nilai x berulang (misal tahun saat ada kolom bulan): pilihan LLM akan
                # menumpuk titik, jadi bentuk sumbu diperbaiki oleh aturan otomatis
                others = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
                spec = _line_spec(df, x, y, others)
                return {**spec, "title": llm_spec.get("title"),
                        "source": "LLM, sumbu diperbaiki aturan otomatis"}
            return {"type": t, "x": x, "y": y, "title": llm_spec.get("title"), "source": "LLM"}
        fallback = rule_based(df, question)
        return {**fallback, "source": "aturan otomatis (spec LLM tidak valid)"}
    return {**rule_based(df, question), "source": "aturan otomatis"}


def render(st, df: pd.DataFrame, spec: dict):
    """Gambar grafik di Streamlit sesuai spec. Tidak menggambar apa pun untuk type 'none'."""
    t = spec["type"]
    if t == "metric":
        cols = st.columns(len(spec["cols"]))
        for c, name in zip(cols, spec["cols"]):
            v = df[name].iloc[0]
            c.metric(str(name), f"{v:,.2f}" if isinstance(v, float) else f"{v:,}", border=True)
        return
    if t not in ALLOWED:
        return
    x, y = spec["x"], spec["y"]
    color = spec.get("color")
    if spec.get("x_parts"):
        parts = spec["x_parts"]
        data = df[parts + [y]].copy()
        if all(pd.api.types.is_numeric_dtype(data[c]) for c in parts):
            data = data.sort_values(parts)
        data[x] = data[parts[0]].astype(str)
        for c in parts[1:]:
            v = data[c]
            # Bulan/kuartal angka diberi nol di depan supaya 2004-02 tidak tertukar dengan 2004-10
            data[x] += "-" + (v.map(lambda n: f"{int(n):02d}") if pd.api.types.is_numeric_dtype(v)
                              else v.astype(str))
        data = data[[x, y]]
    else:
        data = df[[x, y] + ([color] if color else [])].copy()
    data[x] = data[x].astype(str) if t != "scatter" else data[x]
    tip = [alt.Tooltip(x), alt.Tooltip(y, format=",.2f")] + ([alt.Tooltip(color)] if color else [])
    base = alt.Chart(data)
    if t == "line" and color:
        data[color] = data[color].astype(str)
        doms = list(dict.fromkeys(data[color]))
        chart = base.mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=50)).encode(
            alt.X(f"{x}:O", title=x, sort=None), alt.Y(f"{y}:Q", title=y),
            alt.Color(f"{color}:N", title=color,
                      scale=alt.Scale(domain=doms, range=PIE_COLORS[:len(doms)])),
            tooltip=tip)
    elif t == "line":
        chart = base.mark_line(color=SERIES, strokeWidth=2, point=alt.OverlayMarkDef(size=60, color=SERIES)) \
            .encode(alt.X(f"{x}:O", title=x, sort=None), alt.Y(f"{y}:Q", title=y), tooltip=tip)
    elif t == "bar":
        chart = base.mark_bar(color=SERIES, cornerRadiusEnd=4) \
            .encode(alt.Y(f"{x}:N", title=x, sort="-x"), alt.X(f"{y}:Q", title=y), tooltip=tip)
    elif t == "pie":
        # Donut: label persen dihitung dari total, legenda selalu tampil
        # Urutkan dari porsi terbesar; kolom 'urut' mengunci urutan irisan dan label
        # supaya keduanya digambar di posisi yang sama
        pie = data.sort_values(y, ascending=False).reset_index(drop=True)
        pie[x] = pie[x].astype(str)
        if len(pie) > PIE_MAX_SLICES:
            top = pie.head(PIE_MAX_SLICES - 1)
            rest = pd.DataFrame({x: [f"{OTHER_LABEL} ({len(pie) - len(top)} kategori)"],
                                 y: [pie[y].iloc[len(top):].sum()]})
            pie = pd.concat([top, rest], ignore_index=True)
            colors = PIE_COLORS[:len(top)] + [OTHER_COLOR]
        else:
            colors = PIE_COLORS[:len(pie)]
        pie["persen"] = pie[y] / pie[y].sum() * 100
        pie["urut"] = range(len(pie))
        pie["label"] = pie["persen"].map(lambda v: f"{v:.1f}%" if v >= LABEL_MIN_PCT else "")
        enc_color = alt.Color(f"{x}:N", title=x, sort=pie[x].tolist(),
                              scale=alt.Scale(domain=pie[x].tolist(), range=colors))
        base = alt.Chart(pie).encode(
            alt.Theta(f"{y}:Q", stack=True), enc_color, alt.Order("urut:Q"),
            tooltip=[alt.Tooltip(x), alt.Tooltip(y, format=",.2f"),
                     alt.Tooltip("persen:Q", title="porsi (%)", format=".1f")])
        ring = base.mark_arc(innerRadius=65, outerRadius=120, stroke="white", strokeWidth=2)
        label = base.mark_text(radius=140, fontSize=12).encode(
            text="label:N", color=alt.value("#52514e"))
        chart = ring + label
    else:
        chart = base.mark_circle(color=SERIES, size=80) \
            .encode(alt.X(f"{x}:Q", title=x), alt.Y(f"{y}:Q", title=y), tooltip=tip)
    if spec.get("title"):
        chart = chart.properties(title=spec["title"])
    st.altair_chart(chart.properties(height=320), width="stretch",
                    alt=spec.get("title") or f"Grafik {t}: {y} per {x}")
