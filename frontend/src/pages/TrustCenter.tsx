import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Gauge, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'

type Trust={project_id:number;name:string;symbol:string;score:number;level:string;factors:Record<string,number>;metrics:{campaigns:number;verified_funded_campaigns:number;participants:number;completions:number;completion_rate_pct:string;age_days:number};disclaimer:string}

export default function TrustCenter(){const [rows,setRows]=useState<Trust[]>([]);useEffect(()=>{api<Trust[]>('/trust/projects').then(setRows)},[])
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">PROJECT TRUST</span><h1>Signals before <em>hype.</em></h1><p>NuBagz scores observable participation, funding and transparency signals so newcomers have context before interacting.</p></div></div>
 <div className="custody-note"><AlertTriangle/><p><strong>Important:</strong> a NuBagz Trust Score is not an endorsement, audit, safety guarantee or investment recommendation. Crypto projects can fail or lose value even with strong participation signals.</p></div>
 <div className="bag-grid">{rows.map(r=><article className="bag-card" key={r.project_id}><div className="bag-card-top"><span className="category"><ShieldCheck/> ${r.symbol}</span><span>{r.level}</span></div><div className="big-token">{r.score}</div><h3>{r.name}</h3><p>{r.metrics.verified_funded_campaigns}/{r.metrics.campaigns} campaigns verified funded • {r.metrics.completions}/{r.metrics.participants} participant completions</p><div className="bag-meta"><span><CheckCircle2/> Funding {r.factors.verified_funding}/25</span><span><Gauge/> Completion {r.factors.completion_quality}/20</span></div><div className="bag-meta"><span>Transparency {r.factors.transparency}/15</span><span>Age {r.factors.age}/15</span></div></article>)}</div>{!rows.length&&<div className="empty-state"><ShieldCheck/><strong>No approved projects yet.</strong><p>Trust signals appear after projects enter the NuBagz ecosystem.</p></div>}</div>
}
