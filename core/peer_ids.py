"""好友名字 → 抖音 uid，按账号分开存。

会话列表有时只把好友标题显示成数字（昵称资料没加载出来），按名字就找不到人；
按名字找到过一次就记下 uid，以后数字标题也认得出来。放在已挂载的 logs/ 里，换镜像不丢。
"""
import json
from pathlib import Path

PEERS_FILE = Path(__file__).resolve().parent.parent / "logs" / "peer_ids.json"


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(account, path=None):
    ids = _read(path or PEERS_FILE).get(str(account))
    return dict(ids) if isinstance(ids, dict) else {}


def save(account, ids, path=None):
    """尽力而为：有新内容才写，写失败不影响任务。"""
    path = Path(path or PEERS_FILE)
    try:
        data = _read(path)
        if data.get(str(account), {}) == ids:
            return
        data[str(account)] = dict(ids)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
