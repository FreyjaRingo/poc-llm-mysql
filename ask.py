"""
Bertanya ke DeepSeek dari terminal, tanpa dashboard.

Contoh:
    python ask.py "Siapa sales rep dengan penjualan terbesar?"
    python ask.py "Berapa jumlah pelanggan?" --show-prompt
    python ask.py "..." --no-summary      # hasil query tidak dikirim ke DeepSeek
    python ask.py "..." --thinking on --rules on
"""
import argparse

from core import config, pipeline

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("--show-prompt", action="store_true")
ap.add_argument("--no-summary", action="store_true")
ap.add_argument("--rules", choices=["on", "off"])
ap.add_argument("--thinking", choices=["on", "off"])
args = ap.parse_args()
if args.rules:
    config.INCLUDE_BUSINESS_RULES = args.rules == "on"
if args.thinking:
    config.LLM_THINKING = "enabled" if args.thinking == "on" else "disabled"
pipeline.ask(args.question, args.show_prompt, not args.no_summary)
