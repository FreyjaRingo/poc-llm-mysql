"""
Evaluasi akurasi text-to-SQL dengan DeepSeek. Soal uji ada di evaluation/eval_questions.json.

Metode: execution accuracy. SQL dari LLM dan SQL acuan sama-sama dijalankan, lalu
HASIL-nya dibandingkan. Teks SQL tidak dibandingkan karena satu pertanyaan bisa
dijawab dengan banyak bentuk SQL yang benar.

  strict  : himpunan baris sama (urutan baris diabaikan, angka dibulatkan 2 desimal)
  lenient : jumlah baris sama dan setiap kolom acuan ada di hasil LLM
            (kolom tambahan dan urutan kolom diabaikan)
  angka_cocok_cek_manual : nilai angka sama tapi label beda. Tidak dihitung benar, cek manual.
  Soal tanpa SQL acuan dinilai benar jika LLM menolak dengan TIDAK_BISA. Untuk kategori
  akses, benar juga jika database menolak query karena hak akses kolom.

Contoh:
    python evaluate.py --check-gold        # cek SQL acuan, tanpa LLM
    python evaluate.py --self-test         # uji evaluator, harus 22/22
    python evaluate.py                     # evaluasi dengan DeepSeek
    python evaluate.py --rules on          # paksa definisi bisnis ikut dikirim
    python evaluate.py --ids 18,19,20      # soal tertentu saja
    python evaluate.py --thinking on       # paksa mode thinking DeepSeek
"""
import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal

import mysql.connector

from core import config, pipeline


def norm(v):
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return round(float(v), 2)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v).strip()


def norm_rows(rows):
    return [tuple(norm(v) for v in r) for r in rows]


def match_strict(gold, pred):
    return Counter(gold) == Counter(pred)


def match_lenient(gold, pred):
    if len(gold) != len(pred):
        return False
    if not gold:
        return True
    key = lambda x: (x is None, str(x))
    gold_cols = [sorted(col, key=key) for col in zip(*gold)]
    pred_cols = [sorted(col, key=key) for col in zip(*pred)]
    used = set()
    for gc in gold_cols:
        hit = next((i for i, pc in enumerate(pred_cols) if i not in used and pc == gc), None)
        if hit is None:
            return False
        used.add(hit)
    return True


def measure_matches(gold, pred):
    """Kolom angka terakhir acuan cocok dengan salah satu kolom hasil LLM, dengan jumlah
    baris sama. Biasanya berarti angkanya benar tapi label berbeda (misal '2004-01' vs 1).
    Tidak dihitung benar otomatis, harus dicek manual."""
    if not gold or len(gold) != len(pred) or not isinstance(gold[0][-1], float):
        return False
    target = sorted(r[-1] for r in gold if r[-1] is not None)
    for col in zip(*pred):
        if all(isinstance(v, float) or v is None for v in col):
            if sorted(v for v in col if v is not None) == target:
                return True
    return False


def run_gold(conn, sql):
    return norm_rows(pipeline.execute_sql(conn, pipeline.validate_sql(sql))["rows"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-gold", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--rules", choices=["on", "off"])
    ap.add_argument("--thinking", choices=["on", "off"])
    ap.add_argument("--ids", default="")
    args = ap.parse_args()
    if args.rules:
        config.INCLUDE_BUSINESS_RULES = args.rules == "on"
    if args.thinking:
        config.LLM_THINKING = "enabled" if args.thinking == "on" else "disabled"

    questions = json.loads((config.BASE_DIR / "evaluation" / "eval_questions.json").read_text(encoding="utf-8"))
    if args.ids:
        wanted = {int(x) for x in args.ids.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    conn = pipeline.get_connection()

    if args.check_gold:
        ok = True
        for q in questions:
            if not q["gold_sql"]:
                print(f"[{q['id']:>2}] (tidak ada SQL acuan, jawaban benar = menolak)")
                continue
            try:
                rows = run_gold(conn, q["gold_sql"])
                print(f"[{q['id']:>2}] OK  {len(rows)} baris  contoh: {rows[:3]}")
            except Exception as e:
                ok = False
                print(f"[{q['id']:>2}] ERROR {e}")
        print("Semua SQL acuan valid." if ok else "Ada SQL acuan yang perlu diperbaiki.")
        return

    # Prompt sistem dibuat sekali. Prompt yang sama di setiap soal membuat
    # DeepSeek bisa memakai cache, sehingga token input jauh lebih murah.
    system = None if args.self_test else pipeline.build_sql_prompt(conn)

    results = []
    for q in questions:
        rec = {"id": q["id"], "kategori": q["kategori"], "pertanyaan": q["pertanyaan"],
               "status": "", "strict": False, "lenient": False, "pred_sql": "",
               "gold_sql": q["gold_sql"] or "", "input_tokens": 0, "cache_hit_tokens": 0,
               "output_tokens": 0, "llm_latency_s": 0, "error": ""}
        try:
            if args.self_test:
                gen = {"final_sql": pipeline.validate_sql(q["gold_sql"]) if q["gold_sql"] else None,
                       "rejected": None if q["gold_sql"] else "-- TIDAK_BISA: self-test",
                       "usage": {}, "llm_latency_s": 0}
            else:
                gen = pipeline.generate_sql(conn, q["pertanyaan"], system)
                pipeline.write_log({"ts": datetime.now().isoformat(), "source": "evaluate",
                                    "id": q["id"], "question": q["pertanyaan"],
                                    **{k: v for k, v in gen.items() if k != "system_prompt"}})
            for k in ("input_tokens", "cache_hit_tokens", "output_tokens"):
                rec[k] = gen["usage"].get(k) or 0
            rec["llm_latency_s"] = gen["llm_latency_s"]

            if q["gold_sql"] is None:
                # Benar jika LLM menolak. Untuk kategori akses, benar juga jika
                # database menolak query karena hak akses kolom.
                refused = bool(gen["rejected"]) and "TIDAK_BISA" in gen["rejected"]
                denied = False
                if not refused and gen.get("final_sql") and q["kategori"] == "akses":
                    try:
                        pipeline.execute_sql(conn, gen["final_sql"])
                    except mysql.connector.Error as e:
                        denied = "denied" in str(e).lower()
                ok = refused or denied
                rec["strict"] = rec["lenient"] = ok
                rec["status"] = ("benar_menolak" if refused else
                                 "benar_db_menolak" if denied else "salah_tidak_menolak")
                rec["pred_sql"] = gen.get("final_sql") or gen["rejected"] or ""
            elif gen["rejected"]:
                rec["status"], rec["error"] = "ditolak", gen["rejected"]
            else:
                rec["pred_sql"] = gen["final_sql"]
                gold = run_gold(conn, q["gold_sql"])
                try:
                    pred = norm_rows(pipeline.execute_sql(conn, gen["final_sql"])["rows"])
                    rec["strict"] = match_strict(gold, pred)
                    rec["lenient"] = rec["strict"] or match_lenient(gold, pred)
                    rec["status"] = ("benar" if rec["strict"] else
                                     "benar_lenient" if rec["lenient"] else
                                     "angka_cocok_cek_manual" if measure_matches(gold, pred) else
                                     "salah")
                except mysql.connector.Error as e:
                    rec["status"], rec["error"] = "error_sql", str(e)
        except SystemExit:
            raise
        except Exception as e:  # error API, jaringan, dsb.
            rec["status"], rec["error"] = "error_lain", str(e)

        results.append(rec)
        print(f"[{q['id']:>2}] {rec['kategori']:<10} {rec['status']:<20} {q['pertanyaan']}")

    conn.close()

    n = len(results)
    mode = "SELF-TEST" if args.self_test else (
        f"{config.DB_NAME} | {config.LLM_MODEL} | thinking={config.LLM_THINKING} | "
        f"definisi bisnis={'on' if config.INCLUDE_BUSINESS_RULES else 'off'} | "
        f"komentar kolom={'on' if config.INCLUDE_COLUMN_COMMENTS else 'off'}")
    print("\n" + "=" * 70)
    print(mode)
    print(f"Strict  : {sum(r['strict'] for r in results)}/{n}")
    print(f"Lenient : {sum(r['lenient'] for r in results)}/{n}")
    manual = [r["id"] for r in results if r["status"] == "angka_cocok_cek_manual"]
    if manual:
        print(f"Angka cocok, label beda (cek manual): soal {manual}")
    per = defaultdict(lambda: [0, 0])
    for r in results:
        per[r["kategori"]][0] += r["lenient"]
        per[r["kategori"]][1] += 1
    for k, (b, t) in per.items():
        print(f"  {k:<10} {b}/{t} (lenient)")
    tin = sum(r["input_tokens"] for r in results)
    hit = sum(r["cache_hit_tokens"] for r in results)
    tout = sum(r["output_tokens"] for r in results)
    lat = [r["llm_latency_s"] for r in results if r["llm_latency_s"]]
    print(f"Token input {tin:,} (cache hit {hit:,}) | output {tout:,}")
    if lat:
        print(f"Latensi LLM rata-rata {sum(lat) / len(lat):.1f} detik")

    config.REPORT_DIR.mkdir(exist_ok=True)
    tag = "selftest" if args.self_test else (
        ("rules_on" if config.INCLUDE_BUSINESS_RULES else "rules_off")
        + ("_thinking" if config.LLM_THINKING == "enabled" else ""))
    path = config.REPORT_DIR / f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{tag}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"Detail per soal: {path}")


if __name__ == "__main__":
    main()
