#!/usr/bin/env python3
"""
=============================================================
Reddit Japan Travel Monitor v3
=============================================================
v2の全機能 + 年間データの月別分解（ヒストリカルトレンド）

【新機能】
  年間データ(t=year)の各投稿にはcreated_utc（投稿日時）が含まれる。
  これを月別にグルーピングすることで、過去12ヶ月のトレンド推移を
  追加のAPIリクエストなしで生成する。

【使い方】
  python reddit_monitor.py                   # 月次+年間+ヒストリカル
  python reddit_monitor.py --period month    # 月次のみ
  python reddit_monitor.py --period year     # 年間+ヒストリカル
  python reddit_monitor.py --cities "onomichi,tottori"  # 都市を絞る

【出力】
  output/gem_month_YYYYMMDD.csv      — 月次スナップショット
  output/gem_year_YYYYMMDD.csv       — 年間ベースライン
  output/gem_history_YYYYMMDD.csv    — ★新★ 過去12ヶ月の月別推移
  output/gem_combined_YYYYMMDD.json  — 統合JSON
  output/gem_cross_YYYYMMDD.json     — クロス分析
=============================================================
"""

import urllib.request
import urllib.parse
import json
import csv
import os
import sys
import time
from datetime import datetime
from collections import defaultdict

# ============================================================
# 設定
# ============================================================

REDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddit}/search.json"
USER_AGENT = "Mozilla/5.0 (compatible; JapanTravelMonitor/3.0)"
SUBREDDITS = ["JapanTravel", "JapanTravelTips"]
REQUEST_DELAY = 2.5
PERIODS = ["month", "year"]

# ============================================================
# 監視対象都市
# ============================================================

TARGETS = {
    "Onomichi":     {"q": "onomichi", "ja": "尾道",     "region": "広島",   "cat": "候補A"},
    "Kurashiki":    {"q": "kurashiki", "ja": "倉敷",    "region": "岡山",   "cat": "候補A"},
    "Naoshima":     {"q": "naoshima",  "ja": "直島",    "region": "香川",   "cat": "候補A"},
    "Beppu":        {"q": "beppu",     "ja": "別府",    "region": "大分",   "cat": "候補A"},
    "Kagoshima":    {"q": "kagoshima", "ja": "鹿児島",  "region": "鹿児島", "cat": "候補A"},
    "Matsuyama":    {"q": "matsuyama", "ja": "松山",    "region": "愛媛",   "cat": "候補B"},
    "Hakodate":     {"q": "hakodate",  "ja": "函館",    "region": "北海道", "cat": "候補B"},
    "Nagasaki":     {"q": "nagasaki",  "ja": "長崎",    "region": "長崎",   "cat": "候補B"},
    "Matsumoto":    {"q": "matsumoto", "ja": "松本",    "region": "長野",   "cat": "候補B"},
    "Kawagoe":      {"q": "kawagoe",   "ja": "川越",    "region": "埼玉",   "cat": "候補B"},
    "Kinosaki":     {"q": "kinosaki",  "ja": "城崎温泉","region": "兵庫",   "cat": "候補B"},
    "Tottori":      {"q": "tottori",   "ja": "鳥取",    "region": "鳥取",   "cat": "候補B"},
    "Sendai":       {"q": "sendai",    "ja": "仙台",    "region": "宮城",   "cat": "運営中"},
    "Takaoka":      {"q": "takaoka",   "ja": "高岡",    "region": "富山",   "cat": "運営中"},
    "Takayama":     {"q": "takayama",  "ja": "高山",    "region": "岐阜",   "cat": "BM"},
    "Kanazawa":     {"q": "kanazawa",  "ja": "金沢",    "region": "石川",   "cat": "BM"},
    "Fukuoka":      {"q": "fukuoka",   "ja": "福岡",    "region": "福岡",   "cat": "BM"},
    "Hiroshima":    {"q": "hiroshima", "ja": "広島",    "region": "広島",   "cat": "BM"},
    "Shimanami":    {"q": "shimanami", "ja": "しまなみ海道", "region": "広島/愛媛", "cat": "Watch"},
    "Ginzan Onsen": {"q": "ginzan",    "ja": "銀山温泉","region": "山形",   "cat": "Watch"},
    "Yamadera":     {"q": "yamadera",  "ja": "山寺",    "region": "山形",   "cat": "Watch"},
    "Toyama":       {"q": "toyama",    "ja": "富山",    "region": "富山",   "cat": "Watch"},
    "Gokayama":     {"q": "gokayama",  "ja": "五箇山",  "region": "富山",   "cat": "Watch"},
    "Yakushima":    {"q": "yakushima", "ja": "屋久島",  "region": "鹿児島", "cat": "Watch"},
    "Kamikochi":    {"q": "kamikochi", "ja": "上高地",  "region": "長野",   "cat": "Watch"},
    "Kakunodate":   {"q": "kakunodate","ja": "角館",    "region": "秋田",   "cat": "Watch"},
    "Noto":         {"q": "noto peninsula", "ja": "能登半島", "region": "石川", "cat": "Watch"},
    "Amanohashidate": {"q": "amanohashidate", "ja": "天橋立", "region": "京都", "cat": "Watch"},
}

SUPPLY_GAP_QUERIES = [
    "{city} accommodation", "{city} where to stay",
    "{city} hotel", "{city} airbnb",
]

# ============================================================
# Reddit検索
# ============================================================

def reddit_search(subreddit, query, time_filter="year", limit=100):
    params = {
        "q": query, "restrict_sr": "on", "sort": "new",  # v3: sortをnewに変更（日付順で取得）
        "t": time_filter, "limit": str(limit), "type": "link",
    }
    url = REDDIT_SEARCH_URL.format(subreddit=subreddit)
    url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("children", [])
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"⏳429...", end=" ", flush=True)
            time.sleep(10)
            return reddit_search(subreddit, query, time_filter, limit)
        print(f"❌{e.code}", end=" ", flush=True)
        return []
    except Exception as e:
        print(f"❌{e}", end=" ", flush=True)
        return []


def fetch_city_posts(query, time_filter):
    """
    全サブレディットから投稿を取得し、生の投稿リストを返す。
    ヒストリカル分析用にcreated_utcを保持。
    """
    all_posts = []
    for sub in SUBREDDITS:
        posts = reddit_search(sub, query, time_filter)
        time.sleep(REQUEST_DELAY)
        for post in posts:
            d = post.get("data", {})
            created_utc = d.get("created_utc", 0)
            all_posts.append({
                "title": d.get("title", ""),
                "score": d.get("score", 0),
                "comments": d.get("num_comments", 0),
                "created_utc": created_utc,
                "date": datetime.fromtimestamp(created_utc).strftime("%Y-%m-%d"),
                "month": datetime.fromtimestamp(created_utc).strftime("%Y-%m"),
                "url": f"https://reddit.com{d.get('permalink', '')}",
            })
    return all_posts


def summarize_posts(posts):
    """投稿リストから集計値を算出"""
    if not posts:
        return {
            "post_count": 0, "total_score": 0, "total_comments": 0,
            "avg_score": 0, "avg_comments": 0, "top_posts": [],
        }
    total_score = sum(p["score"] for p in posts)
    total_comments = sum(p["comments"] for p in posts)
    return {
        "post_count": len(posts),
        "total_score": total_score,
        "total_comments": total_comments,
        "avg_score": round(total_score / len(posts), 1),
        "avg_comments": round(total_comments / len(posts), 1),
        "top_posts": sorted(posts, key=lambda x: x["score"], reverse=True)[:5],
    }


def check_supply_gap(city_query, time_filter):
    gap_posts = 0
    for template in SUPPLY_GAP_QUERIES:
        q = template.format(city=city_query)
        posts = reddit_search("JapanTravel", q, time_filter, limit=25)
        time.sleep(REQUEST_DELAY)
        for post in posts:
            text = (post.get("data", {}).get("title", "") + " " +
                    post.get("data", {}).get("selftext", "")).lower()
            if any(kw in text for kw in [
                "hard to find", "limited", "no hotel", "sold out",
                "fully booked", "nowhere to stay", "few options",
                "difficult", "not many", "any recommendations"
            ]):
                gap_posts += 1
    return gap_posts


# ============================================================
# スコアリング
# ============================================================

def calc_gem_score(mentions, supply_gap, period):
    count = mentions["post_count"]
    if period == "month":
        if count == 0:     buzz = 0
        elif count <= 2:   buzz = count * 15
        elif count <= 5:   buzz = 40 + (count - 2) * 12
        elif count <= 15:  buzz = 80 + min(20, (count - 5) * 2)
        elif count <= 30:  buzz = 75 - (count - 15)
        else:              buzz = max(20, 60 - (count - 30) * 2)
    else:
        if count == 0:     buzz = 0
        elif count <= 3:   buzz = count * 12
        elif count <= 10:  buzz = 40 + (count - 3) * 7
        elif count <= 30:  buzz = 85 + min(15, (count - 10))
        elif count <= 60:  buzz = 80 - (count - 30)
        else:              buzz = max(20, 50 - (count - 60))

    engagement = min(100, mentions["avg_score"] * 1.5)
    gap = min(100, supply_gap * (30 if period == "month" else 20))
    comment_density = min(100, mentions["avg_comments"] * 5)
    return round(buzz * 0.30 + engagement * 0.20 + gap * 0.35 + comment_density * 0.15)


# ============================================================
# ヒストリカル分析（★新機能）
# ============================================================

def build_monthly_history(city_posts_map, targets):
    """
    年間データの投稿を月別（YYYY-MM）にグルーピングし、
    都市×月のマトリクスを生成する。
    """
    # 過去12ヶ月のキーを生成
    now = datetime.now()
    months = []
    for i in range(12, 0, -1):
        y = now.year
        m = now.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")
    # 今月も追加
    months.append(f"{now.year:04d}-{now.month:02d}")

    history_rows = []

    for city_en, posts in city_posts_map.items():
        info = targets[city_en]

        # 月別にグループ化
        by_month = defaultdict(list)
        for p in posts:
            by_month[p["month"]].append(p)

        for month_key in months:
            month_posts = by_month.get(month_key, [])
            count = len(month_posts)
            total_up = sum(p["score"] for p in month_posts)
            total_comments = sum(p["comments"] for p in month_posts)

            history_rows.append({
                "city_en": city_en,
                "city_ja": info["ja"],
                "region": info["region"],
                "category": info["cat"],
                "month": month_key,
                "post_count": count,
                "total_score": total_up,
                "avg_score": round(total_up / max(count, 1), 1),
                "avg_comments": round(total_comments / max(count, 1), 1),
            })

    return history_rows, months


def print_history(history_rows, months, targets):
    """ヒストリカルトレンドのコンソール表示"""
    print(f"\n{'=' * 60}")
    print(f"📈 ヒストリカルトレンド（過去12ヶ月 + 今月）")
    print(f"{'=' * 60}")

    # 月ラベル（短縮）
    short_months = [m[5:] for m in months]  # "04", "05", ...
    header = f"  {'都市':<8} " + " ".join(f"{m:>3}" for m in short_months) + "  trend"
    print(f"\n{header}")
    print(f"  {'─' * (8 + len(months) * 4 + 8)}")

    # 都市ごとのスパークライン
    city_monthly = defaultdict(dict)
    for row in history_rows:
        city_monthly[row["city_en"]][row["month"]] = row["post_count"]

    # トレンド計算（後半6ヶ月の平均 vs 前半6ヶ月の平均）
    city_trends = []
    for city_en in city_monthly:
        counts = [city_monthly[city_en].get(m, 0) for m in months]
        first_half = sum(counts[:6]) / max(len([c for c in counts[:6] if c > 0]), 1)
        second_half = sum(counts[6:]) / max(len([c for c in counts[6:] if c > 0]), 1)

        if first_half > 0:
            trend_ratio = second_half / first_half
        elif second_half > 0:
            trend_ratio = 99.0
        else:
            trend_ratio = 0.0

        city_trends.append((city_en, counts, trend_ratio))

    # トレンド比率順にソート
    city_trends.sort(key=lambda x: x[2], reverse=True)

    for city_en, counts, trend_ratio in city_trends:
        info = targets[city_en]
        max_count = max(counts) if counts else 1

        # スパークライン（数字がゼロなら·、それ以外は数字）
        spark = []
        for c in counts:
            if c == 0:
                spark.append("  ·")
            elif c < 10:
                spark.append(f"  {c}")
            else:
                spark.append(f"{c:>3}")

        # トレンドアイコン
        if trend_ratio >= 2.0:
            trend_icon = "🔥🔥"
        elif trend_ratio >= 1.5:
            trend_icon = " 🔥"
        elif trend_ratio >= 1.2:
            trend_icon = " 📈"
        elif trend_ratio >= 0.8:
            trend_icon = " → "
        elif trend_ratio > 0:
            trend_icon = " 📉"
        else:
            trend_icon = " ⚪"

        line = " ".join(spark)
        print(f"  {info['ja']:<7} {line} {trend_icon}")

    # 注目トレンド
    rising = [(en, counts, ratio) for en, counts, ratio in city_trends if ratio >= 1.5 and sum(counts[6:]) >= 3]
    if rising:
        print(f"\n  🚨 後半6ヶ月で加速している都市（前半比1.5倍以上）:")
        for en, counts, ratio in rising:
            info = targets[en]
            h1 = sum(counts[:6])
            h2 = sum(counts[6:])
            print(f"     {info['ja']}：前半{h1}件 → 後半{h2}件（{ratio:.1f}倍）")

    return city_trends


# ============================================================
# スキャン実行
# ============================================================

def scan_period(targets, period):
    """1期間分のスキャン。年間の場合は生投稿も返す。"""
    results = []
    raw_posts = {}  # city_en -> [posts]（ヒストリカル用）

    for i, (name, info) in enumerate(targets.items()):
        print(f"   [{i+1}/{len(targets)}] {info['ja']}...", end=" ", flush=True)

        posts = fetch_city_posts(info["q"], period)
        mentions = summarize_posts(posts)
        gap = check_supply_gap(info["q"], period)
        score = calc_gem_score(mentions, gap, period)

        print(f"📝{mentions['post_count']} ↑{mentions['avg_score']} 🏨{gap} → GEM:{score}")

        if period == "year":
            raw_posts[name] = posts

        results.append({
            "period": period, "rank": 0,
            "city_en": name, "city_ja": info["ja"],
            "region": info["region"], "category": info["cat"],
            "post_count": mentions["post_count"],
            "total_score": mentions["total_score"],
            "avg_score": mentions["avg_score"],
            "avg_comments": mentions["avg_comments"],
            "supply_gap": gap, "gem_score": score,
            "top_post_url": mentions["top_posts"][0]["url"] if mentions["top_posts"] else "",
            "top_post_title": mentions["top_posts"][0]["title"][:80] if mentions["top_posts"] else "",
            "scan_date": datetime.now().strftime("%Y-%m-%d"),
        })

    results.sort(key=lambda x: x["gem_score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results, raw_posts


# ============================================================
# レポート表示
# ============================================================

def print_ranking(results, label):
    cats = {"候補A":"🏆 候補A","候補B":"📊 候補B","運営中":"🏠 運営中","Watch":"👀 Watch","BM":"📈 BM"}
    print(f"\n{'='*60}\n📊 {label}\n{'='*60}")
    for cat, clabel in cats.items():
        cr = sorted([r for r in results if r["category"]==cat], key=lambda x: x["gem_score"], reverse=True)
        if not cr: continue
        print(f"\n {'─'*46}\n {clabel}\n {'─'*46}")
        for r in cr:
            bar = "█"*(r["gem_score"]//5) + "░"*(20-r["gem_score"]//5)
            gf = " ⚠️" if r["supply_gap"]>=(2 if r["period"]=="month" else 5) else ""
            print(f"\n  #{r['rank']} {r['city_ja']}（{r['city_en']}）— {r['region']}")
            print(f"     [{bar}] {r['gem_score']}/100")
            print(f"     📝{r['post_count']} | ↑{r['avg_score']} | 💬{r['avg_comments']} | 🏨{r['supply_gap']}{gf}")


def print_cross_analysis(month_results, year_results):
    print(f"\n{'='*60}\n🔥 クロス分析\n{'='*60}")
    m_map = {r["city_en"]: r for r in month_results}
    y_map = {r["city_en"]: r for r in year_results}
    analysis = []
    for city_en in m_map:
        m, y = m_map[city_en], y_map.get(city_en)
        if not y: continue
        expected = y["post_count"] / 12
        actual = m["post_count"]
        accel = (actual/expected) if expected > 0 else (99.0 if actual > 0 else 0.0)
        analysis.append({
            "city_en": city_en, "city_ja": m["city_ja"], "category": m["category"],
            "month_posts": actual, "year_posts": y["post_count"],
            "expected_monthly": round(expected, 1), "acceleration": round(accel, 2),
            "month_gem": m["gem_score"], "year_gem": y["gem_score"],
            "gem_diff": m["gem_score"] - y["gem_score"],
            "month_gap": m["supply_gap"], "year_gap": y["supply_gap"],
        })
    analysis.sort(key=lambda x: x["acceleration"], reverse=True)

    print(f"\n  {'都市':<8} {'月次':>4} {'年月平均':>7} {'加速度':>6} {'月GEM':>5} {'年GEM':>5} {'宿不満':>5}")
    print(f"  {'─'*50}")
    for a in analysis[:15]:
        ic = "🔥" if a["acceleration"]>=2.0 else "📈" if a["acceleration"]>=1.3 else "→ " if a["acceleration"]>=0.7 else "📉"
        gf = "⚠️" if a["month_gap"]>=2 else "  "
        print(f"  {a['city_ja']:<7} {a['month_posts']:>4} {a['expected_monthly']:>6} {ic}{a['acceleration']:>5.1f}x {a['month_gem']:>5} {a['year_gem']:>5} {a['month_gap']:>3}{gf}")

    hot = [a for a in analysis if a["acceleration"]>=1.5 and a["month_gap"]>=1]
    if hot:
        print(f"\n  🚨 要注目（加速1.5x↑+宿不満あり）:")
        for a in hot:
            print(f"     {a['city_ja']}：{a['month_posts']}件（年平均{a['expected_monthly']}の{a['acceleration']}倍）宿不満{a['month_gap']}件")
    return analysis


# ============================================================
# ファイル出力
# ============================================================

def save_all(month_res, year_res, cross, history_rows):
    os.makedirs("output", exist_ok=True)
    ds = datetime.now().strftime("%Y%m%d")

    for label, data in [("month", month_res), ("year", year_res)]:
        if data:
            p = f"output/gem_{label}_{ds}.csv"
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=data[0].keys())
                w.writeheader(); w.writerows(data)
            print(f"📁 {label}: {p}")

    combined = (month_res or []) + (year_res or [])
    if combined:
        p = f"output/gem_combined_{ds}.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        print(f"📁 統合JSON: {p}")

    if cross:
        p = f"output/gem_cross_{ds}.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cross, f, ensure_ascii=False, indent=2)
        print(f"📁 クロス: {p}")

    # ★ ヒストリカル出力
    if history_rows:
        p = f"output/gem_history_{ds}.csv"
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=history_rows[0].keys())
            w.writeheader(); w.writerows(history_rows)
        print(f"📁 ヒストリカル: {p}")

        # JSON版（ビジュアル連携用）
        p2 = f"output/gem_history_{ds}.json"
        with open(p2, "w", encoding="utf-8") as f:
            json.dump(history_rows, f, ensure_ascii=False, indent=2)
        print(f"📁 ヒストリカルJSON: {p2}")

    # 前月比較
    prev = sorted([f for f in os.listdir("output")
                   if f.startswith("gem_month_") and f.endswith(".csv")
                   and f != f"gem_month_{ds}.csv"])
    if prev and month_res:
        try:
            prev_map = {}
            with open(f"output/{prev[-1]}", "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f): prev_map[row["city_en"]] = row
            print(f"\n{'─'*46}\n 📈 前月比 (vs {prev[-1]})\n{'─'*46}")
            for r in month_res:
                pr = prev_map.get(r["city_en"])
                if pr:
                    dp = r["post_count"] - int(pr["post_count"])
                    dg = r["gem_score"] - int(pr["gem_score"])
                    if abs(dp) >= 2 or abs(dg) >= 5:
                        print(f"  {r['city_ja']}: 投稿{'📈' if dp>0 else '📉'}{dp:+d} / GEM{'⬆️' if dg>0 else '⬇️'}{dg:+d}")
        except Exception as e:
            print(f"  ⚠️ {e}")


# ============================================================
# メイン
# ============================================================

def main():
    filter_cities = None
    if "--cities" in sys.argv:
        idx = sys.argv.index("--cities")
        if idx + 1 < len(sys.argv):
            filter_cities = [c.strip().lower() for c in sys.argv[idx + 1].split(",")]

    run_periods = PERIODS
    if "--period" in sys.argv:
        idx = sys.argv.index("--period")
        if idx + 1 < len(sys.argv):
            p = sys.argv[idx + 1].strip().lower()
            if p in ("month", "year"): run_periods = [p]

    targets = TARGETS
    if filter_cities:
        targets = {k: v for k, v in TARGETS.items()
                   if k.lower() in filter_cities or v["ja"] in filter_cities}

    reqs = len(targets) * 6 * len(run_periods)

    print("=" * 60)
    print("🏯 Reddit Japan Travel Monitor v3")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"🔍 {len(targets)}都市 × {len(run_periods)}期間")
    print(f"⏱  約{reqs * REQUEST_DELAY / 60:.0f}分")
    print("=" * 60)

    month_res, year_res = None, None
    year_raw_posts = {}

    for period in run_periods:
        tag = "過去1ヶ月" if period == "month" else "過去1年"
        print(f"\n{'━'*60}\n 📅 {tag}\n{'━'*60}")
        results, raw = scan_period(targets, period)
        if period == "month":
            month_res = results
            print_ranking(results, "月次 HIDDEN GEM")
        else:
            year_res = results
            year_raw_posts = raw
            print_ranking(results, "年間 HIDDEN GEM")

    # クロス分析
    cross = None
    if month_res and year_res:
        cross = print_cross_analysis(month_res, year_res)

    # ★ ヒストリカル分析
    history_rows = []
    if year_raw_posts:
        history_rows, months = build_monthly_history(year_raw_posts, targets)
        print_history(history_rows, months, targets)

    # 出力
    save_all(month_res, year_res, cross, history_rows)

    print(f"\n{'='*60}\n✅ 完了！\n{'='*60}")
    print("\n💡 活用法:")
    print("  • gem_history_*.csv → 過去12ヶ月の月別投稿数推移")
    print("  • 後半6ヶ月で加速🔥の都市 → 今まさにトレンド入り")
    print("  • Claude Code: claude 'gem_history CSVを読んでチャートにして'")


if __name__ == "__main__":
    main()
