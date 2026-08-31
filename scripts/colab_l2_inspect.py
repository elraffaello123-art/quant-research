"""
colab_l2_inspect.py — Step 1: find out what the L2 and options data actually ARE.

RUNS IN COLAB, NOT ON THE MAC. The L2 corpus is ~470 GB (376 MB/day x ~1250 days).
It never comes to this machine — see the hard rule in CLAUDE.md. Colab reads it straight
from mounted Drive without copying, so it also costs zero storage.

>>> BEFORE YOU RUN THIS <<<
Folders that are SHARED WITH YOU do not show up in Colab by default. Only "My Drive" does.
So for each of the two folders, in the Drive web UI:
    right-click the folder -> Organize -> Add shortcut to Drive -> My Drive
Then it appears in Colab at /content/drive/MyDrive/<folder name>.

Paste each CELL below into its own Colab cell.
"""

# ============================================================ CELL 1
# Mount Drive and inventory both folders. This settles how much data actually exists —
# the Drive connector on the Mac only sees a partial view, so your account is the truth.

from google.colab import drive
drive.mount('/content/drive')

import os

# EDIT THESE to match the shortcut names you just created.
L2   = '/content/drive/MyDrive/<L2 folder name>'      # the 1-JGEw2Bx... folder
OPTS = '/content/drive/MyDrive/<options folder name>' # the 1Tm84_l-... folder

for label, base in [('L2', L2), ('OPTIONS', OPTS)]:
    print('=' * 60)
    print(label, base)
    if not os.path.exists(base):
        print('  NOT FOUND — did the shortcut get added to My Drive?')
        continue
    n_files = n_bytes = 0
    for root, _dirs, files in os.walk(base):
        if not files:
            continue
        sizes = [os.path.getsize(os.path.join(root, f)) for f in files]
        n_files += len(files)
        n_bytes += sum(sizes)
        rel = os.path.relpath(root, base)
        print(f'  {rel:<24} {len(files):>5} files  {sum(sizes)/1e9:>7.2f} GB')
        for f in sorted(files)[:3]:
            print(f'      e.g. {f}')
    print(f'  TOTAL: {n_files} files, {n_bytes/1e9:.1f} GB')


# ============================================================ CELL 2
# What IS an L2 file? Everything downstream depends on this answer.
#
#   bid_px_00..09 / bid_sz_00..09  -> depth snapshots. OBI is a direct column sum. EASY.
#   order_id / action (add/cancel) -> per-order events. The order book must be REPLAYED
#                                     to get depth levels. Much harder; a plain format
#                                     conversion would produce nothing usable.
#
# 376 MB/day is small for NQ — full per-order data would be several GB/day — so the
# depth-snapshot case is likely. Confirm rather than assume.

import pandas as pd

F = '<paste the full path to one L2 csv from Cell 1>'

head = pd.read_csv(F, nrows=5)
print('columns:', head.columns.tolist())
print()
print(head.dtypes)
print()
print(head.T.to_string())

# How many rows in the whole day? Tells us the snapshot frequency.
with open(F) as fh:
    n = sum(1 for _ in fh) - 1
print(f'\nrows in this file: {n:,}')
print(f'~{n/23400:.1f} rows/second if this covers a 6.5h session')
