import { useEffect, useMemo, useState } from 'react'
import { ArrowDownToLine, Coins, Gem, History, Sparkles } from 'lucide-react'
import { api } from '../lib/api'

type AssetAmount={asset:string;amount:string}
type Summary={lifetime:AssetAmount[];available:AssetAmount[];pending:AssetAmount[];withdrawn:AssetAmount[];referral:AssetAmount[];unique_assets:number;monthly:{month:string;assets:AssetAmount[]}[]}

const totalUnits=(rows:AssetAmount[])=>rows.reduce((sum,row)=>sum+Number(row.amount||0),0)

export default function Earnings(){
 const [data,setData]=useState<Summary|null>(null)
 useEffect(()=>{api<Summary>('/earnings/summary').then(setData)},[])
 const lifetimeUnits=useMemo(()=>totalUnits(data?.lifetime||[]),[data])
 const availableUnits=useMemo(()=>totalUnits(data?.available||[]),[data])
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">EARNINGS CENTRE</span><h1>Everything you’ve <em>Bagged.</em></h1><p>Track earned assets, balances waiting to be withdrawn, settled rewards and referral income in one place.</p></div></div>
 <div className="stats-grid"><div className="stat-card hot"><span><Sparkles/>LIFETIME UNITS</span><strong>{lifetimeUnits.toLocaleString(undefined,{maximumFractionDigits:4})}</strong><small>Across all reward assets</small></div><div className="stat-card"><span><Coins/>AVAILABLE</span><strong>{availableUnits.toLocaleString(undefined,{maximumFractionDigits:4})}</strong><small>Ledger units ready to use</small></div><div className="stat-card"><span><Gem/>ASSETS BAGGED</span><strong>{data?.unique_assets??'—'}</strong><small>Unique reward assets</small></div><div className="stat-card"><span><ArrowDownToLine/>WITHDRAWALS</span><strong>{data?.withdrawn.length??'—'}</strong><small>Assets with settled withdrawals</small></div></div>
 <div className="two-col"><section className="panel"><div className="panel-head"><div><span>LIFETIME EARNINGS</span><h2>Assets earned</h2></div></div>{data?.lifetime.length?data.lifetime.map(row=><div className="treasury-row" key={row.asset}><strong>{row.asset}</strong><b>{Number(row.amount).toLocaleString(undefined,{maximumFractionDigits:8})}</b></div>):<div className="empty-state"><Coins/><strong>No earnings yet.</strong><p>Complete your first funded Bag to start your earnings history.</p></div>}</section>
 <section className="panel"><div className="panel-head"><div><span>REFERRAL INCOME</span><h2>Earn when your people Bag</h2></div></div>{data?.referral.length?data.referral.map(row=><div className="treasury-row" key={row.asset}><strong>{row.asset}</strong><b>{Number(row.amount).toLocaleString(undefined,{maximumFractionDigits:8})}</b></div>):<div className="empty-state"><Sparkles/><strong>No referral earnings yet.</strong><p>Share your NuBagz referral code and earn from funded campaign referral allocations.</p></div>}</section></div>
 <section className="panel activity-panel"><div className="panel-head"><div><span><History/> MONTHLY HISTORY</span><h2>Your earning timeline</h2></div></div>{data?.monthly.length?data.monthly.slice().reverse().map(row=><div className="activity-row" key={row.month}><div><span>{row.month}</span><strong>{row.assets.length} reward asset{row.assets.length===1?'':'s'}</strong></div><b>{row.assets.map(a=>`${Number(a.amount).toLocaleString(undefined,{maximumFractionDigits:4})} ${a.asset}`).join(' • ')}</b></div>):<div className="empty-state">Your monthly earning history will appear after your first reward.</div>}</section></div>
}
