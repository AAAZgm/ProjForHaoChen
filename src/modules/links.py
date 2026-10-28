"""Extract a video URL from shared text without losing query parameters."""
import re

def extract_url(text) -> str:
    """从一段文字中提取 http(s) 开头的链接。

    适用场景：别人发的分享是"标题 + 链接"混合的文字，例如：
      【你看这个古振兴他饿不饿-哔哩哔哩】 https://b23.tv/7hLWYrn
    会提取出：https://b23.tv/7hLWYrn

    截断规则：从 http 开始，到第一个空白字符 / 中文 / 中文标点为止；
    如果文字里没有 http，则原样返回（可能用户只粘贴了链接）。
    """
    if not text:
        return ""
    text = str(text).strip()
    # 保留 ?p=、&、# 等 URL 字符，仅截断分享文字及包围链接的标点。
    m = re.search(r'''https?://[^\s<>"'，。；、！？（）【】〔〕\u4e00-\u9fff]+''',
                  text, flags=re.IGNORECASE)
    if not m:
        return text
    return m.group(0).rstrip(".,;!?)\u005d}")


