"""
Uji pemilihan alat oleh agent (tool calling).

Yang dinilai bukan angka jawabannya (itu sudah diuji evaluate.py), tetapi apakah DeepSeek
memanggil alat yang tepat, dengan argumen yang tepat, dan menyampaikan peringatan bisnis.

Contoh:
    python evaluate_agent.py
    python evaluate_agent.py --thinking on
    python evaluate_agent.py --ids 3,9,10
"""
import argparse
import csv
import json
import sys
import time

from core import agent, config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser()
ap.add_argument("--thinking", choices=["on", "off"])
ap.add_argument("--rules", choices=["on", "off"], default="on")
ap.add_argument("--ids", default="")
args = ap.parse_args()
if args.thinking:
    config.LLM_THINKING = "enabled" if args.thinking == "on" else "disabled"
config.INCLUDE_BUSINESS_RULES = args.rules == "on"

qs = json.loads((config.BASE_DIR / "evaluation" / "agent_questions.json").read_text(encoding="utf-8"))
if args.ids:
    keep = {int(x) for x in args.ids.split(",")}
    qs = [q for q in qs if q["id"] in keep]

rows, ok_total = [], 0
for q in qs:
    problems = []
    try:
        r = agent.run(q["pertanyaan"])
        called = [s["tool"] for s in r["steps"]]
        for t in q.get("alat_wajib", []):
            if t not in called:
                problems.append(f"tidak memanggil {t}")
        if q.get("alat_salah_satu") and not set(called) & set(q["alat_salah_satu"]):
            problems.append(f"tidak memanggil salah satu dari {q['alat_salah_satu']}")
        for t in q.get("alat_dilarang", []):
            if t in called:
                problems.append(f"memanggil {t} padahal tidak perlu")
        for tool, exp in q.get("argumen", {}).items():
            got = [s["args"] for s in r["steps"] if s["tool"] == tool]
            if got and any(g.get(k) != v for g in got[:1] for k, v in exp.items()):
                problems.append(f"argumen {tool} {got[0]} tidak sesuai {exp}")
        if q.get("status_alat"):
            st_ = [s["payload"].get("status") for s in r["steps"]]
            if q["status_alat"] not in st_:
                problems.append(f"status alat {st_} bukan {q['status_alat']}")
        if q.get("jawaban_harus_memuat_salah_satu"):
            if not any(w.lower() in r["answer"].lower() for w in q["jawaban_harus_memuat_salah_satu"]):
                problems.append("jawaban tidak menyebut peringatan bisnis")
        answer, usage, lat = r["answer"], r["usage"], r["latency_s"]
    except Exception as e:
        called, answer, usage, lat = [], "", {}, 0
        problems.append(f"error: {e}")
    ok = not problems
    ok_total += ok
    print(f"[{q['id']:>2}] {'LULUS' if ok else 'GAGAL'}  alat={called}  {q['pertanyaan']}")
    for p in problems:
        print(f"       - {p}")
    rows.append({"id": q["id"], "pertanyaan": q["pertanyaan"], "lulus": ok, "alat": " > ".join(called),
                 "masalah": "; ".join(problems), "jawaban": answer,
                 "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                 "latency_s": lat})

print(f"\n{config.LLM_MODEL} | thinking={config.LLM_THINKING} | lulus {ok_total}/{len(qs)}")
config.REPORT_DIR.mkdir(exist_ok=True)
path = config.REPORT_DIR / f"agent_eval_{time.strftime('%Y%m%d_%H%M%S')}.csv"
with open(path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"Detail: {path}")
