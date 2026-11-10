"""List uiautomator nodes with text and bounds (UTF-8 console friendly)."""

import re
import sys


def main() -> None:
    xml = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    keyword = sys.argv[2] if len(sys.argv) > 2 else ""
    pattern = r"<node[^>]*/>"
    for node in re.findall(pattern, xml):
        text = re.search(r'text="([^"]*)"', node)
        desc = re.search(r'content-desc="([^"]*)"', node)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not bounds:
            continue
        label = (text.group(1) if text else "") or (desc.group(1) if desc else "")
        flag = "CLICK" if 'clickable="true"' in node else ("CHECK" if 'checkable="true"' in node else "")
        if keyword and keyword not in label:
            continue
        if not label and not flag:
            continue
        x1, y1, x2, y2 = map(int, bounds.groups())
        print(f"{(x1 + x2) // 2:5d} {(y1 + y2) // 2:5d}  {flag:5s} {label}")


if __name__ == "__main__":
    main()
