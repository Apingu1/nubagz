import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Landing from './pages/Landing'
import Auth from './pages/Auth'
import WalletOnboarding from './pages/WalletOnboarding'
import AppShell from './components/AppShell'
import Dashboard from './pages/Dashboard'
import BagWork from './pages/BagWork'
import BagDetail from './pages/BagDetail'
import ChallengeDetail from './pages/ChallengeDetail'
import Notifications from './pages/Notifications'
import ActivityFeed from './pages/ActivityFeed'
import Swaps from './pages/Swaps'
import BagDrops from './pages/BagDrops'
import TrustCenter from './pages/TrustCenter'
import Reports from './pages/Reports'
import AccountTrust from './pages/AccountTrust'
import MyBag from './pages/MyBag'
import ProjectAnalytics from './pages/ProjectAnalytics'
import Leaderboard from './pages/Leaderboard'
import CreatorStudio from './pages/CreatorStudio'
import CreateProject from './pages/CreateProject'
import CreateChallenge from './pages/CreateChallenge'
import Admin from './pages/Admin'
import { useAuth } from './context/AuthContext'

function Protected({children}:{children:ReactNode}){const {user,loading}=useAuth();if(loading)return <div className="boot">NUBAGZ<span>↗</span></div>;return user?<>{children}</>:<Navigate to="/login" replace/>}
function AdminOnly(){const {user}=useAuth();return user?.role==='ADMIN'?<Admin/>:<Navigate to="/app" replace/>}
function LegacyChallengeBuilderRedirect(){const location=useLocation();return <Navigate to={`/app/studio/challenges/new${location.search}`} replace/>}

export default function App(){return <Routes>
 <Route path="/" element={<Landing/>}/>
 <Route path="/login" element={<Auth mode="login"/>}/>
 <Route path="/register" element={<Auth mode="register"/>}/>
 <Route path="/wallet-setup" element={<Protected><WalletOnboarding/></Protected>}/>
 <Route path="/app" element={<Protected><AppShell/></Protected>}>
  <Route index element={<Dashboard/>}/>
  <Route path="work" element={<BagWork/>}/>
  <Route path="daily" element={<Navigate to="/app/work?view=for-you" replace/>}/>
  <Route path="for-you" element={<Navigate to="/app/work?view=for-you" replace/>}/>
  <Route path="discover" element={<Navigate to="/app/work?view=all" replace/>}/>
  <Route path="trending" element={<Navigate to="/app/work?view=trending" replace/>}/>
  <Route path="watchbag" element={<Navigate to="/app/work?view=watchlist" replace/>}/>
  <Route path="notifications" element={<Notifications/>}/>
  <Route path="activity" element={<ActivityFeed/>}/>
  <Route path="swaps" element={<Swaps/>}/>
  <Route path="gas" element={<Navigate to="/app/work?category=ONCHAIN" replace/>}/>
  <Route path="onchain" element={<Navigate to="/app/work?category=ONCHAIN" replace/>}/>
  <Route path="drops" element={<BagDrops/>}/>
  <Route path="bounties" element={<Navigate to="/app/work?view=all" replace/>}/>
  <Route path="revenue-share" element={<Navigate to="/app/studio" replace/>}/>
  <Route path="trust" element={<TrustCenter/>}/>
  <Route path="reports" element={<Reports/>}/>
  <Route path="account-trust" element={<AccountTrust/>}/>
  <Route path="challenges/:id" element={<ChallengeDetail/>}/>
  <Route path="bagz/:id" element={<BagDetail/>}/>
  <Route path="bag" element={<MyBag/>}/>
  <Route path="earnings" element={<Navigate to="/app/bag?section=rewards" replace/>}/>
  <Route path="referrals" element={<Navigate to="/app/bag?section=invites" replace/>}/>
  <Route path="builders" element={<Navigate to="/app/studio" replace/>}/>
  <Route path="project-analytics" element={<ProjectAnalytics/>}/>
  <Route path="templates" element={<Navigate to="/app/studio/challenges/new" replace/>}/>
  <Route path="leaderboard" element={<Leaderboard/>}/>
  <Route path="studio" element={<CreatorStudio/>}/>
  <Route path="studio/projects/new" element={<CreateProject/>}/>
  <Route path="studio/challenges/new" element={<CreateChallenge/>}/>
  <Route path="studio/campaigns/new" element={<LegacyChallengeBuilderRedirect/>}/>
  <Route path="admin" element={<AdminOnly/>}/>
 </Route>
 <Route path="*" element={<Navigate to="/"/>}/>
 </Routes>}
