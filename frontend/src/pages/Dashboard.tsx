import { useEffect, useState } from 'react'
import { ArrowUpRight, Flame, Gem, Layers3, Sparkles, Trophy } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import type { Dashboard as DashboardType } from '../types'
import { useAuth } from '../context/AuthContext'

type Access={bag_score:number;tier:string;tier_min_score:number;tier_max_score:number;benefits:string[];next_tier:string|null;next_tier_score:number|null;points_to_next:number;principle:string}

export default function Dashboard(){
 const {user}=useAuth(); const [dash,setDash]=useState<DashboardType|null>(null);const [access,setAccess]=useState<Access|null>(null)
 useEffect(()=>{Promise.all([api<DashboardType>('/users/dashboard'),api<Access>('/access/me')]).then(([d,a])=>{setDash(d);setAccess(a)}).catch(()=>{})},[])
 const points=dash?.bag_score??user?.bag_score??0
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">NUBAGZ COMMAND CENTER</span><h1>Yo, {user?.username}. <em>Keep baggin'.</em></h1><p>Discover Challenges, build meaningful participation and grow your NuBagz Points. My Trust stays separate as your integrity signal.</p></div><Link to="/app/work?view=for-you" className="btn primary">Explore Challenges <ArrowUpRight size={17}/></Link></div>
 <div className="stats-grid"><div className="stat-card"><span><Gem/>ASSETS BAGGED</span><strong>{dash?.lifetime_assets ?? '—'}</strong><small>Unique reward assets</small></div><div className="stat-card"><span><Layers3/>CHALLENGES COMPLETED</span><strong>{dash?.completed_bagz ?? '—'}</strong><small>{dash?.active_bagz||0} active right now</small></div><div className="stat-card hot"><span><Trophy/>POINTS • {access?.tier||'—'}</span><strong>{points.toLocaleString()}</strong><div className="score-bar"><i style={{width:`${Math.min(100,points/10)}%`}}/></div><small>{access?.next_tier_score?`${access.points_to_next} Points to ${access.next_tier}`:'Top access tier reached'}</small></div><div className="stat-card"><span><Flame/>STREAK</span><strong>{dash?.streak_days ?? user?.streak_days}<em> days</em></strong><small>Come back tomorrow</small></div></div>
 <div className="dash-grid"><section className="panel balance-panel"><div className="panel-head"><div><span>MY BAG</span><h2>What you've earned</h2></div><Link to="/app/bag">View all <ArrowUpRight/></Link></div>{dash?.balances?.length?<div className="asset-list">{dash.balances.slice(0,5).map((b,i)=><div className="asset-row" key={b.asset_symbol}><div className={`asset-icon a${i%4}`}>{b.asset_symbol.slice(0,2)}</div><div><strong>{b.asset_symbol}</strong><small>Available</small></div><b>{Number(b.amount).toLocaleString(undefined,{maximumFractionDigits:4})}</b></div>)}</div>:<div className="empty-state"><Sparkles/><strong>Your Bag is empty — for now.</strong><p>Complete an approved Challenge to earn your first project reward.</p><Link to="/app/work?view=all">Browse Bag Work</Link></div>}</section>
 <section className="panel xp-panel"><div className="level-orb"><Trophy/><strong>{access?.tier||'STARTER'}</strong></div><span>PARTICIPATION</span><h2>{points.toLocaleString()} Points</h2><div className="xp-track"><i style={{width:`${Math.min(100,points/10)}%`}}/></div><p>Points represent NuBagz participation. They do not represent Trust, money deposited or a guarantee of future token allocation.</p><div className="unlock"><Sparkles/><div><strong>{access?.tier||'Starter'} access</strong><span>{access?.benefits?.join(' • ')||'Explore Challenges • Build participation • Earn project rewards'}</span></div></div></section></div>
 </div>
}
