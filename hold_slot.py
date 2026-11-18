"""Занять слот очереди видеокарты (core.gpu_slots) — на ходу уменьшить число одновременных сборок без перезапуска.
  python hold_slot.py 3          # держит slot_3.lock, пока процесс жив"""
import msvcrt
import sys
import time
from pathlib import Path

k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
d = Path(r"C:\Users\user\Documents\GitHub\farm\output\_work\_gpu_slots")
d.mkdir(parents=True, exist_ok=True)
f = open(d / f"slot_{k}.lock", "a+")
f.seek(0)
while True:
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        break
    except OSError:
        time.sleep(0.2)                                   # слот занят сборкой — ждём, когда она закончится
print(f"слот {k} занят заглушкой", flush=True)
while True:
    time.sleep(60)
