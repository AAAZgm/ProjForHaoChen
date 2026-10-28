"""An explicit, read-only release check; never downloads or executes updates."""
import json
import urllib.error
import urllib.request
from packaging.version import Version, InvalidVersion

from . import runtime

API = "https://api.github.com/repos/AAAZgm/ProjForHaoChen/releases/latest"


def check_update():
    request = urllib.request.Request(API, headers={"User-Agent": f"BiliVideoTool/{runtime.APP_VERSION}",
                                                 "Accept": "application/vnd.github+json"})
    link = f"[打开发布页]({runtime.RELEASES_URL})"
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            release = json.loads(response.read(1024 * 1024))
        if release.get("draft") or release.get("prerelease"):
            return f"暂无正式版本更新。{link}"
        tag = str(release["tag_name"])
        latest, current = Version(tag.lstrip("v")), Version(runtime.APP_VERSION)
        if latest > current:
            return f"发现正式版本 **{latest}**（当前 {runtime.APP_VERSION}）。请在发布页查看说明并下载；配置与原有成品会保留。{link}"
        return f"当前版本 {runtime.APP_VERSION}；未发现更新的正式版本。{link}"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return f"仓库尚未提供正式发布版本。当前 {runtime.APP_VERSION} 可继续使用。{link}"
        if exc.code in (403, 429):
            return f"更新服务暂时限流，请稍后再试。{link}"
    except (OSError, ValueError, KeyError, InvalidVersion):
        pass
    return f"暂时无法检查更新，请检查网络后重试。本地编辑不受影响。{link}"
