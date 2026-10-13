"""插件定向测试引导；复用宿主隔离和网络守卫，不依赖仓库旧版network_guard路径。"""

import os
import sys
from pathlib import Path

BACKEND = Path(os.environ.get('MOVIEPILOT_BACKEND_PATH', str(Path(__file__).parents[4] / 'MoviePilot')))
if not (BACKEND / 'app/testing/bootstrap.py').is_file():
    raise RuntimeError('请通过 MOVIEPILOT_BACKEND_PATH 指定 MoviePilot 源码根目录')
sys.path.insert(0, str(BACKEND))

from app.testing.bootstrap import prepare_backend
from app.testing.network import block_real_network  # noqa: F401

prepare_backend()
