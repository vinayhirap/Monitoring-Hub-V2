// monitoring-hub/frontend/src/pages/Overview.jsx
import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useWebSocket } from "../hooks/useWebSocket";
import { getLiveAccounts, getAlerts } from "../api/api";
import "./Overview.css";

const BASE = "http://localhost:8000";

export default function Overview() {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([]);
  const [alerts,   setAlerts]   = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [filter,   setFilter]   = useState("All");
  const [lastSync, setLastSync] = useState(null);
  const [isNOC,    setIsNOC]    = useState(false);

  const deletedIds = useRef(new Set());
  const { lastMessage: alertMsg } = useWebSocket("alerts");

  const loadAll = useCallback(async () => {
    try {
      const [accs, als] = await Promise.all([
        getLiveAccounts().catch(() => []),
        getAlerts().catch(() => []),
      ]);
      const filtered = (Array.isArray(accs) ? accs : [])
        .filter(a => !deletedIds.current.has(a.id));
      setAccounts(filtered);
      setAlerts(Array.isArray(als) ? als : []);
      setLastSync(new Date());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    const t = setInterval(loadAll, 60000);
    return () => clearInterval(t);
  }, [loadAll]);

  useEffect(() => {
    if (!alertMsg || alertMsg.type !== "new_alert") return;
    setAlerts(prev => [alertMsg, ...prev].slice(0, 100));
  }, [alertMsg]);

  useEffect(() => {
    document.body.classList.toggle("noc-mode", isNOC);
    return () => document.body.classList.remove("noc-mode");
  }, [isNOC]);

  async function handleDelete(e, acc) {
    e.stopPropagation();
    if (!window.confirm(`Remove "${acc.account_name}" from monitoring?`)) return;
    deletedIds.current.add(acc.id);
    setAccounts(prev => prev.filter(a => a.id !== acc.id));
    try {
      const res = await fetch(`${BASE}/admin/accounts/${acc.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      console.error("Delete failed:", err);
      deletedIds.current.delete(acc.id);
      setAccounts(prev => [...prev, acc].sort((a, b) => a.id - b.id));
      alert("Failed to remove account. Please try again.");
    }
  }

  const healthyCount  = accounts.filter(a => a.status === "healthy").length;
  const warningCount  = accounts.filter(a => a.status === "warning").length;
  const criticalCount = accounts.filter(a => a.status === "critical").length;

  const activeAlerts   = alerts.filter(a => (a.status || "").toLowerCase() === "active");
  const criticalAlerts = activeAlerts.filter(a => (a.severity || "").toUpperCase() === "CRITICAL").length;
  const warningAlerts  = activeAlerts.filter(a => (a.severity || "").toUpperCase() === "WARNING").length;

  const filteredAccounts = accounts.filter(a => {
    if (filter === "Healthy")  return a.status === "healthy";
    if (filter === "Warning")  return a.status === "warning";
    if (filter === "Critical") return a.status === "critical";
    return true;
  });

  return (
    <div className={`overview ${isNOC ? "noc-fullscreen" : ""}`}>
      <div className="ov-header">
        <div>
          <h1 style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-0.02em" }}>
            ASLOps Dashboard <span className="hl">Overview</span>
          </h1>
          <p style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 4 }}>
            Live AWS infrastructure monitoring across all accounts · NOC View
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {lastSync && (
            <span style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
              Synced {lastSync.toLocaleTimeString()}
            </span>
          )}
          <button className="btn-refresh" onClick={loadAll} title="Refresh now">↻ Refresh</button>
          <button
            className={`ov-noc-btn ${isNOC ? "noc-active" : ""}`}
            onClick={() => setIsNOC(v => !v)}
          >
            {isNOC ? "⊠ Exit NOC" : "⊞ NOC Mode"}
          </button>
        </div>
      </div>

      <div className="ov-summary">
        <SummaryTile icon="🏢" label="Total Accounts" value={accounts.length} />
        <SummaryTile icon="✅" label="Healthy"  value={healthyCount}  color="green" />
        <SummaryTile icon="⚠️" label="Warning"  value={warningCount}  color={warningCount  > 0 ? "yellow" : "default"} pulse={warningCount  > 0} />
        <SummaryTile icon="🔴" label="Critical" value={criticalCount} color={criticalCount > 0 ? "red"    : "default"} pulse={criticalCount > 0} />
      </div>

      {(criticalAlerts > 0 || warningAlerts > 0) && (
        <div className="alert-strip">
          <span className="as-dot critical" />
          {criticalAlerts > 0 && (
            <span style={{ fontWeight: 700, color: "var(--red)", marginRight: 8 }}>
              {criticalAlerts} CRITICAL
            </span>
          )}
          {warningAlerts > 0 && (
            <>
              <span style={{ color: "var(--text-muted)", marginRight: 8 }}>·</span>
              <span style={{ fontWeight: 600, color: "var(--yellow)", marginRight: 8 }}>
                {warningAlerts} WARNING
              </span>
            </>
          )}
          <span style={{ color: "var(--text-muted)", fontSize: 13 }}>
            — Active alerts require attention
          </span>
          <button onClick={() => navigate("/alerts")} className="as-btn">View Alerts →</button>
        </div>
      )}

      <div className="ov-section-bar">
        <h2 style={{ fontSize: 17, fontWeight: 700 }}>
          AWS Accounts
          <span style={{ fontWeight: 400, fontSize: 13, color: "var(--text-muted)", marginLeft: 8 }}>
            ({filteredAccounts.length})
          </span>
        </h2>
        <div className="filter-row">
          <span style={{ fontSize: 13, color: "var(--text-muted)", marginRight: 6 }}>Filter:</span>
          {["All", "Healthy", "Warning", "Critical"].map(f => (
            <button
              key={f}
              className={`f-btn ${filter === f ? "f-active" : ""}`}
              onClick={() => setFilter(f)}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="ov-loading"><span className="spin">◌</span> Fetching live AWS data…</div>
      ) : filteredAccounts.length === 0 ? (
        <div className="ov-empty">
          No accounts found.{" "}
          <span className="ov-link" onClick={() => navigate("/onboarding")}>Onboard an account →</span>
        </div>
      ) : (
        <div className="accounts-grid">
          {filteredAccounts.map(acc => (
            <AccountCard
              key={acc.id}
              account={acc}
              alerts={alerts}
              onClick={() => navigate(`/accounts/${acc.id}/services`)}
              onDelete={e => handleDelete(e, acc)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AccountCard({ account, alerts, onClick, onDelete }) {
  const status     = account.status || "healthy";
  const ec2Running = account.ec2_running ?? 0;
  const ec2Total   = account.ec2_total   ?? 0;

  // Filter alerts for this account
  const acctAlerts = alerts.filter(a => {
    const r = a.resource || a.resource_id || "";
    return (
      r.startsWith("i-") ||
      r.includes(account.account_id || "____")
    );
  });
  const activeAcctAlerts  = acctAlerts.filter(a => (a.status || "").toLowerCase() === "active");
  const acctCritical      = activeAcctAlerts.filter(a => (a.severity || "").toUpperCase() === "CRITICAL").length;
  const acctWarning       = activeAcctAlerts.filter(a => (a.severity || "").toUpperCase() === "WARNING").length;

  // Donut segments: base = ec2_running instances
  // Critical instances = min(acctCritical, ec2Running) — those with active critical alerts
  // Warning  instances = min(acctWarning,  ec2Running - criticalInstances)
  // Healthy  instances = remainder
  const total            = ec2Running || 0;
  const criticalCount    = Math.min(acctCritical, total);
  const warningCount     = Math.min(acctWarning,  Math.max(0, total - criticalCount));
  const healthyCount     = Math.max(0, total - criticalCount - warningCount);

  return (
    <div className={`account-card ac-${status}`} onClick={onClick}>
      <div className="acc-card-header">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {account.account_name}
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)" }}>
            {account.account_id}
          </div>
        </div>
        <StatusPill status={status} />
      </div>

      <div style={{ display: "flex", gap: 5, margin: "8px 0", flexWrap: "wrap" }}>
        <Tag text={account.region}      color="blue" />
        <Tag text={account.environment} color="purple" />
        {account.owner_team && <Tag text={account.owner_team} color="muted" />}
      </div>

      {(acctCritical > 0 || acctWarning > 0) && (
        <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
          {acctCritical > 0 && (
            <span style={{ fontSize: 10, color: "#ff4d6d", background: "rgba(255,77,109,0.1)", border: "1px solid rgba(255,77,109,0.2)", borderRadius: 4, padding: "1px 6px" }}>
              🔴 {acctCritical} critical
            </span>
          )}
          {acctWarning > 0 && (
            <span style={{ fontSize: 10, color: "#ffc940", background: "rgba(255,201,64,0.1)", border: "1px solid rgba(255,201,64,0.2)", borderRadius: 4, padding: "1px 6px" }}>
              ⚠ {acctWarning} warning
            </span>
          )}
        </div>
      )}

      <div className="acc-body">
        {/* 3-segment donut: green=healthy, amber=warning, red=critical */}
        <HealthRing
          total={total}
          healthy={healthyCount}
          warning={warningCount}
          critical={criticalCount}
        />
        <div className="acc-chips">
          <ResChip icon="🖥"  label="EC2"    value={ec2Total}                  sub={`${ec2Running} running`} />
          <ResChip icon="💾"  label="EBS"    value={account.ebs_total    || 0} />
          <ResChip icon="🪣"  label="S3"     value={account.s3_total     || 0} />
          <ResChip icon="λ"   label="Lambda" value={account.lambda_total || 0} />
        </div>
      </div>

      <div className="acc-footer">
        <span className="view-link">View Services →</span>
        <button className="btn-delete-sm" onClick={onDelete} title="Remove">✕</button>
      </div>
    </div>
  );
}

/**
 * HealthRing — 3-segment donut
 *
 * Segments (clockwise from 12 o'clock):
 *   🟢 green  = healthy running instances (no active alerts)
 *   🟡 amber  = instances with active WARNING alerts
 *   🔴 red    = instances with active CRITICAL alerts
 *
 * Centre label shows total running count.
 * If zero running: shows an empty grey ring.
 */
function HealthRing({ total, healthy, warning, critical }) {
  const r    = 28;
  const circ = 2 * Math.PI * r;
  const sw   = 7;

  if (total === 0) {
    return (
      <div className="h-ring-wrap">
        <svg width="70" height="70" viewBox="0 0 70 70">
          <circle cx="35" cy="35" r={r} fill="none" stroke="rgba(99,130,190,0.12)" strokeWidth={sw} />
        </svg>
        <div className="h-ring-label">
          <div className="h-ring-num" style={{ color: "var(--text-muted)" }}>0</div>
          <div className="h-ring-sub">running</div>
        </div>
      </div>
    );
  }

  // Build segments — only include non-zero ones
  const rawSegs = [
    { count: healthy,  color: "#00e5a0" }, // green
    { count: warning,  color: "#ffc940" }, // amber
    { count: critical, color: "#ff4d6d" }, // red
  ].filter(s => s.count > 0);

  let offsetAngle = 0; // degrees from top (−90°)
  const paths = rawSegs.map((seg, i) => {
    const pct    = seg.count / total;
    const angle  = pct * 360;
    const dash   = pct * circ;
    const gap    = circ - dash;
    const rotate = offsetAngle - 90; // start at 12 o'clock

    offsetAngle += angle;

    return (
      <circle
        key={i}
        cx="35" cy="35" r={r}
        fill="none"
        stroke={seg.color}
        strokeWidth={sw}
        strokeDasharray={`${dash} ${gap}`}
        strokeDashoffset={0}
        strokeLinecap="butt"
        transform={`rotate(${rotate} 35 35)`}
      />
    );
  });

  // Centre colour: red if any critical, amber if only warning, green if all healthy
  const centreColor = critical > 0 ? "#ff4d6d" : warning > 0 ? "#ffc940" : "#00e5a0";

  return (
    <div className="h-ring-wrap">
      <svg width="70" height="70" viewBox="0 0 70 70">
        {/* track */}
        <circle cx="35" cy="35" r={r} fill="none" stroke="rgba(99,130,190,0.08)" strokeWidth={sw} />
        {paths}
      </svg>
      <div className="h-ring-label">
        <div className="h-ring-num" style={{ color: centreColor }}>{total}</div>
        <div className="h-ring-sub">running</div>
      </div>
    </div>
  );
}

function ResChip({ icon, label, value, sub }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--bg-elevated)", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px", fontSize: 11 }}>
      <span style={{ fontSize: 12 }}>{icon}</span>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{value}</span>
      {sub && <span style={{ color: "var(--text-muted)", fontSize: 10 }}>· {sub}</span>}
    </div>
  );
}

function SummaryTile({ icon, label, value, color, pulse }) {
  return (
    <div className={`sum-tile sum-${color || "default"}`} style={{ position: "relative" }}>
      {pulse && <span className="pulse-ring" />}
      <span className="sum-icon">{icon}</span>
      <div className="sum-body">
        <div className="sum-label">{label}</div>
        <div className="sum-value">{value}</div>
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const m = {
    healthy:  { label: "Healthy",  cls: "pill-green" },
    warning:  { label: "Warning",  cls: "pill-yellow" },
    critical: { label: "Critical", cls: "pill-red" },
  };
  const { label, cls } = m[status] || m.healthy;
  return <span className={`status-pill ${cls}`}>{label}</span>;
}

function Tag({ text, color }) {
  return text ? <span className={`tag tag-${color || "blue"}`}>{text}</span> : null;
}
