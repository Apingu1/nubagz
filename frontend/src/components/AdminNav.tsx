import { NavLink } from 'react-router-dom'
import { LayoutDashboard, ShieldCheck, UsersRound } from 'lucide-react'

export function AdminNav(){
  const linkClass=({isActive}:{isActive:boolean})=>isActive?'admin-subnav-link active':'admin-subnav-link'
  return <nav className="admin-subnav" aria-label="Admin workspace navigation">
    <NavLink to="/app/admin" end className={linkClass}><LayoutDashboard size={16}/><span>Overview</span></NavLink>
    <NavLink to="/app/admin/users" className={linkClass}><UsersRound size={16}/><span>Users & Trust</span></NavLink>
    <NavLink to="/app/admin/security" className={linkClass}><ShieldCheck size={16}/><span>Security & Audit</span></NavLink>
  </nav>
}