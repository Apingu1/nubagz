import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Compass, LayoutDashboard, Trophy, BriefcaseBusiness, Shield, LogOut, WalletCards, Zap, BadgePoundSterling, Gift, CalendarDays, RadioTower, ShieldCheck, UserRoundCheck, Network, Hammer, Award, Coins, BrainCircuit, Bell, BarChart3, FileStack, Star, Scale, Activity, Flame, Bookmark, ArrowLeftRight, Fuel, PanelLeftClose, PanelLeftOpen, Menu, X } from 'lucide-react'
import { Logo } from './Logo'
import { BagZRouteFeature } from './BagZMascot'
import { useAuth } from '../context/AuthContext'

export default function AppShell(){
 const {user,logout}=useAuth();const nav=useNavigate();const location=useLocation()
 const [collapsed,setCollapsed]=useState(()=>{try{return localStorage.getItem('nubagz.sidebar.collapsed')!=='false'}catch{return true}})
 const [mobileOpen,setMobileOpen]=useState(false)
 useEffect(()=>{try{localStorage.setItem('nubagz.sidebar.collapsed',String(collapsed))}catch{}},[collapsed])
 useEffect(()=>{setMobileOpen(false)},[location.pathname])
 const items=[['/app','Home',LayoutDashboard],['/app/daily','Daily Earn',CalendarDays],['/app/for-you','For You',BrainCircuit],['/app/trending','Trending',Flame],['/app/watchbag','WatchBag',Bookmark],['/app/swaps','Swaps',ArrowLeftRight],['/app/gas','Gas Pass',Fuel],['/app/notifications','Notifications',Bell],['/app/activity','Activity',Activity],['/app/discover','Discover',Compass],['/app/drops','BagDrops',Gift],['/app/bounties','Bounties',Award],['/app/revenue-share','Revenue Share',Coins],['/app/builders','BagBuilders',Hammer],['/app/onchain','Onchain Lab',RadioTower],['/app/trust','Project Trust',ShieldCheck],['/app/reviews','Reviews',Star],['/app/reports','Reports',Scale],['/app/account-trust','My Trust',UserRoundCheck],['/app/earnings','Earnings',BadgePoundSterling],['/app/referrals','Referrals',Network],['/app/bag','My Bag',WalletCards],['/app/leaderboard','Leaderboard',Trophy],['/app/studio','Creator Studio',BriefcaseBusiness]] as const
 const linkClass=({isActive}:{isActive:boolean})=>isActive?'side-link active':'side-link'
 return <div className={`app-shell ${collapsed?'sidebar-is-collapsed':''}`}>
  <aside className={`sidebar ${collapsed?'collapsed':''} ${mobileOpen?'mobile-open':''}`}>
   <div className="sidebar-top"><Logo/><button className="sidebar-close-mobile" aria-label="Close menu" onClick={()=>setMobileOpen(false)}><X size={20}/></button><button className="sidebar-collapse-btn" aria-label={collapsed?'Expand navigation':'Collapse navigation'} title={collapsed?'Expand navigation':'Collapse navigation'} onClick={()=>setCollapsed(v=>!v)}>{collapsed?<PanelLeftOpen size={18}/>:<PanelLeftClose size={18}/>}</button></div>
   <div className="side-kicker">EARN YOUR WAY IN</div>
   <nav aria-label="Main navigation">{items.map(([to,label,Icon])=><NavLink key={to} to={to} end={to==='/app'} className={linkClass} title={collapsed?label:undefined}><Icon size={18}/><span>{label}</span></NavLink>)}{user?.role==='CREATOR'&&<><NavLink to="/app/project-analytics" className={linkClass} title={collapsed?'Project Analytics':undefined}><BarChart3 size={18}/><span>Project Analytics</span></NavLink><NavLink to="/app/templates" className={linkClass} title={collapsed?'Templates':undefined}><FileStack size={18}/><span>Templates</span></NavLink></>}{user?.role==='ADMIN'&&<NavLink to="/app/admin" className={linkClass} title={collapsed?'Admin':undefined}><Shield size={18}/><span>Admin</span></NavLink>}</nav>
   <div className="sidebar-bottom"><div className="mini-profile"><div className="avatar">{user?.username?.slice(0,2).toUpperCase()}</div><div className="profile-copy"><strong>{user?.username}</strong><small>BagScore {user?.bag_score}</small></div></div><button className="icon-btn" title="Log out" aria-label="Log out" onClick={()=>{logout();nav('/')}}><LogOut size={18}/></button></div>
  </aside>
  {mobileOpen&&<button className="sidebar-backdrop" aria-label="Close menu" onClick={()=>setMobileOpen(false)}/>} 
  <main className="app-main"><div className="mobile-top"><button className="mobile-menu-btn" aria-label="Open navigation" onClick={()=>setMobileOpen(true)}><Menu size={21}/></button><Logo/><div className="pulse-pill"><Zap size={14}/> {user?.streak_days} day streak</div></div><div className="bag-z-app-feature-wrap"><BagZRouteFeature/></div><Outlet/></main>
 </div>
}
