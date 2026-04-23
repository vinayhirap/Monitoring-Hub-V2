// monitoring-hub/frontend/src/pages/ServiceList.jsx
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";

const SERVICES = [
  { id:"ec2",    label:"EC2",    icon:"🖥",  desc:"Compute instances",     color:"#00c7ff" },
  { id:"ebs",    label:"EBS",    icon:"💾",  desc:"Block storage volumes",  color:"#38bdf8" },
  { id:"rds",    label:"RDS",    icon:"🗄",  desc:"Managed databases",      color:"#a78bfa" },
  { id:"s3",     label:"S3",     icon:"🪣",  desc:"Object storage buckets", color:"#fbbf24" },
  { id:"ecs",    label:"ECS",    icon:"📦",  desc:"Container services",     color:"#34d399" },
  { id:"elb",    label:"ELB",    icon:"⚖",   desc:"Load balancers",         color:"#f472b6" },
  { id:"lambda", label:"Lambda", icon:"λ",   desc:"Serverless functions",   color:"#00e5a0" },
];

export default function ServiceList() {
  const { id }    = useParams();
  const navigate  = useNavigate();
  const [account, setAccount] = useState(null);

  useEffect(() => {
    fetch(`http://localhost:8000/admin/accounts/${id}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setAccount(d); })
      .catch(console.error);
  }, [id]);

  return (
    <div style={{ maxWidth: 1100 }}>
      {/* Breadcrumb */}
      <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:20, fontSize:11, color:"var(--text-muted)", fontFamily:"var(--font-mono)", letterSpacing:"0.06em" }}>
        <span
          style={{ cursor:"pointer", color:"var(--accent)", transition:"opacity .15s" }}
          onClick={() => navigate("/overview")}
        >ALL ACCOUNTS</span>
        <span style={{ opacity:.4 }}>›</span>
        <span style={{ color:"var(--text-secondary)" }}>{account?.account_name ?? `Account ${id}`}</span>
        <span style={{ opacity:.4 }}>›</span>
        <span>SERVICES</span>
      </div>

      {/* Header */}
      <div style={{ marginBottom:32 }}>
        <h1 style={{ fontSize:24, fontWeight:700, marginBottom:5, letterSpacing:"-0.01em" }}>
          {account?.account_name ?? "Account"}
          <span style={{ color:"var(--accent)", marginLeft:8 }}>/ Services</span>
        </h1>
        <p style={{ color:"var(--text-muted)", fontSize:12 }}>
          {account?.account_id} · {account?.default_region} · Select a service to inspect resources
        </p>
      </div>

      {/* 4 + 3 layout: first row 4 cards, second row 3 centered */}
      <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
        {/* Row 1: EC2, EBS, RDS, S3 */}
        <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:16 }}>
          {SERVICES.slice(0, 4).map(svc => (
            <ServiceCard key={svc.id} svc={svc} onClick={() => navigate(`/accounts/${id}/${svc.id}`)} />
          ))}
        </div>
        {/* Row 2: ECS, ELB, Lambda — centered by using max-width */}
        <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:16, maxWidth:"75%", margin:"0 auto", width:"100%" }}>
          {SERVICES.slice(4).map(svc => (
            <ServiceCard key={svc.id} svc={svc} onClick={() => navigate(`/accounts/${id}/${svc.id}`)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ServiceCard({ svc, onClick }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background:   hovered ? "var(--bg-card-hover)" : "var(--bg-card)",
        border:       `1px solid ${hovered ? svc.color + "60" : "var(--border)"}`,
        borderRadius: "var(--radius-lg)",
        padding:      "28px 20px 22px",
        cursor:       "pointer",
        transition:   "all .18s ease",
        textAlign:    "center",
        position:     "relative",
        overflow:     "hidden",
        transform:    hovered ? "translateY(-4px)" : "translateY(0)",
        boxShadow:    hovered ? `0 12px 32px ${svc.color}20` : "none",
      }}
    >
      {/* top accent bar */}
      <div style={{
        position:"absolute", top:0, left:0, right:0, height:3,
        background:`linear-gradient(90deg,${svc.color}00,${svc.color},${svc.color}00)`,
        opacity: hovered ? 1 : 0.35,
        transition:"opacity .18s",
      }}/>

      {/* glow blob */}
      <div style={{
        position:"absolute", top:"18%", left:"50%", transform:"translateX(-50%)",
        width:70, height:70, borderRadius:"50%",
        background: svc.color + "1a",
        filter:"blur(20px)",
        opacity: hovered ? 1 : 0,
        transition:"opacity .2s",
        pointerEvents:"none",
      }}/>

      <div style={{
        fontSize: 36,
        marginBottom: 12,
        position: "relative",
        // colored circle behind icon
        width: 64, height: 64, borderRadius: "50%",
        background: svc.color + "15",
        border: `1px solid ${svc.color}25`,
        display: "flex", alignItems: "center", justifyContent: "center",
        margin: "0 auto 14px",
        transition: "background .18s, border-color .18s",
        ...(hovered ? { background: svc.color + "25", borderColor: svc.color + "50" } : {}),
      }}>
        {svc.icon}
      </div>

      <div style={{ fontWeight:700, fontSize:15, color:"var(--text-primary)", marginBottom:6 }}>{svc.label}</div>
      <div style={{ fontSize:12, color:"var(--text-muted)", lineHeight:1.5, marginBottom:14 }}>{svc.desc}</div>

      <div style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        fontSize:10, fontFamily:"var(--font-mono)", fontWeight:700,
        color: svc.color, letterSpacing:"0.08em",
        background: svc.color + "12",
        border: `1px solid ${svc.color}30`,
        borderRadius: 20,
        padding: "4px 12px",
        opacity: hovered ? 1 : 0.6,
        transition:"all .18s",
      }}>
        OPEN →
      </div>
    </div>
  );
}