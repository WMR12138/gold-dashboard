#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金看板每日更新脚本
- 数据源：上海黄金交易所 Au99.99 现价 + 新浪 USD/CNY 汇率
- 更新内容：顶部金价、近两周走势图、最近记录表、机构预测人民币换算、页脚时间
- 全年走势缩略图保持不动（年度维度，无需每日重绘）
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

CN_TZ = timezone(timedelta(hours=8))
PREMIUM = 10.0          # 民生生肖金条加价：元/克
OZ_TO_GRAM = 31.1035
ROWS_KEEP = 30          # 最近记录保留条数

BASE = "."
FILES = ["index.html", "dashboard.html"]
HISTORY = "data/history.json"


def http_get(url, referer=None, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        **({"Referer": referer} if referer else {}),
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def fetch_sge():
    """返回 (date_str, price_yuan_per_gram)"""
    txt = http_get("https://www.sge.com.cn/graph/quotations")
    d = json.loads(txt)
    data = d.get("data") or []
    if not data:
        raise RuntimeError("SGE data empty")
    price = float(data[-1])
    delay = d.get("delaystr", "")  # 例: 2026年11月23日 12:03:57
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", delay)
    if m:
        date_str = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    else:
        date_str = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    return date_str, price


def fetch_usdcny():
    txt = http_get("https://hq.sinajs.cn/list=fx_susdcny", referer="https://finance.sina.com.cn")
    m = re.search(r'"(.*?)"', txt)
    if not m:
        raise RuntimeError("fx parse fail")
    parts = m.group(1).split(",")
    for p in parts:
        try:
            v = float(p)
        except ValueError:
            continue
        if 5.0 < v < 9.0:
            return v
    raise RuntimeError("fx value not found")


ROW_RE = re.compile(
    r'<tr style="[^"]*">\s*'
    r'<td style="color:#333">(\d{4}-\d{2}-\d{2})</td>\s*'
    r'<td style="text-align:right;font-weight:600">([\d.]+)</td>\s*'
    r'<td[^>]*>([▲▼])\s*([\d.]+)</td></tr>',
    re.S,
)


def parse_rows(html):
    rows = []
    for m in ROW_RE.finditer(html):
        rows.append({
            "date": m.group(1),
            "price": float(m.group(2)),
            "dir": m.group(3),
            "diff": float(m.group(4)),
        })
    return rows


def build_rows_html(rows):
    """rows: 按日期倒序，第一行高亮"""
    out = []
    for i, r in enumerate(rows):
        bg = ' style="background:rgba(229,57,53,0.06)"' if i == 0 else ' style=""'
        color = "#e53935" if r["dir"] == "▲" else "#12a150"
        out.append(
            '<tr%s>\n'
            '    <td style="color:#333">%s</td>\n'
            '    <td style="text-align:right;font-weight:600">%.2f</td>\n'
            '    <td style="text-align:right;color:%s">%s %.2f</td></tr>'
            % (bg, r["date"], r["price"], color, r["dir"], r["diff"])
        )
    return "".join(out)


def nice_axis(vmin, vmax, steps=4):
    span = max(vmax - vmin, 1e-6)
    raw = span / steps
    mag = 10 ** int(f"{raw:e}".split("e")[1])
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    lo = (int(vmin // step)) * step
    hi = lo + step * steps
    while hi < vmax:
        hi += step
        steps += 1
    return lo, hi, steps


def build_week_svg(rows):
    """rows: 升序（旧->新），最多 10 条"""
    pts = rows[-10:]
    if len(pts) < 2:
        return None
    x0, x1 = 42.0, 326.0
    y0, y1 = 18.0, 176.0
    prices = [p["price"] for p in pts]
    lo, hi, n = nice_axis(min(prices), max(prices))
    if hi - lo < 1e-6:
        hi = lo + 1

    def ymap(v):
        return y1 - (v - lo) / (hi - lo) * (y1 - y0)

    def xmap(i):
        return x0 + i * (x1 - x0) / (len(pts) - 1)

    s = ['<svg viewBox="0 0 340 210">']
    step = (hi - lo) / n
    for k in range(n + 1):
        val = lo + k * step
        y = ymap(val)
        s.append('<line x1="42" y1="%.2f" x2="326" y2="%.2f" stroke="#eee"/>' % (y, y))
        s.append('<text x="37" y="%.2f" font-size="8.5" fill="#999" text-anchor="end">%g</text>' % (y + 3, round(val)))
    coords = " ".join("%.2f,%.2f" % (xmap(i), ymap(p["price"])) for i, p in enumerate(pts))
    s.append('<polyline points="%s" fill="none" stroke="#c19a2b" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' % coords)
    for i, p in enumerate(pts):
        last = (i == len(pts) - 1)
        s.append('<circle cx="%.2f" cy="%.2f" r="%s" fill="%s"/>' % (
            xmap(i), ymap(p["price"]), "3.2" if last else "2.6", "#e53935" if last else "#c19a2b"))
    for i, p in enumerate(pts):
        last = (i == len(pts) - 1)
        s.append('<text x="%.2f" y="189" font-size="7.5" fill="%s" text-anchor="end" transform="rotate(-40 %.2f 189)">%s</text>'
                 % (xmap(i), "#e53935" if last else "#999", xmap(i), p["date"][5:]))
    s.append("</svg>")
    return "".join(s)


def main():
    now = datetime.now(CN_TZ)
    try:
        date_str, au_price = fetch_sge()
        fx = fetch_usdcny()
    except Exception as e:
        print("FETCH FAILED:", e, file=sys.stderr)
        return 0  # 不修改文件，workflow 不会产生提交

    bar_price = round(au_price + PREMIUM, 2)

    path = FILES[0]
    html = open(path, encoding="utf-8").read()
    rows = parse_rows(html)
    if not rows:
        print("no rows parsed", file=sys.stderr)
        return 1

    # 同日已有则覆盖价格，否则插入
    if rows[0]["date"] == date_str:
        rows[0]["price"] = bar_price
    else:
        rows.insert(0, {"date": date_str, "price": bar_price, "dir": "▲", "diff": 0.0})

    # 重新计算涨跌（倒序，i 的前一日是 i+1）
    for i in range(len(rows) - 1):
        d = round(rows[i]["price"] - rows[i + 1]["price"], 2)
        rows[i]["dir"] = "▲" if d >= 0 else "▼"
        rows[i]["diff"] = abs(d)

    kept = rows[:ROWS_KEEP]
    latest = kept[0]
    prev = kept[1] if len(kept) > 1 else kept[0]
    pct = (latest["price"] - prev["price"]) / prev["price"] * 100 if prev["price"] else 0.0

    # 历史累积
    try:
        hist = json.load(open(HISTORY, encoding="utf-8"))
    except Exception:
        hist = {}
    hist[latest["date"]] = latest["price"]
    import os
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    json.dump(dict(sorted(hist.items())), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    new_week = build_week_svg(list(reversed(kept)))
    rows_html = build_rows_html(kept)
    stamp = now.strftime("%Y-%m-%d %H:%M")
    mmdd = latest["date"][5:]

    for f in FILES:
        h = open(f, encoding="utf-8").read()

        # 顶部价格
        h = re.sub(r'<div class="price">[\d.]+</div>',
                   '<div class="price">%.2f</div>' % latest["price"], h, count=1)
        # badge
        arrow = "▲" if pct >= 0 else "▼"
        h = re.sub(r'<div class="badge">.*?</div>',
                   '<div class="badge">%s %s %.2f%%</div>' % (mmdd, arrow, pct), h, count=1)
        # 近两周 SVG（仅替换该卡片内的 svg，全年走势图不动）
        if new_week:
            h = re.sub(r'(<h2>近两周走势（元/克）</h2>\s*)<svg.*?</svg>',
                       lambda m: m.group(1) + new_week, h, count=1, flags=re.S)
        # 表格
        h = re.sub(r'(<tbody>)(.*?)(</tbody>)',
                   lambda m: m.group(1) + rows_html + m.group(3), h, count=1, flags=re.S)
        h = re.sub(r'最近记录（共 \d+ 个交易日）', '最近记录（共 %d 个交易日）' % max(214, len(hist)), h, count=1)
        # 预测换算
        def conv(m):
            usd = float(m.group(1))
            return "%g 美元/盎司</b>（约 <b>%d 元/克" % (usd, round(usd * fx / OZ_TO_GRAM))
        h = re.sub(r'([\d.]+) 美元/盎司</b>（约 <b>\d+ 元/克', conv, h)
        h = re.sub(r'按当前汇率 [\d.]+ 换算', '按当前汇率 %.2f 换算' % fx, h)
        h = re.sub(r'（截至 \d{4}-\d{2}）', '（截至 %s）' % latest["date"][:7], h)
        # 页脚时间
        h = re.sub(r'更新 \d{4}-\d{2}-\d{2} \d{2}:\d{2}', '更新 %s' % stamp, h)
        open(f, "w", encoding="utf-8").write(h)

    print("OK %s Au99.99=%.2f bar=%.2f fx=%.4f pct=%.2f%%" % (date_str, au_price, bar_price, fx, pct))
    return 0


if __name__ == "__main__":
    sys.exit(main())
