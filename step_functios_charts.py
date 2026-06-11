#!/usr/bin/env python3
"""
Step Functions Execution Dashboard
Uses CloudWatch Metrics to fetch daily execution counts per state machine.
Generates an interactive HTML report with:
  - KPI summary cards
  - Combined daily chart (all machines)
  - Per-machine breakdown bar chart
  - Individual daily chart per state machine
"""

import boto3
import argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import json


METRICS = ["ExecutionsStarted", "ExecutionsSucceeded", "ExecutionsFailed",
           "ExecutionsTimedOut", "ExecutionsAborted"]


def get_standard_state_machines(sfn_client):
    machines = []
    paginator = sfn_client.get_paginator("list_state_machines")
    for page in paginator.paginate():
        for sm in page["stateMachines"]:
            if sm.get("type", "STANDARD") == "STANDARD":
                machines.append(sm)
            else:
                name = sm["stateMachineArn"].split(":")[-1]
                print(f"  [EXPRESS] {name} — skipped")
    return machines


def get_daily_metrics(cw_client, state_machine_arn, start_date, end_date):
    """Returns { "YYYY-MM-DD": { metric: count } } for one state machine."""
    daily = defaultdict(lambda: {m: 0 for m in METRICS})
    for metric in METRICS:
        resp = cw_client.get_metric_statistics(
            Namespace="AWS/States",
            MetricName=metric,
            Dimensions=[{"Name": "StateMachineArn", "Value": state_machine_arn}],
            StartTime=start_date,
            EndTime=end_date,
            Period=86400,
            Statistics=["Sum"],
        )
        for point in resp["Datapoints"]:
            day = point["Timestamp"].strftime("%Y-%m-%d")
            daily[day][metric] = int(point["Sum"])
    return daily


def generate_html(all_daily, machine_daily, machine_summary, sorted_days, region, start_date, end_date):
    started   = [all_daily[d]["ExecutionsStarted"]   for d in sorted_days]
    succeeded = [all_daily[d]["ExecutionsSucceeded"] for d in sorted_days]
    failed    = [all_daily[d]["ExecutionsFailed"]    for d in sorted_days]

    machine_names   = list(machine_summary.keys())
    machine_success = [machine_summary[m]["ExecutionsSucceeded"] for m in machine_names]
    machine_failed  = [machine_summary[m]["ExecutionsFailed"]    for m in machine_names]
    machine_totals  = [machine_summary[m]["ExecutionsStarted"]   for m in machine_names]

    total_started   = sum(started)
    total_succeeded = sum(succeeded)
    total_failed    = sum(failed)
    success_rate    = round(total_succeeded / total_started * 100, 1) if total_started else 0

    # Build per-machine daily data for individual charts
    per_machine_js = {}
    for name, daily in machine_daily.items():
        per_machine_js[name] = {
            "succeeded": [daily.get(d, {}).get("ExecutionsSucceeded", 0) for d in sorted_days],
            "failed":    [daily.get(d, {}).get("ExecutionsFailed", 0) +
                          daily.get(d, {}).get("ExecutionsTimedOut", 0) +
                          daily.get(d, {}).get("ExecutionsAborted", 0)  for d in sorted_days],
        }

    # HTML blocks for individual machine charts
    machine_chart_html = ""
    for name in machine_names:
        safe_id = name.replace("-", "_").replace(".", "_")
        machine_chart_html += f"""
<div class="section">
  <div class="section-title">{name}</div>
  <div class="chart-card">
    <canvas id="chart_{safe_id}" style="max-height:200px"></canvas>
  </div>
</div>
"""

    # JS to initialise each individual machine chart
    machine_chart_js = ""
    for name in machine_names:
        safe_id = name.replace("-", "_").replace(".", "_")
        data = per_machine_js[name]
        machine_chart_js += f"""
  new Chart(document.getElementById('chart_{safe_id}'), {{
    type: 'bar',
    data: {{
      labels: LABELS,
      datasets: [
        {{ label: 'Succeeded', data: {json.dumps(data['succeeded'])},
           backgroundColor: GREEN, borderRadius: 3 }},
        {{ label: 'Failed',    data: {json.dumps(data['failed'])},
           backgroundColor: RED,   borderRadius: 3 }},
      ],
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ position: 'top', labels: {{ boxWidth: 10, padding: 12 }} }},
        tooltip: {{ callbacks: {{ footer: items => 'Total: ' + items.reduce((s,i) => s + i.parsed.y, 0) }} }},
      }},
      scales: {{
        x: {{ stacked: true, grid: {{ color: GRID }}, ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
        y: {{ stacked: true, grid: {{ color: GRID }}, beginAtZero: true }},
      }},
    }},
  }});
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Step Functions Dashboard — {region}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
      background: #0d1117; color: #c9d1d9;
      min-height: 100vh; padding: 32px 24px;
    }}
    header {{ border-bottom: 1px solid #21262d; padding-bottom: 24px; margin-bottom: 36px; }}
    .eyebrow {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #6e7681; margin-bottom: 8px; }}
    h1 {{ font-size: 28px; font-weight: 700; color: #f0f6fc; letter-spacing: -0.02em; }}
    .meta {{ margin-top: 6px; font-size: 12px; color: #484f58; }}
    .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 40px; }}
    .kpi {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 20px 24px; }}
    .kpi-label {{ font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #6e7681; margin-bottom: 10px; }}
    .kpi-value {{ font-size: 36px; font-weight: 700; line-height: 1; color: #f0f6fc; }}
    .kpi-value.green {{ color: #3fb950; }}
    .kpi-value.red   {{ color: #f85149; }}
    .kpi-value.blue  {{ color: #58a6ff; }}
    .kpi-sub {{ font-size: 11px; color: #484f58; margin-top: 6px; }}
    .section {{ margin-bottom: 40px; }}
    .section-title {{
      font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase;
      color: #8b949e; margin-bottom: 16px;
      display: flex; align-items: center; gap: 8px;
    }}
    .section-title::after {{ content: ''; flex: 1; height: 1px; background: #21262d; }}
    .chart-card {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 24px; }}
    canvas {{ max-height: 300px; }}
    .tab-bar {{ display: flex; gap: 4px; margin-bottom: 20px; }}
    .tab {{
      background: transparent; border: 1px solid #21262d; color: #6e7681;
      font-family: inherit; font-size: 12px; letter-spacing: 0.05em;
      padding: 6px 14px; border-radius: 6px; cursor: pointer; transition: all 0.15s;
    }}
    .tab:hover {{ color: #c9d1d9; border-color: #444c56; }}
    .tab.active {{ background: #1f6feb22; border-color: #1f6feb; color: #58a6ff; }}
    .filter-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
    .filter-row label {{ font-size: 12px; color: #6e7681; }}
    select {{
      background: #161b22; border: 1px solid #21262d; color: #c9d1d9;
      font-family: inherit; font-size: 12px; padding: 6px 10px;
      border-radius: 6px; cursor: pointer; outline: none;
    }}
    select:focus {{ border-color: #1f6feb; }}
    .per-machine-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
      gap: 24px;
    }}
    .per-machine-grid .section {{ margin-bottom: 0; }}
    footer {{ border-top: 1px solid #21262d; padding-top: 20px; margin-top: 48px; font-size: 11px; color: #484f58; text-align: center; }}
  </style>
</head>
<body>

<header>
  <div class="eyebrow">AWS Step Functions · {region}</div>
  <h1>Execution Dashboard</h1>
  <div class="meta">
    {start_date.strftime("%b %d, %Y")} → {end_date.strftime("%b %d, %Y")} &nbsp;·&nbsp; Last 20 days &nbsp;·&nbsp; Source: CloudWatch Metrics
  </div>
</header>

<!-- KPIs -->
<div class="kpi-row">
  <div class="kpi">
    <div class="kpi-label">Total Started</div>
    <div class="kpi-value blue">{total_started:,}</div>
    <div class="kpi-sub">across {len(machine_summary)} state machine(s)</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Succeeded</div>
    <div class="kpi-value green">{total_succeeded:,}</div>
    <div class="kpi-sub">{success_rate}% success rate</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Failed / Timed Out</div>
    <div class="kpi-value red">{total_failed:,}</div>
    <div class="kpi-sub">{round(100 - success_rate, 1)}% failure rate</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">State Machines</div>
    <div class="kpi-value">{len(machine_summary)}</div>
    <div class="kpi-sub">Standard, in {region}</div>
  </div>
</div>

<!-- Combined daily chart -->
<div class="section">
  <div class="section-title">All State Machines — Daily Executions</div>
  <div class="chart-card">
    <div class="tab-bar">
      <button class="tab active" onclick="setChartType('bar', event)">Bar</button>
      <button class="tab" onclick="setChartType('line', event)">Line</button>
    </div>
    <canvas id="dailyChart"></canvas>
  </div>
</div>

<!-- Per-machine breakdown (totals) -->
<div class="section">
  <div class="section-title">Breakdown by State Machine</div>
  <div class="chart-card">
    <div class="filter-row">
      <label>Sort by</label>
      <select id="sortSelect" onchange="updateMachineChart()">
        <option value="total">Total executions</option>
        <option value="failed">Failures</option>
        <option value="name">Name</option>
      </select>
    </div>
    <canvas id="machineChart"></canvas>
  </div>
</div>

<!-- Per-machine daily charts -->
<div class="section">
  <div class="section-title">Daily Executions per State Machine</div>
  <div class="per-machine-grid">
    {machine_chart_html}
  </div>
</div>

<footer>
  Generated on {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} &nbsp;·&nbsp; Region: {region}
</footer>

<script>
  const LABELS    = {json.dumps(sorted_days)};
  const SUCCEEDED = {json.dumps(succeeded)};
  const FAILED    = {json.dumps(failed)};

  const M_NAMES   = {json.dumps(machine_names)};
  const M_TOTALS  = {json.dumps(machine_totals)};
  const M_SUCCESS = {json.dumps(machine_success)};
  const M_FAILED  = {json.dumps(machine_failed)};

  const GRID    = 'rgba(255,255,255,0.06)';
  const GREEN   = '#3fb950';
  const RED     = '#f85149';
  const GREEN20 = 'rgba(63,185,80,0.18)';
  const RED20   = 'rgba(248,81,73,0.18)';

  Chart.defaults.color = '#6e7681';
  Chart.defaults.borderColor = GRID;
  Chart.defaults.font.family = "'SF Mono', 'Fira Code', monospace";
  Chart.defaults.font.size = 11;

  // ── Combined daily chart ──────────────────────────────────────
  let dailyChart;

  function buildDailyDatasets(type) {{
    const fill = type === 'line';
    return [
      {{ label: 'Succeeded', data: SUCCEEDED, backgroundColor: fill ? GREEN20 : GREEN,
         borderColor: GREEN, borderWidth: fill ? 2 : 0, fill: fill, tension: 0.35, borderRadius: fill ? 0 : 4 }},
      {{ label: 'Failed',    data: FAILED,    backgroundColor: fill ? RED20   : RED,
         borderColor: RED,   borderWidth: fill ? 2 : 0, fill: fill, tension: 0.35, borderRadius: fill ? 0 : 4 }},
    ];
  }}

  function createDailyChart(type) {{
    if (dailyChart) dailyChart.destroy();
    dailyChart = new Chart(document.getElementById('dailyChart'), {{
      type,
      data: {{ labels: LABELS, datasets: buildDailyDatasets(type) }},
      options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ position: 'top', labels: {{ boxWidth: 12, padding: 16 }} }},
          tooltip: {{ callbacks: {{ footer: items => 'Total: ' + items.reduce((s,i) => s + i.parsed.y, 0) }} }},
        }},
        scales: {{
          x: {{ stacked: type === 'bar', grid: {{ color: GRID }}, ticks: {{ maxRotation: 45 }} }},
          y: {{ stacked: type === 'bar', grid: {{ color: GRID }}, beginAtZero: true }},
        }},
      }},
    }});
  }}

  function setChartType(type, event) {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    createDailyChart(type);
  }}

  createDailyChart('bar');

  // ── Machine totals chart ──────────────────────────────────────
  let machineChart;

  function updateMachineChart() {{
    const sortBy = document.getElementById('sortSelect').value;
    const idx = M_NAMES.map((_, i) => i);
    if (sortBy === 'total')  idx.sort((a, b) => M_TOTALS[b]  - M_TOTALS[a]);
    if (sortBy === 'failed') idx.sort((a, b) => M_FAILED[b]  - M_FAILED[a]);
    if (sortBy === 'name')   idx.sort((a, b) => M_NAMES[a].localeCompare(M_NAMES[b]));
    const d = {{ names: idx.map(i => M_NAMES[i]), success: idx.map(i => M_SUCCESS[i]), failed: idx.map(i => M_FAILED[i]) }};
    if (machineChart) machineChart.destroy();
    machineChart = new Chart(document.getElementById('machineChart'), {{
      type: 'bar',
      data: {{
        labels: d.names,
        datasets: [
          {{ label: 'Succeeded', data: d.success, backgroundColor: GREEN, borderRadius: 4 }},
          {{ label: 'Failed',    data: d.failed,  backgroundColor: RED,   borderRadius: 4 }},
        ],
      }},
      options: {{
        indexAxis: 'y', responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{ legend: {{ position: 'top', labels: {{ boxWidth: 12, padding: 16 }} }} }},
        scales: {{
          x: {{ stacked: true, grid: {{ color: GRID }}, beginAtZero: true }},
          y: {{ stacked: true, grid: {{ color: GRID }} }},
        }},
      }},
    }});
  }}

  updateMachineChart();

  // ── Per-machine daily charts ──────────────────────────────────
  {machine_chart_js}
</script>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(
        description="Step Functions dashboard using CloudWatch Metrics (last 20 days)."
    )
    parser.add_argument("--region",  required=True, help="AWS region (e.g. us-east-1)")
    parser.add_argument("--profile", default=None,  help="AWS CLI profile name (optional)")
    parser.add_argument("--output",  default="step_functions_report.html",
                        help="Output HTML file (default: step_functions_report.html)")
    args = parser.parse_args()

    end_date   = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=20)

    print(f"Region : {args.region}")
    print(f"Period : {start_date.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')}")
    print()

    session    = boto3.Session(profile_name=args.profile, region_name=args.region)
    sfn_client = session.client("stepfunctions")
    cw_client  = session.client("cloudwatch")

    print("Fetching state machines...")
    machines = get_standard_state_machines(sfn_client)
    print(f"Found {len(machines)} Standard state machine(s).\n")

    if not machines:
        print("Nothing to report. Exiting.")
        return

    all_daily       = defaultdict(lambda: {"ExecutionsStarted": 0, "ExecutionsSucceeded": 0, "ExecutionsFailed": 0})
    machine_daily   = {}   # name → { day → { metric: count } }
    machine_summary = {}   # name → { metric: total }

    for sm in machines:
        arn  = sm["stateMachineArn"]
        name = arn.split(":")[-1]
        print(f"  {name} ...")
        daily = get_daily_metrics(cw_client, arn, start_date, end_date)

        machine_daily[name] = daily

        # Merge into global daily totals
        for day, counts in daily.items():
            all_daily[day]["ExecutionsStarted"]   += counts["ExecutionsStarted"]
            all_daily[day]["ExecutionsSucceeded"] += counts["ExecutionsSucceeded"]
            all_daily[day]["ExecutionsFailed"]    += (
                counts["ExecutionsFailed"] +
                counts["ExecutionsTimedOut"] +
                counts["ExecutionsAborted"]
            )

        machine_summary[name] = {
            "ExecutionsStarted":   sum(v["ExecutionsStarted"]   for v in daily.values()),
            "ExecutionsSucceeded": sum(v["ExecutionsSucceeded"] for v in daily.values()),
            "ExecutionsFailed":    sum(
                v["ExecutionsFailed"] + v["ExecutionsTimedOut"] + v["ExecutionsAborted"]
                for v in daily.values()
            ),
        }

    # Fill missing days with zeros
    sorted_days = []
    for i in range(20):
        day = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        sorted_days.append(day)
        if day not in all_daily:
            all_daily[day] = {"ExecutionsStarted": 0, "ExecutionsSucceeded": 0, "ExecutionsFailed": 0}

    print(f"\nGenerating report → {args.output}")
    html = generate_html(all_daily, machine_daily, machine_summary, sorted_days, region=args.region,
                         start_date=start_date, end_date=end_date)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Done! Open {args.output} in your browser.")


if __name__ == "__main__":
    main()