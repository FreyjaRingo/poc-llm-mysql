"""
Penjelasan deterministik untuk SQL yang ditulis LLM.

SQL diurai dengan sqlglot (parser, bukan LLM), lalu disusun ulang menjadi langkah-langkah
dalam bahasa biasa. Arti setiap kolom diambil dari COMMENT di database. Karena dibuat oleh
kode, penjelasan ini selalu sesuai dengan SQL yang benar-benar dijalankan.
"""
import re

import sqlglot
from sqlglot import exp

from core import pipeline

AGG_NAMES = {"Sum": "jumlah (SUM)", "Count": "banyaknya (COUNT)", "Avg": "rata-rata (AVG)",
             "Max": "nilai terbesar (MAX)", "Min": "nilai terkecil (MIN)"}
_comments = {}


def column_comments() -> dict:
    """{nama_kolom: komentar} dari information_schema, dibaca sekali."""
    if not _comments:
        conn = pipeline.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT TABLE_NAME, COLUMN_NAME, COLUMN_COMMENT FROM information_schema.COLUMNS
                           WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_COMMENT <> ''""")
            for t, c, k in cur.fetchall():
                _comments[c] = f"{k} (tabel {t})"
            cur.execute("""SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES
                           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_COMMENT <> ''""")
            for t, k in cur.fetchall():
                _comments[f"__table__{t}"] = k
            cur.close()
        finally:
            conn.close()
    return _comments


def _sql(node) -> str:
    return node.sql(dialect="mysql") if node is not None else ""


def _source(node) -> str:
    """Nama sumber data: tabel atau hasil subquery."""
    if isinstance(node, exp.Subquery):
        return f"hasil subquery {node.alias or ''}".strip()
    if isinstance(node, exp.Table):
        return f"tabel {node.name}" + (f" (alias {node.alias})" if node.alias else "")
    return _sql(node)


def _explain_select(sel: exp.Select) -> dict:
    out = {"sumber": [], "join": [], "filter": [], "kelompok": [], "hitungan": [],
           "kolom": [], "having": [], "urutan": [], "batas": None}
    frm = sel.args.get("from") or sel.args.get("from_")
    if frm is not None:
        out["sumber"].append(_source(frm.this))
    for j in sel.args.get("joins") or []:
        on, using = j.args.get("on"), j.args.get("using")
        if on is not None:
            cond = f", dengan syarat `{_sql(on)}`"
        elif using:
            cond = ", dengan kolom yang sama: " + ", ".join(f"`{_sql(u)}`" for u in using)
        else:
            cond = ""
        out["join"].append(f"{_source(j.this)}{cond}")
    where = sel.args.get("where")
    if where is not None:
        cond = where.this
        parts = list(cond.flatten()) if isinstance(cond, exp.And) else [cond]
        for p_ in parts:
            # Subquery di dalam filter diringkas, isinya dijelaskan di bagian tersendiri
            txt = _sql(p_)
            for sq in p_.find_all(exp.Subquery):
                txt = txt.replace(_sql(sq), "(hasil subquery)")
            out["filter"].append(txt)
    group = sel.args.get("group")
    if group is not None:
        out["kelompok"] = [_sql(g) for g in group.expressions]
    for e in sel.expressions:
        body = e.unalias()
        alias = e.alias or ""
        aggs = [a for a in body.find_all(exp.AggFunc)]
        if aggs:
            fn = type(aggs[0]).__name__
            inner = _sql(aggs[0].this) if aggs[0].this is not None else "*"
            label = AGG_NAMES.get(fn, fn.upper())
            name = alias or "kolom hasil"
            extra = "" if body is aggs[0] else f" (rumus lengkap: {_sql(body)})"
            out["hitungan"].append(f"{name} = {label} dari {inner}{extra}")
        else:
            out["kolom"].append(f"{alias} = {_sql(body)}" if alias and alias != _sql(body) else _sql(body))
    having = sel.args.get("having")
    if having is not None:
        out["having"] = [_sql(having.this)]
    order = sel.args.get("order")
    if order is not None:
        out["urutan"] = [f"{_sql(o.this)} {'menurun' if o.args.get('desc') else 'menaik'}"
                         for o in order.expressions]
    limit = sel.args.get("limit")
    if limit is not None:
        out["batas"] = _sql(limit.expression)
    return out


def explain_sql(sql: str) -> dict:
    """Urai SQL menjadi bagian-bagian yang bisa dibaca. Tidak memanggil LLM."""
    out = {"asumsi": [m.strip().rstrip("*/").strip()
                      for m in re.findall(r"asumsi\s*:\s*([^\n]+?)(?:\*/|$)", sql, re.I | re.M)],
           "bagian": [], "tabel": [], "kolom_dipakai": []}
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except sqlglot.errors.ParseError as e:
        out["error"] = str(e)
        return out
    out["tabel"] = sorted({t.name for t in tree.find_all(exp.Table)})
    # Subquery dijelaskan dari yang paling dalam, lalu query utama
    subs = [sq for sq in tree.find_all(exp.Subquery) if isinstance(sq.this, exp.Select)]
    subs.sort(key=lambda sq: -sq.depth)
    for i, sq in enumerate(subs, 1):
        nama = f"Subquery {sq.alias}" if sq.alias else f"Subquery {i} (di dalam filter)"
        out["bagian"].append({"nama": nama, **_explain_select(sq.this)})
    main = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if main is not None:
        out["bagian"].append({"nama": "Query utama", **_explain_select(main)})
    com = column_comments()
    used = sorted({c.name for c in tree.find_all(exp.Column)})
    out["kolom_dipakai"] = [(c, com[c]) for c in used if c in com]
    return out


def to_markdown(info: dict) -> str:
    """Susun hasil explain_sql menjadi langkah bernomor per bagian."""
    if info.get("error"):
        return f"SQL tidak bisa diurai: {info['error']}"
    blocks = []
    multi = len(info["bagian"]) > 1
    for b in info["bagian"]:
        lines, n = [], 1

        def step(text):
            nonlocal n
            lines.append(f"{n}. {text}")
            n += 1

        if b["sumber"]:
            step("Ambil data dari " + ", ".join(b["sumber"]) + ".")
        for j in b["join"]:
            step(f"Gabungkan dengan {j}.")
        if b["filter"]:
            step("Saring baris: " + "; ".join(f"`{f}`" for f in b["filter"]) + ".")
        if b["kelompok"]:
            step("Kelompokkan per " + ", ".join(f"`{g}`" for g in b["kelompok"]) + ".")
        for h in b["hitungan"]:
            step(f"Hitung `{h}`.")
        if b["kolom"]:
            step("Tampilkan kolom " + ", ".join(f"`{k}`" for k in b["kolom"]) + ".")
        if b["having"]:
            step("Simpan hanya kelompok yang memenuhi `" + b["having"][0] + "`.")
        if b["urutan"]:
            step("Urutkan berdasarkan " + ", ".join(f"`{o}`" for o in b["urutan"]) + ".")
        if b["batas"]:
            step(f"Ambil maksimal {b['batas']} baris.")
        head = f"**{b['nama']}**\n" if multi else ""
        blocks.append(head + "\n".join(lines))
    return "\n\n".join(blocks)


def validation_checklist(final_sql: str) -> list[tuple[str, bool]]:
    """Pemeriksaan keamanan yang sudah dilewati SQL ini sebelum dijalankan."""
    return [
        ("Hanya satu statement SELECT (tidak bisa mengubah data)", True),
        ("Tidak memakai fungsi berbahaya (SLEEP, LOAD_FILE, INTO OUTFILE)", True),
        ("LIMIT dipasang untuk membatasi jumlah baris", bool(re.search(r"\bLIMIT\b", final_sql, re.I))),
        ("Dijalankan dengan user read-only llm_reader dan batas waktu", True),
    ]
