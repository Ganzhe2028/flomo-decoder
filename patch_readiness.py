from pathlib import Path

path = Path("scripts/check_open_source_readiness.py")
text = path.read_text(encoding="utf-8")
lines = text.split("\n")

start = None
end = None
for i, line in enumerate(lines):
    if line == "PRIVATE_TEXT_RE = re.compile(":
        start = i
    if start is not None and line == ")":
        end = i
        break

assert start is not None and end is not None, (start, end)

new_block = '''def _build_private_text_re() -> re.Pattern[str]:
    """通用个人路径模式，可选叠加 FLOMO_PRIVATE_TEXT_PATTERNS 环境变量。

    不在仓库里硬编码任何个人用户名/设备名；本机需要时可经环境变量追加
    正则片段，例如 FLOMO_PRIVATE_TEXT_PATTERNS='flomo@Myname|MyDevice'。
    """
    extra = os.environ.get("FLOMO_PRIVATE_TEXT_PATTERNS", "").strip()
    parts = [
        r"/Users/[^\\\\s)]+",
        r"C:\\\\\\\\Users\\\\\\\\[^\\\\s)]+",
    ]
    if extra:
        parts.append(extra)
    return re.compile(r"(" + "|".join(parts) + r")", re.IGNORECASE)


PRIVATE_TEXT_RE = _build_private_text_re()'''

lines[start:end + 1] = new_block.split("\n")

for i, line in enumerate(lines):
    if line == "import re":
        lines.insert(i, "import os")
        break

path.write_text("\n".join(lines), encoding="utf-8")
print("patched OK")
