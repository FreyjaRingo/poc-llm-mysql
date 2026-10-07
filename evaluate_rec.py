"""
Evaluasi metode rekomendasi dengan split waktu.

Model hanya melihat transaksi sebelum --cutoff (default 1 Jan 2005). Lalu dicek: dari 10
produk yang direkomendasikan, berapa yang benar-benar dibeli pelanggan setelah cutoff.
Hanya produk BARU (belum pernah dibeli sebelum cutoff) yang dihitung.

  hit       : persen pelanggan yang minimal 1 rekomendasinya dibeli
  precision : rata-rata porsi rekomendasi yang dibeli (dari 10)
  recall    : rata-rata porsi produk baru yang berhasil ditebak
  ci_low/ci_high : selang kepercayaan 95% (bootstrap). Jika selang dua metode
                   tumpang tindih, selisihnya belum tentu bermakna.

Contoh:
    python evaluate_rec.py               # 4 metode tanpa LLM, gratis, beberapa detik
    python evaluate_rec.py --with-llm    # tambah metode LLM (sekitar 44 panggilan DeepSeek)
"""
import argparse
import sys
import time

from core import config, features, recommend

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser()
ap.add_argument("--cutoff", default="2005-01-01")
ap.add_argument("--with-llm", action="store_true")
ap.add_argument("--thinking", choices=["on", "off"])
args = ap.parse_args()
if args.thinking:
    config.LLM_THINKING = "enabled" if args.thinking == "on" else "disabled"

data = features.load_data()


def progress(i, n):
    print(f"\r  pelanggan {i}/{n}", end="", flush=True)


print(f"Latih: transaksi sebelum {args.cutoff} | Uji: produk baru yang dibeli sesudahnya")
t = time.time()
summary, detail = recommend.evaluate(data, args.cutoff, llm=args.with_llm, progress=progress)
print(f"\n  selesai dalam {time.time() - t:.0f} detik\n")

fmt = summary.copy()
for m in ("hit", "precision", "recall"):
    fmt[m] = fmt.apply(lambda r: f"{r[m]:.1%} [{r[m + '_ci_low']:.1%}, {r[m + '_ci_high']:.1%}]", axis=1)
print(fmt[["metode", "pelanggan_diuji", "hit", "precision", "recall"]].to_string(index=False))
if "invalid" in detail.columns:
    inv = detail.loc[detail.metode == "llm", "invalid"].sum()
    print(f"\nKode produk tidak valid dari LLM (dibuang): {int(inv)}")

config.REPORT_DIR.mkdir(exist_ok=True)
tag = time.strftime("%Y%m%d_%H%M%S") + ("_llm" if args.with_llm else "")
summary.to_csv(config.REPORT_DIR / f"rec_eval_{tag}_ringkasan.csv", index=False, encoding="utf-8-sig")
detail.to_csv(config.REPORT_DIR / f"rec_eval_{tag}_detail.csv", index=False, encoding="utf-8-sig")
print(f"\nLaporan: reports/rec_eval_{tag}_*.csv")
