"""Проверка: Pinterest отдаёт пины с этого IP и картинки скачиваются."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.harvester import PinterestHarvester  # noqa: E402

h = PinterestHarvester(on_status=lambda m: None)
try:
    metas = h.search("girl eating cereal at night kitchen phone photo")
    print(f"Pinterest: найдено пинов {len(metas)}")
    sys.exit(0 if metas else 1)
finally:
    h.close()
