import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ExternalLink, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react'
import { api } from '../lib/api'
import type { ChallengeFeed } from '../types'

const filters=[
  ['ALL','All'],['SOCIAL','Social'],['BAG_WORK','Bag Work'],['CONTENT','Content'],['COMMUNITY','Community'],['ONCHAIN','On-chain'],['CUSTOM','Custom'],
] as const

function typeLabel(row:ChallengeFeed){if(row.category==='SOCIAL')return `${row.provider||'SOCIAL'} · ${row.action||'ACTION'}`;return row.category.replace('_',' ')}
function targetHref(row:ChallengeFeed){const raw=(row.target_url||'').trim();if(!raw)return '';if(/^https?:\/\//i.test(raw))return raw;if(row.provider==='X')return `https://x.com/${raw.replace(/^@/,'')}`;return ''}

export default function BagWork(){
  const [rows,setRows]=useState<ChallengeFeed[]>([]);const [filter,setFilter]=useState('ALL');const [loading,setLoading]=useState(true);const [busy,setBusy]=useState<number|null>(null);const [message,setMessage]=useState('')
  const load=async()=>{setLoading(true);try{setRows(await api<ChallengeFeed[]>('/challenges'));setMessage('')}catch(e:any){setMessage(e?.message||'Could not load Bag Work.')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[])
  const visible=useMemo(()=>filter==='ALL'?rows:rows.filter(r=>r.category===filter),[rows,filter])
  const complete=async(row:ChallengeFeed)=>{let answer:string|undefined;let evidence:string|undefined
    if(row.verification_type==='PROJECT_REVIEW'){const value=window.prompt('Add a proof link or a short evidence note for project review.');if(!value)return;evidence=value}
    if(row.verification_type==='QUIZ'){const question=String(row.config?.question||'Enter your answer');const value=window.prompt(question);if(value===null)return;answer=value}
    setBusy(row.id);setMessage('');try{const result=await api<{status:string;completed:boolean}>(`/challenges/${row.id}/complete`,{method:'POST',body:JSON.stringify({answer:answer||null,evidence:evidence||null})});setMessage(result.status==='PENDING'?'Proof submitted for project review.':result.completed?'Bag completed — reward settled.':'Bag Work verified.');await load()}catch(e:any){setMessage(e?.message||'This activity could not be verified yet.')}finally{setBusy(null)}}
  return <div className="page bag-work-page"><div className="page-head"><div><span className="eyebrow small">BAG WORK</span><h1>One place to <em>earn your way in.</em></h1><p>Social actions, project work, content, community and on-chain activities all live in one feed. Verification happens according to the activity type.</p></div><button className="mini-action" onClick={()=>void load()} disabled={loading}><RefreshCw/> Refresh</button></div>
  <div className="bag-work-filters">{filters.map(([key,label])=><button key={key} className={filter===key?'active':''} onClick={()=>setFilter(key)}>{label}</button>)}</div>
  {message&&<div className="form-note bag-work-message">{message}</div>}
  {loading?<div className="panel empty-state"><RefreshCw/><strong>Loading Bag Work…</strong></div>:visible.length?<div className="bag-work-grid">{visible.map(row=>{const done=row.completion_status==='VERIFIED'||row.completion_status==='APPROVED';const pending=row.completion_status==='PENDING';const href=targetHref(row);return <article className={`panel bag-work-card ${done?'completed':''}`} key={row.id}><div className="bag-work-card-top"><span className="challenge-type">{typeLabel(row)}</span>{done?<span className="verified-chip"><CheckCircle2/> Verified</span>:pending?<span className="pending-chip">Pending review</span>:<span className="xp-chip">+{row.xp_reward} XP</span>}</div><div className="challenge-project"><span>{row.project_name}</span><small>${row.project_symbol}</small></div><h2>{row.title}</h2><p>{row.description}</p><div className="challenge-reward"><div><small>Bag completion reward</small><strong>{Number(row.user_reward).toLocaleString(undefined,{maximumFractionDigits:6})} {row.reward_asset}</strong></div><div><small>Verification</small><strong>{row.verification_type==='AUTO'?'Automatic':row.verification_type.replace('_',' ')}</strong></div></div>{row.category==='SOCIAL'&&<div className="auto-proof-note"><ShieldCheck/> NuBagz checks the action against your connected X identity. A typed username is never accepted as proof.</div>}<div className="challenge-actions">{href&&!done&&!pending&&<a className="mini-action" href={href} target="_blank" rel="noreferrer"><ExternalLink/> Open {row.provider==='X'?'X':'target'}</a>}<button className={`btn ${done?'ghost':'primary'}`} disabled={done||pending||busy===row.id} onClick={()=>void complete(row)}>{done?<><CheckCircle2/> Completed</>:pending?'Awaiting review':busy===row.id?'Checking…':row.verification_type==='AUTO'?<><ShieldCheck/> Verify activity</>:<><Sparkles/> {row.verification_type==='PROJECT_REVIEW'?'Submit proof':'Complete'}</>}</button></div></article>})}</div>:<div className="panel empty-state"><Sparkles/><strong>No Bag Work in this filter yet</strong><p>New project activities will appear here as they go live.</p></div>}</div>
}
