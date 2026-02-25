#!/usr/bin/env python3
"""FitBites Analytics CLI — production data pipeline tool.

Usage:
  python scripts/analytics_cli.py seed          # Seed 30 days of test data
  python scripts/analytics_cli.py dashboard     # Generate static dashboard
  python scripts/analytics_cli.py report        # Print KPI report to stdout
  python scripts/analytics_cli.py export        # Export metrics JSON
  python scripts/analytics_cli.py full          # Seed + dashboard + report
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def cmd_seed():
    from scripts.seed_analytics import seed
    await seed()
    from scripts.seed_recipes import seed as seed_recipes
    await seed_recipes()


async def cmd_dashboard():
    from scripts.generate_dashboard import main
    await main()


async def cmd_report():
    from scripts.generate_dashboard import gather_metrics
    m = await gather_metrics()
    
    print("=" * 60)
    print("  FitBites Analytics Report")
    print("=" * 60)
    print()
    print(f"  📊 Users")
    print(f"     DAU: {m['dau']:>8,}    WAU: {m['wau']:>8,}    MAU: {m['mau']:>8,}")
    print(f"     Views/User: {m['views_per_user']}")
    print(f"     Retention (W1→W2): {m['retention']['rate']}%")
    print()
    print(f"  💰 Revenue")
    print(f"     Est. Revenue (30d): ${m['total_revenue_est']:>10.2f}")
    print(f"     ARPU: ${m['arpu']:.4f}/user/month")
    print(f"     LTV (12mo, 40% retention): ${m['arpu'] * 12 * 0.4:.2f}")
    print()
    print(f"  🔗 Affiliate Performance")
    print(f"     CTR: {m['affiliate_ctr']}%  |  Convert: {m['click_to_convert']}%")
    print(f"     Total Clicks: {m['total_clicks']:,}  |  Conversions: {m['total_conversions']:,}")
    print()
    print(f"  📊 Funnel")
    funnel = m["funnel"]
    max_val = max(funnel.values()) if funnel else 1
    for stage, count in funnel.items():
        bar_len = int(count / max_val * 30)
        print(f"     {stage:<25} {'█' * bar_len} {count:,}")
    print()
    print(f"  📱 Platforms")
    for p in m["platforms"]:
        print(f"     {p['platform']:<12} {p['users']:>6,} users  ({p['events']:>6,} events)")
    print()
    print(f"  🏆 Top 5 Recipes")
    for i, r in enumerate(m["top_recipes"][:5], 1):
        print(f"     {i}. {r['title']:<40} {r['views']:>6,} views")
    print()
    print(f"  💎 Revenue by Partner")
    for partner, rev in sorted(m["revenue_by_partner"].items(), key=lambda x: -x[1]):
        print(f"     {partner:<15} ${rev:>8.2f}")
    print()
    print("=" * 60)


async def cmd_export():
    from scripts.generate_dashboard import gather_metrics
    import json
    m = await gather_metrics()
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "metrics.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(m, f, indent=2, default=str)
    print(f"✅ Exported to {out}")


async def cmd_full():
    await cmd_seed()
    await cmd_dashboard()
    await cmd_report()


COMMANDS = {
    "seed": cmd_seed,
    "dashboard": cmd_dashboard,
    "report": cmd_report,
    "export": cmd_export,
    "full": cmd_full,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    asyncio.run(COMMANDS[sys.argv[1]]())


if __name__ == "__main__":
    main()
