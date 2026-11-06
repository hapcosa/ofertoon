"""Cruza IDs reales de colecciones Shopify medidos por shopify_audit.py."""
import argparse
import itertools
import json
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("files", nargs="+", type=Path)
args = parser.parse_args()
groups = [(json.loads(path.read_text())["handle"],
           set(json.loads(path.read_text())["ids"])) for path in args.files]
for (left, a), (right, b) in itertools.combinations(groups, 2):
    shared = a & b
    print(f"{left} × {right}: {len(shared)} compartidos / {len(a)} + {len(b)}; "
          f"Jaccard={len(shared) / len(a | b):.4f}")
print("TOTAL", len(set().union(*(ids for _, ids in groups))))
