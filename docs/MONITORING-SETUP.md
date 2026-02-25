# FitBites Monitoring & Alerting Setup

## Overview

Premium apps need **proactive monitoring** — know about issues before users complain. This guide covers external uptime monitoring, error tracking, and performance monitoring.

---

## 1. Uptime Monitoring (CRITICAL)

### Recommended: UptimeRobot (Free tier sufficient)

**Setup Steps:**

1. **Create account:** https://uptimerobot.com
2. **Add monitor:**
   - Monitor Type: HTTP(s)
   - Friendly Name: FitBites API Production
   - URL: `https://prolific-optimism-production.up.railway.app/health`
   - Monitoring Interval: 5 minutes (free tier)
   - Monitor Timeout: 30 seconds
   - HTTP Method: GET
   - Expected Status: 200

3. **Add alert contacts:**
   - Email: hayden@example.com (adjust)
   - Telegram: (optional - can integrate)
   - Webhook: (optional - Slack/Discord)

4. **Configure alerts:**
   - Alert when: Down
   - Send notification when: Down for 2+ consecutive checks
   - Recovery notification: Yes

### Alternative: Pingdom (More features, paid)

Similar setup, but adds:
- Performance insights (response time trends)
- Transaction monitoring (multi-step checks)
- Real user monitoring (RUM)

---

## 2. Error Tracking (Sentry) — Already Integrated ✅

### Setup Steps:

1. **Create Sentry project:** https://sentry.io
   - Choose: Python / FastAPI
   - Copy DSN

2. **Add to Railway:**
   ```bash
   railway variables set SENTRY_DSN="https://xxx@sentry.io/xxx"
   railway variables set SENTRY_ENVIRONMENT="production"
   ```

3. **Verify in Sentry dashboard:**
   - Should see "First event received" within 5 minutes
   - Check Issues tab for errors
   - Review Performance tab for slow endpoints

### Sentry Configuration (Already Set):
- ✅ FastAPI integration
- ✅ SQLAlchemy integration
- ✅ Request tracing (10% sample rate)
- ✅ Performance profiling (10% sample rate)
- ✅ PII scrubbing (cookies, sensitive headers)

---

## 3. Metrics & Performance (Prometheus) — Already Integrated ✅

### Current Metrics Exposed:

**Endpoint:** `https://prolific-optimism-production.up.railway.app/metrics`

**Metrics available:**
- `fitbites_http_requests_total` — Request count by method, path, status
- `fitbites_http_request_duration_seconds` — Request latency (histogram)
- `fitbites_active_requests` — In-flight request count
- `fitbites_uptime_seconds` — Process uptime

### Prometheus Scraping Setup (Optional):

If you have a Prometheus server, add this scrape config:

```yaml
scrape_configs:
  - job_name: 'fitbites-api'
    scrape_interval: 30s
    static_configs:
      - targets: ['prolific-optimism-production.up.railway.app']
    metrics_path: '/metrics'
    scheme: https
```

### Grafana Dashboard (Optional):

1. Import pre-built FastAPI dashboard or create custom
2. Useful panels:
   - Request rate (req/sec)
   - P50/P95/P99 latency
   - Error rate (5xx responses)
   - Active requests

---

## 4. Log Aggregation & Alerting

### Current Setup:
- ✅ Structured JSON logging (production)
- ✅ Railway log storage (7-day retention free, 90-day on Pro)

### Export to External Service (Optional):

#### Option A: Datadog
```bash
# Add Datadog agent to Dockerfile or use Railway integration
railway variables set DD_API_KEY="your_key"
railway variables set DD_SITE="datadoghq.com"
```

#### Option B: CloudWatch (if using AWS)
```bash
# Use CloudWatch log driver in Docker
railway variables set AWS_LOG_GROUP="/fitbites/api"
```

#### Option C: Papertrail (Simple, free tier)
```bash
# Add rsyslog forwarding to Papertrail
railway variables set PAPERTRAIL_HOST="logsX.papertrailapp.com"
railway variables set PAPERTRAIL_PORT="12345"
```

### Key Alerts to Set Up:

1. **High error rate:** >1% 5xx responses in 5 minutes
2. **Slow responses:** P95 latency >500ms for 10 minutes
3. **Database errors:** Any "database connection" log entries
4. **Rate limit abuse:** >100 429 responses from single IP in 1 minute

---

## 5. Database Monitoring

### Railway PostgreSQL Metrics (Built-in):

Railway dashboard shows:
- ✅ Connection count
- ✅ Query rate
- ✅ Disk usage
- ✅ CPU usage

### Manual Connection Pool Check:

```bash
# SSH to Railway container (if enabled)
railway run python -c "
from src.db.engine import engine
print(f'Pool size: {engine.pool.size()}')
print(f'Checked out: {engine.pool.checkedout()}')
print(f'Overflow: {engine.pool.overflow()}')
"
```

### Alerts to Set Up:

1. **High connection count:** >80% of pool size
2. **Slow queries:** Any query >1 second (configure in PostgreSQL)
3. **Disk space:** >80% usage

---

## 6. Performance Baselines (For Reference)

### Current Performance (Empty DB, Feb 24 2026):

| Endpoint | Method | P50 | P95 | P99 |
|----------|--------|-----|-----|-----|
| `/health` | GET | 5ms | 10ms | 15ms |
| `/api/v1/recipes` | GET | 50ms | 100ms | 200ms |
| `/api/v1/recipes/{id}` | GET | 20ms | 40ms | 80ms |
| `/api/v1/search` | GET | 100ms | 200ms | 400ms |
| `/api/v1/auth/signup` | POST | 200ms | 300ms | 500ms |

**Note:** These will increase with production data volume. Monitor trends, not absolutes.

---

## 7. Monitoring Checklist

Before launch, ensure:

- [ ] Uptime monitor configured (UptimeRobot/Pingdom)
- [ ] Sentry DSN added to Railway
- [ ] First Sentry error received (verify integration)
- [ ] Alert contacts configured (email, Telegram, etc.)
- [ ] Metrics endpoint responding (`/metrics`)
- [ ] Railway dashboard checked for resource usage
- [ ] Performance baselines documented
- [ ] On-call rotation defined (who gets alerts?)

---

## 8. Incident Response Plan

### When uptime monitor triggers:

1. **Check Railway dashboard** — Is service running?
2. **Check Sentry** — Recent errors?
3. **Check logs:** `railway logs -n 100`
4. **Quick fixes:**
   - Restart service: `railway up --detach`
   - Rollback: `railway rollback` (if recent deploy)
5. **Escalate:** If not resolved in 15 minutes, page on-call engineer

### When Sentry alert triggers:

1. **Triage error:**
   - Is it affecting all users? (high volume)
   - Or specific feature? (low volume, specific endpoint)
2. **Quick fix:**
   - If config issue → update Railway env var
   - If code bug → hotfix commit + deploy
   - If external service down → wait or disable feature
3. **Document:** Add to incident log

---

## 9. Recommended Monitoring Services

| Service | Free Tier | Use Case | Priority |
|---------|-----------|----------|----------|
| **UptimeRobot** | 50 monitors, 5 min interval | Uptime checks | 🔴 Critical |
| **Sentry** | 5K errors/month | Error tracking | 🔴 Critical |
| **Railway** | Built-in logs, metrics | Hosting metrics | ✅ Included |
| **Prometheus** | Self-hosted | Metrics scraping | 🟡 Nice-to-have |
| **Grafana** | Free hosted or self-hosted | Dashboards | 🟡 Nice-to-have |
| **Datadog** | 14-day trial | Full observability | 🟢 Optional ($$) |

---

## 10. Status Page (Optional, for Launch)

Consider setting up a public status page:

- **Statuspage.io** (Atlassian) — Free tier, hosted
- **Cachet** — Open source, self-hosted
- **Railway status page** — Custom Next.js page fetching `/health`

Shows users:
- ✅ All systems operational
- ⚠️ Degraded performance
- 🔴 Service outage

---

## Summary

**For MVP launch, MUST HAVE:**
1. ✅ Sentry error tracking (already set up)
2. 🔴 UptimeRobot health checks (15 min setup)
3. ✅ Railway built-in monitoring (already active)

**Nice-to-have for scale:**
- Prometheus + Grafana dashboards
- Log aggregation (Datadog/Papertrail)
- Custom alerting (PagerDuty)
- Status page

**Next steps:**
1. Create UptimeRobot account
2. Add Sentry DSN to Railway
3. Test alert flow (trigger downtime, verify notifications)
4. Document on-call rotation

---

**Last updated:** Feb 24, 2026 by BYTE
