#!/usr/bin/env python3
"""Generate a production-grade FitBites analytics dashboard as static HTML.

Queries the SQLite analytics database directly and produces:
1. Real-time KPI cards (DAU, MAU, retention, revenue)
2. User growth chart (30-day trend)
3. Recipe-to-revenue funnel
4. Platform breakdown
5. Top recipes by engagement
6. Affiliate revenue by partner
7. API performance metrics
8. Cohort retention analysis

Outputs: static/dashboard.html (self-contained, no external deps except Chart.js CDN)
"""
import asyncio
import json
import sys
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from src.db.engine import async_session

# Commission rates for revenue estimation
COMMISSION_RATES = {
    "amazon": 0.02, "iherb": 0.05, "instacart": 5.0,  # CPA
    "thrive": 5.0, "hellofresh": 10.0,  # CPA
}
AVG_ORDER = {"amazon": 35, "iherb": 42, "instacart": 65}
CPA_PROVIDERS = {"instacart", "thrive", "hellofresh"}


async def query(sql: str, params: dict = None):
    async with async_session() as session:
        result = await session.execute(text(sql), params or {})
        return result.all()


async def gather_metrics():
    now = datetime.now(timezone.utc)
    d30 = (now - timedelta(days=30)).isoformat()
    d7 = (now - timedelta(days=7)).isoformat()
    d1 = (now - timedelta(days=1)).isoformat()

    metrics = {}

    # 1. KPIs
    metrics["dau"] = (await query(
        "SELECT COUNT(DISTINCT user_id) FROM analytics_events WHERE timestamp >= :since AND user_id IS NOT NULL",
        {"since": d1}))[0][0]
    
    metrics["wau"] = (await query(
        "SELECT COUNT(DISTINCT user_id) FROM analytics_events WHERE timestamp >= :since AND user_id IS NOT NULL",
        {"since": d7}))[0][0]
    
    metrics["mau"] = (await query(
        "SELECT COUNT(DISTINCT user_id) FROM analytics_events WHERE timestamp >= :since AND user_id IS NOT NULL",
        {"since": d30}))[0][0]

    metrics["total_events_30d"] = (await query(
        "SELECT COUNT(*) FROM analytics_events WHERE timestamp >= :since", {"since": d30}))[0][0]

    # 2. Daily Active Users trend (30 days)
    dau_rows = await query("""
        SELECT DATE(timestamp) as day, COUNT(DISTINCT user_id) as users
        FROM analytics_events
        WHERE timestamp >= :since AND user_id IS NOT NULL
        GROUP BY day ORDER BY day
    """, {"since": d30})
    metrics["dau_trend"] = [{"date": str(r[0]), "users": r[1]} for r in dau_rows]

    # 3. Event counts by type (30d)
    event_counts = await query("""
        SELECT event, COUNT(*) as cnt
        FROM analytics_events WHERE timestamp >= :since
        GROUP BY event ORDER BY cnt DESC
    """, {"since": d30})
    metrics["event_counts"] = {r[0]: r[1] for r in event_counts}

    # 4. Funnel
    funnel_events = ["app_open", "recipe_view", "recipe_save", "affiliate_click", "grocery_list_generated", "affiliate_conversion"]
    funnel = {}
    for ev in funnel_events:
        cnt = (await query(
            "SELECT COUNT(*) FROM analytics_events WHERE event = :ev AND timestamp >= :since",
            {"ev": ev, "since": d30}))[0][0]
        funnel[ev] = cnt
    metrics["funnel"] = funnel

    # 5. Platform breakdown
    platforms = await query("""
        SELECT platform, COUNT(DISTINCT user_id) as users, COUNT(*) as events
        FROM analytics_events
        WHERE timestamp >= :since AND platform IS NOT NULL
        GROUP BY platform ORDER BY users DESC
    """, {"since": d30})
    metrics["platforms"] = [{"platform": r[0], "users": r[1], "events": r[2]} for r in platforms]

    # 6. Top recipes by views
    top_recipes = await query("""
        SELECT json_extract(properties, '$.recipe_id') as recipe_id,
               json_extract(properties, '$.recipe_title') as title,
               COUNT(*) as views
        FROM analytics_events
        WHERE event = 'recipe_view' AND timestamp >= :since
        GROUP BY recipe_id ORDER BY views DESC LIMIT 10
    """, {"since": d30})
    metrics["top_recipes"] = [{"id": r[0], "title": r[1], "views": r[2]} for r in top_recipes]

    # 7. Affiliate clicks by provider
    aff_clicks = await query("""
        SELECT json_extract(properties, '$.provider') as provider, COUNT(*) as clicks
        FROM analytics_events
        WHERE event = 'affiliate_click' AND timestamp >= :since
        GROUP BY provider ORDER BY clicks DESC
    """, {"since": d30})
    metrics["affiliate_clicks"] = [{"provider": r[0], "clicks": r[1]} for r in aff_clicks]

    # 8. Affiliate conversions & revenue estimate
    aff_conv = await query("""
        SELECT json_extract(properties, '$.provider') as provider,
               COUNT(*) as conversions,
               COALESCE(SUM(json_extract(properties, '$.order_value')), 0) as order_value
        FROM analytics_events
        WHERE event = 'affiliate_conversion' AND timestamp >= :since
        GROUP BY provider ORDER BY conversions DESC
    """, {"since": d30})
    
    revenue_by_partner = {}
    total_revenue = 0
    for r in aff_conv:
        provider = r[0] or "amazon"
        conversions = r[1]
        order_val = r[2] or 0
        if provider in CPA_PROVIDERS:
            rev = conversions * COMMISSION_RATES.get(provider, 5.0)
        elif order_val > 0:
            rev = order_val * COMMISSION_RATES.get(provider, 0.02)
        else:
            aov = AVG_ORDER.get(provider, 35)
            rev = conversions * aov * COMMISSION_RATES.get(provider, 0.02)
        revenue_by_partner[provider] = round(rev, 2)
        total_revenue += rev
    
    metrics["revenue_by_partner"] = revenue_by_partner
    metrics["total_revenue_est"] = round(total_revenue, 2)
    metrics["total_conversions"] = sum(r[1] for r in aff_conv)
    metrics["total_clicks"] = sum(r[1] for r in aff_clicks)

    # 9. Daily events trend
    daily_events = await query("""
        SELECT DATE(timestamp) as day, event, COUNT(*) as cnt
        FROM analytics_events
        WHERE timestamp >= :since
        GROUP BY day, event ORDER BY day
    """, {"since": d30})
    
    daily_map = defaultdict(lambda: defaultdict(int))
    for r in daily_events:
        daily_map[str(r[0])][r[1]] = r[2]
    metrics["daily_events"] = dict(daily_map)

    # 10. Hourly activity pattern
    hourly = await query("""
        SELECT CAST(strftime('%H', timestamp) AS INTEGER) as hour, COUNT(*) as cnt
        FROM analytics_events WHERE timestamp >= :since
        GROUP BY hour ORDER BY hour
    """, {"since": d30})
    metrics["hourly_pattern"] = [{"hour": r[0], "events": r[1]} for r in hourly]

    # 11. Top ingredients clicked
    top_ingredients = await query("""
        SELECT json_extract(properties, '$.ingredient') as ingredient, COUNT(*) as clicks
        FROM analytics_events
        WHERE event = 'affiliate_click' AND timestamp >= :since
        GROUP BY ingredient ORDER BY clicks DESC LIMIT 10
    """, {"since": d30})
    metrics["top_ingredients"] = [{"ingredient": r[0], "clicks": r[1]} for r in top_ingredients]

    # 12. App version distribution
    versions = await query("""
        SELECT app_version, COUNT(DISTINCT user_id) as users
        FROM analytics_events
        WHERE timestamp >= :since AND app_version IS NOT NULL
        GROUP BY app_version ORDER BY users DESC
    """, {"since": d30})
    metrics["app_versions"] = [{"version": r[0], "users": r[1]} for r in versions]

    # 13. Retention: users who were active in week 1 AND week 2+
    w1_start = (now - timedelta(days=30)).isoformat()
    w1_end = (now - timedelta(days=23)).isoformat()
    w2_start = (now - timedelta(days=23)).isoformat()
    w2_end = (now - timedelta(days=16)).isoformat()
    
    w1_users = (await query("""
        SELECT COUNT(DISTINCT user_id) FROM analytics_events
        WHERE timestamp >= :s AND timestamp < :e AND user_id IS NOT NULL
    """, {"s": w1_start, "e": w1_end}))[0][0]
    
    retained = (await query("""
        SELECT COUNT(DISTINCT a.user_id) FROM analytics_events a
        INNER JOIN (
            SELECT DISTINCT user_id FROM analytics_events
            WHERE timestamp >= :w1s AND timestamp < :w1e AND user_id IS NOT NULL
        ) b ON a.user_id = b.user_id
        WHERE a.timestamp >= :w2s AND a.timestamp < :w2e
    """, {"w1s": w1_start, "w1e": w1_end, "w2s": w2_start, "w2e": w2_end}))[0][0]

    metrics["retention"] = {
        "week1_users": w1_users,
        "week2_retained": retained,
        "rate": round(retained / max(w1_users, 1) * 100, 1),
    }

    # Computed KPIs
    mau = max(metrics["mau"], 1)
    # Users who clicked at least one affiliate link
    clickers = (await query(
        "SELECT COUNT(DISTINCT user_id) FROM analytics_events WHERE event='affiliate_click' AND timestamp >= :since AND user_id IS NOT NULL",
        {"since": d30}))[0][0]
    
    metrics["arpu"] = round(total_revenue / mau, 4)
    metrics["affiliate_ctr"] = round(clickers / mau * 100, 2)  # % of users who click
    metrics["click_to_convert"] = round(metrics["total_conversions"] / max(metrics["total_clicks"], 1) * 100, 2)
    metrics["views_per_user"] = round(metrics["event_counts"].get("recipe_view", 0) / mau, 1)
    metrics["clickers"] = clickers

    return metrics


def generate_html(metrics: dict) -> str:
    m = metrics
    funnel = m["funnel"]
    
    # Funnel conversion rates
    funnel_rates = {}
    prev_key = None
    for key in ["app_open", "recipe_view", "recipe_save", "affiliate_click", "affiliate_conversion"]:
        if prev_key and funnel.get(prev_key, 0) > 0:
            funnel_rates[f"{prev_key}→{key}"] = round(funnel[key] / funnel[prev_key] * 100, 1)
        prev_key = key

    # Health score
    score_parts = []
    score_parts.append(min(25, int(m["views_per_user"] / 5 * 25)))
    score_parts.append(min(25, int(m["affiliate_ctr"] / 15 * 25)))
    score_parts.append(min(25, int(m["click_to_convert"] / 3 * 25)))
    score_parts.append(min(25, int(min(m["mau"] / 1000, 1) * 25)))
    health_score = sum(score_parts)
    
    if health_score >= 90: grade = "A"
    elif health_score >= 75: grade = "B"
    elif health_score >= 60: grade = "C"
    elif health_score >= 40: grade = "D"
    else: grade = "F"

    dau_labels = json.dumps([d["date"][-5:] for d in m["dau_trend"]])
    dau_data = json.dumps([d["users"] for d in m["dau_trend"]])
    
    # Daily revenue trend from daily_events
    dates = sorted(m["daily_events"].keys())
    daily_clicks = json.dumps([m["daily_events"][d].get("affiliate_click", 0) for d in dates])
    daily_views = json.dumps([m["daily_events"][d].get("recipe_view", 0) for d in dates])
    daily_opens = json.dumps([m["daily_events"][d].get("app_open", 0) for d in dates])
    date_labels = json.dumps([d[-5:] for d in dates])

    hourly_labels = json.dumps([f"{h['hour']:02d}:00" for h in m["hourly_pattern"]])
    hourly_data = json.dumps([h["events"] for h in m["hourly_pattern"]])

    platform_labels = json.dumps([p["platform"] or "unknown" for p in m["platforms"]])
    platform_data = json.dumps([p["users"] for p in m["platforms"]])
    platform_colors = json.dumps(["#007AFF", "#34C759", "#FF9500"][:len(m["platforms"])])

    aff_labels = json.dumps([a["provider"] or "unknown" for a in m["affiliate_clicks"]])
    aff_data = json.dumps([a["clicks"] for a in m["affiliate_clicks"]])

    top_recipe_labels = json.dumps([r["title"][:30] for r in m["top_recipes"][:8]])
    top_recipe_data = json.dumps([r["views"] for r in m["top_recipes"][:8]])

    ing_labels = json.dumps([i["ingredient"] for i in m["top_ingredients"][:8]])
    ing_data = json.dumps([i["clicks"] for i in m["top_ingredients"][:8]])

    rev_labels = json.dumps(list(m["revenue_by_partner"].keys()))
    rev_data = json.dumps(list(m["revenue_by_partner"].values()))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M EST")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FitBites Analytics Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0a0a0f; --surface: #141419; --surface2: #1c1c24;
    --border: #2a2a35; --text: #e4e4e7; --text-muted: #71717a;
    --accent: #007AFF; --green: #34C759; --red: #FF3B30;
    --yellow: #FFD60A; --orange: #FF9500; --purple: #AF52DE;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
    padding: 24px; max-width: 1400px; margin: 0 auto;
  }}
  .header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 32px; padding-bottom: 16px; border-bottom: 1px solid var(--border);
  }}
  .header h1 {{ font-size: 28px; font-weight: 700; }}
  .header h1 span {{ color: var(--accent); }}
  .header .meta {{ color: var(--text-muted); font-size: 13px; }}
  .health-badge {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 16px; border-radius: 20px; font-weight: 600; font-size: 14px;
  }}
  .health-A, .health-B {{ background: rgba(52,199,89,0.15); color: var(--green); }}
  .health-C {{ background: rgba(255,214,10,0.15); color: var(--yellow); }}
  .health-D, .health-F {{ background: rgba(255,59,48,0.15); color: var(--red); }}

  .kpi-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px; margin-bottom: 32px;
  }}
  .kpi {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px;
  }}
  .kpi .label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi .value {{ font-size: 32px; font-weight: 700; margin: 4px 0; }}
  .kpi .sub {{ font-size: 12px; color: var(--text-muted); }}
  .kpi.green .value {{ color: var(--green); }}
  .kpi.yellow .value {{ color: var(--yellow); }}
  .kpi.red .value {{ color: var(--red); }}

  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; margin-bottom: 24px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px;
  }}
  .card h3 {{ font-size: 16px; margin-bottom: 16px; font-weight: 600; }}
  .card canvas {{ max-height: 300px; }}

  .funnel {{ margin-bottom: 32px; }}
  .funnel-bar {{
    display: flex; align-items: center; gap: 12px; padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }}
  .funnel-bar .fname {{ width: 200px; font-size: 14px; font-weight: 500; }}
  .funnel-bar .fbar {{
    flex: 1; height: 32px; border-radius: 6px; position: relative;
    background: var(--surface2); overflow: hidden;
  }}
  .funnel-bar .fbar-fill {{
    height: 100%; border-radius: 6px; transition: width 0.6s ease;
    display: flex; align-items: center; padding-left: 12px;
    font-size: 13px; font-weight: 600; color: white;
  }}
  .funnel-bar .frate {{ width: 80px; text-align: right; font-size: 13px; color: var(--text-muted); }}

  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align: left; padding: 10px 12px; color: var(--text-muted); font-weight: 500;
       font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
       border-bottom: 1px solid var(--border); }}
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); }}
  tr:hover td {{ background: var(--surface2); }}

  .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
  .badge-green {{ background: rgba(52,199,89,0.15); color: var(--green); }}
  .badge-yellow {{ background: rgba(255,214,10,0.15); color: var(--yellow); }}
  .badge-red {{ background: rgba(255,59,48,0.15); color: var(--red); }}

  .section-title {{
    font-size: 20px; font-weight: 700; margin: 32px 0 16px;
    padding-top: 16px; border-top: 1px solid var(--border);
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>🍽️ <span>FitBites</span> Analytics</h1>
    <div class="meta">Last updated: {now_str} · 30-day window · {m['total_events_30d']:,} events tracked</div>
  </div>
  <div>
    <span class="health-badge health-{grade}">
      Health: {health_score}/100 ({grade})
    </span>
  </div>
</div>

<!-- KPI Cards -->
<div class="kpi-grid">
  <div class="kpi">
    <div class="label">Daily Active Users</div>
    <div class="value">{m['dau']:,}</div>
    <div class="sub">Last 24 hours</div>
  </div>
  <div class="kpi">
    <div class="label">Weekly Active Users</div>
    <div class="value">{m['wau']:,}</div>
    <div class="sub">Last 7 days</div>
  </div>
  <div class="kpi">
    <div class="label">Monthly Active Users</div>
    <div class="value">{m['mau']:,}</div>
    <div class="sub">Last 30 days</div>
  </div>
  <div class="kpi {'green' if m['views_per_user'] >= 5 else 'yellow' if m['views_per_user'] >= 3 else 'red'}">
    <div class="label">Views / User</div>
    <div class="value">{m['views_per_user']}</div>
    <div class="sub">Target: 5.0</div>
  </div>
  <div class="kpi {'green' if m['affiliate_ctr'] >= 15 else 'yellow' if m['affiliate_ctr'] >= 8 else 'red'}">
    <div class="label">Affiliate CTR</div>
    <div class="value">{m['affiliate_ctr']}%</div>
    <div class="sub">Target: 15%</div>
  </div>
  <div class="kpi {'green' if m['click_to_convert'] >= 3 else 'yellow' if m['click_to_convert'] >= 1.5 else 'red'}">
    <div class="label">Click → Convert</div>
    <div class="value">{m['click_to_convert']}%</div>
    <div class="sub">Target: 3%</div>
  </div>
  <div class="kpi">
    <div class="label">Est. Revenue (30d)</div>
    <div class="value">${m['total_revenue_est']:.2f}</div>
    <div class="sub">ARPU: ${m['arpu']:.4f}/user</div>
  </div>
  <div class="kpi {'green' if m['retention']['rate'] >= 25 else 'yellow' if m['retention']['rate'] >= 15 else 'red'}">
    <div class="label">Week 1→2 Retention</div>
    <div class="value">{m['retention']['rate']}%</div>
    <div class="sub">{m['retention']['week2_retained']}/{m['retention']['week1_users']} users</div>
  </div>
</div>

<!-- Funnel -->
<h2 class="section-title">📊 Recipe-to-Revenue Funnel</h2>
<div class="funnel card">
{''.join(f'''
  <div class="funnel-bar">
    <div class="fname">{ev.replace('_', ' ').title()}</div>
    <div class="fbar">
      <div class="fbar-fill" style="width: {max(funnel[ev] / max(funnel['app_open'], 1) * 100, 2):.1f}%; background: linear-gradient(90deg, var(--accent), var(--purple));">
        {funnel[ev]:,}
      </div>
    </div>
    <div class="frate">{funnel_rates.get(list(funnel_rates.keys())[i-1], '') if i > 0 and i-1 < len(funnel_rates) else ''}{'%' if i > 0 and i-1 < len(funnel_rates) else ''}</div>
  </div>''' for i, ev in enumerate(["app_open", "recipe_view", "recipe_save", "affiliate_click", "affiliate_conversion"]))}
</div>

<!-- Charts Row 1 -->
<div class="grid">
  <div class="card">
    <h3>📈 Daily Active Users (30d)</h3>
    <canvas id="dauChart"></canvas>
  </div>
  <div class="card">
    <h3>📱 Platform Distribution</h3>
    <canvas id="platformChart"></canvas>
  </div>
</div>

<!-- Charts Row 2 -->
<div class="grid">
  <div class="card">
    <h3>🔥 Daily Events Breakdown</h3>
    <canvas id="eventsChart"></canvas>
  </div>
  <div class="card">
    <h3>⏰ Activity by Hour</h3>
    <canvas id="hourlyChart"></canvas>
  </div>
</div>

<!-- Charts Row 3 -->
<div class="grid">
  <div class="card">
    <h3>🏆 Top Recipes by Views</h3>
    <canvas id="recipesChart"></canvas>
  </div>
  <div class="card">
    <h3>💰 Revenue by Partner</h3>
    <canvas id="revenueChart"></canvas>
  </div>
</div>

<!-- Charts Row 4 -->
<div class="grid">
  <div class="card">
    <h3>🛒 Top Ingredients (Affiliate Clicks)</h3>
    <canvas id="ingredientsChart"></canvas>
  </div>
  <div class="card">
    <h3>🔗 Affiliate Clicks by Provider</h3>
    <canvas id="affChart"></canvas>
  </div>
</div>

<!-- Tables -->
<h2 class="section-title">📋 Detailed Breakdown</h2>
<div class="grid">
  <div class="card">
    <h3>Event Counts (30d)</h3>
    <div class="table-wrap">
      <table>
        <tr><th>Event</th><th>Count</th><th>Share</th></tr>
        {''.join(f"<tr><td>{ev}</td><td>{cnt:,}</td><td>{cnt/m['total_events_30d']*100:.1f}%</td></tr>" for ev, cnt in sorted(m['event_counts'].items(), key=lambda x: -x[1]))}
      </table>
    </div>
  </div>
  <div class="card">
    <h3>App Version Distribution</h3>
    <div class="table-wrap">
      <table>
        <tr><th>Version</th><th>Users</th></tr>
        {''.join(f"<tr><td>{v['version']}</td><td>{v['users']:,}</td></tr>" for v in m['app_versions'])}
      </table>
    </div>
  </div>
</div>

<script>
const chartDefaults = {{
  color: '#71717a',
  borderColor: '#2a2a35',
  font: {{ family: '-apple-system, system-ui, sans-serif' }},
}};
Chart.defaults.color = '#71717a';
Chart.defaults.borderColor = '#2a2a35';

// DAU Chart
new Chart(document.getElementById('dauChart'), {{
  type: 'line',
  data: {{
    labels: {dau_labels},
    datasets: [{{
      label: 'DAU',
      data: {dau_data},
      borderColor: '#007AFF',
      backgroundColor: 'rgba(0,122,255,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ y: {{ beginAtZero: true }} }},
  }}
}});

// Platform Chart (Doughnut)
new Chart(document.getElementById('platformChart'), {{
  type: 'doughnut',
  data: {{
    labels: {platform_labels},
    datasets: [{{
      data: {platform_data},
      backgroundColor: {platform_colors},
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    cutout: '65%',
    plugins: {{
      legend: {{ position: 'bottom' }},
    }},
  }}
}});

// Daily Events Stacked
new Chart(document.getElementById('eventsChart'), {{
  type: 'bar',
  data: {{
    labels: {date_labels},
    datasets: [
      {{ label: 'Opens', data: {daily_opens}, backgroundColor: '#007AFF', stack: 'a' }},
      {{ label: 'Views', data: {daily_views}, backgroundColor: '#34C759', stack: 'a' }},
      {{ label: 'Clicks', data: {daily_clicks}, backgroundColor: '#FF9500', stack: 'a' }},
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ stacked: true }},
      y: {{ stacked: true, beginAtZero: true }},
    }},
    plugins: {{ legend: {{ position: 'bottom' }} }},
  }}
}});

// Hourly
new Chart(document.getElementById('hourlyChart'), {{
  type: 'bar',
  data: {{
    labels: {hourly_labels},
    datasets: [{{
      label: 'Events',
      data: {hourly_data},
      backgroundColor: 'rgba(175,82,222,0.6)',
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ y: {{ beginAtZero: true }} }},
  }}
}});

// Top Recipes
new Chart(document.getElementById('recipesChart'), {{
  type: 'bar',
  data: {{
    labels: {top_recipe_labels},
    datasets: [{{
      label: 'Views',
      data: {top_recipe_data},
      backgroundColor: 'rgba(52,199,89,0.7)',
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
  }}
}});

// Revenue by Partner
new Chart(document.getElementById('revenueChart'), {{
  type: 'doughnut',
  data: {{
    labels: {rev_labels},
    datasets: [{{
      data: {rev_data},
      backgroundColor: ['#007AFF', '#34C759', '#FF9500', '#AF52DE', '#FF3B30'],
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    cutout: '65%',
    plugins: {{ legend: {{ position: 'bottom' }} }},
  }}
}});

// Top Ingredients
new Chart(document.getElementById('ingredientsChart'), {{
  type: 'bar',
  data: {{
    labels: {ing_labels},
    datasets: [{{
      label: 'Clicks',
      data: {ing_data},
      backgroundColor: 'rgba(255,149,0,0.7)',
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
  }}
}});

// Affiliate Clicks
new Chart(document.getElementById('affChart'), {{
  type: 'bar',
  data: {{
    labels: {aff_labels},
    datasets: [{{
      label: 'Clicks',
      data: {aff_data},
      backgroundColor: ['#007AFF', '#34C759', '#FF9500', '#AF52DE', '#FF3B30'],
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ y: {{ beginAtZero: true }} }},
  }}
}});
</script>
</body>
</html>"""


async def main():
    print("Gathering metrics from database...")
    metrics = await gather_metrics()
    
    print(f"\n📊 Key Metrics:")
    print(f"  DAU: {metrics['dau']:,}  |  WAU: {metrics['wau']:,}  |  MAU: {metrics['mau']:,}")
    print(f"  Views/User: {metrics['views_per_user']}  |  Affiliate CTR: {metrics['affiliate_ctr']}%")
    print(f"  Conversions: {metrics['total_conversions']}  |  Est Revenue: ${metrics['total_revenue_est']:.2f}")
    print(f"  Retention (W1→W2): {metrics['retention']['rate']}%")
    
    html = generate_html(metrics)
    
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dashboard.html")
    
    with open(out_path, "w") as f:
        f.write(html)
    
    print(f"\n✅ Dashboard generated: {out_path}")
    print(f"   Size: {len(html):,} bytes")
    
    # Also save metrics JSON for API consumption
    json_path = os.path.join(out_dir, "metrics.json")
    # Convert non-serializable types
    serializable = {k: v for k, v in metrics.items()}
    with open(json_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"   Metrics JSON: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
