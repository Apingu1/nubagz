import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Trophy, BriefcaseBusiness, Shield, LogOut, WalletCards, Zap, BadgePoundSterling, Gift, ShieldCheck, UserRoundCheck, Network, Coins, Bell, BarChart3, FileStack, Scale, Activity, ArrowLeftRight, PanelLeftClose, PanelLeftOpen, Menu, X, ListChecks } from 'lucide-react'
import { usePrivy } from '@privy-io/react-auth'
import { Logo } from './Logo'
import { BagZRouteFeature } from './BagZMascot'
import { useAuth } from '../context/AuthContext'
import { privyConfigured } from '../context/WalletProvider'

function PrivyLogoutButton({finish}:{finish:()=>void}){const {logout}=usePrivy();return <button className="icon-btn" title="Log out" aria-label="Log out" onClick={()=>{void (async()=>{try{await logout()}finally{finish()}})()}}><LogOut size={18}/></button>}
function LogoutButton({finish}:{finish:()=>void}){return privyConfigured?<PrivyLogoutButton finish={finish}/>:<button className="icon-btn" title="Log out" aria-label="Log out" onClick={finish}><LogOut size={18}/></button>}

export default function AppShell(){
 const {user,logout}=useAuth();const nav=useNavigate();const location=useLocation()
 const [collapsed,setCollapsed]=useState(()=>{try{return localStorage.getItem('nubagz.sidebar.collapsed')!=='false'}catch{return true}})
 const [mobileOpen,setMobileOpen]=useState(false)
 useEffect(()=>{try{localStorage.setItem('nubagz.sidebar.collapsed',String(collapsed))}catch{}},[collapsed])
 useEffect(()=>{setMobileOpen(false)},[location.pathname])
 const finishLogout=()=>{logout();nav('/')}
 const coreItems=[['/app','Home',LayoutDashboard],['/app/bag','My Bag',WalletCards],['/app/work','Bag Work',ListChecks],['/app/drops','BagDrops',Gift],['/app/swaps','Swaps',ArrowLeftRight],['/app/earnings','Earnings',BadgePoundSterling]] as const
 const trustItems=[['/app/trust','Project Trust',ShieldCheck],['/app/account-trust','My Trust',UserRoundCheck],['/app/reports','Reports',Scale]] as const
 const accountItems=[['/app/notifications','Notifications',Bell],['/app/activity','Activity',Activity],['/app/referrals','Referrals',Network],['/app/leaderboard','Leaderboard',Trophy]] as const
 const buildItems=[['/app/studio','Creator Studio',BriefcaseBusiness],['/app/revenue-share','Revenue Share',Coins]] as const
 const linkClass=({isActive}:{isActive:boolean})=>isActive?'side-link active':'side-link'
 const renderItems=(items:readonly (readonly [string,string,any])[])=>items.map(([to,label,Icon])=><NavLink key={to} to={to} end={to==='/app'} className={linkClass} title={collapsed?label:undefined}><Icon size={18}/><span>{label}</span></NavLink>)
 return <div className={`app-shell ${collapsed?'sidebar-is-collapsed':''}`}><aside className={`sidebar ${collapsed?'collapsed':''} ${mobileOpen?'mobile-open':''}`}><div className="sidebar-top"><Logo/><button className="sidebar-close-mobile" aria-label="Close menu" onClick={()=>setMobileOpen(false)}><X size={20}/></button><button className="sidebar-collapse-btn" aria-label={collapsed?'Expand navigation':'Collapse navigation'} title={collapsed?'Expand navigation':'Collapse navigation'} onClick={()=>setCollapsed(v=>!v)}>{collapsed?<PanelLeftOpen size={18}/>:<PanelLeftClose size={18}/>}</button></div><div className="side-kicker">EARN YOUR WAY IN</div><nav aria-label="Main navigation"><div className="nav-section"><span className="nav-section-title">CORE</span>{renderItems(coreItems)}</div><div className="nav-section"><span className="nav-section-title">TRUST & SAFETY</span>{renderItems(trustItems)}</div><div className="nav-section"><span className="nav-section-title">ACCOUNT & COMMUNITY</span>{renderItems(accountItems)}</div><div className="nav-section"><span className="nav-section-title">BUILD</span>{renderItems(buildItems)}{user?.role==='CREATOR'&&<><NavLink to="/app/project-analytics" className={linkClass} title={collapsed?'Project Analytics':undefined}><BarChart3 size={18}/><span>Project Analytics</span></NavLink><NavLink to="/app/templates" className={linkClass} title={collapsed?'Templates':undefined}><FileStack size={18}/><span>Templates</span></NavLink></>}{user?.role==='ADMIN'&&<NavLink to="/app/admin" className={linkClass} title={collapsed?'Admin':undefined}><Shield size={18}/><span>Admin</span></NavLink>}</div></nav><div className="sidebar-bottom"><div className="mini-profile"><div className="avatar">{user?.username?.slice(0,2).toUpperCase()}</div><div className="profile-copy"><strong>{user?.username}</strong><small>BagScore {user?.bag_score}</small></div></div><LogoutButton finish={finishLogout}/></div></aside>{mobileOpen&&<button className="sidebar-backdrop" aria-label="Close menu" onClick={()=>setMobileOpen(false)}/>}<main className="app-main"><div className="mobile-top"><button className="mobile-menu-btn" aria-label="Open navigation" onClick={()=>setMobileOpen(true)}><Menu size={21}/></button><Logo/><div className="pulse-pill"><Zap size={14}/> {user?.streak_days} day streak</div></div><div className="bag-z-app-feature-wrap"><BagZRouteFeature/></div><Outlet/></main></div>
}
