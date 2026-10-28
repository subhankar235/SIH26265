import { Routes, Route, Navigate, Link } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import RoleGuard from '../components/common/RoleGuard';
import { InstitutionRegister, OfficialRegister, VerifyEmailPage, AcceptInvitePage, ForgotPasswordPage, ResetPasswordPage, ChangePasswordPage } from '../pages/auth/AuthPages';
import AdminAccounts from '../pages/admin/AdminAccounts';
import AdminInstitutions from '../pages/admin/AdminInstitutions';
import AdminDeliveryMonitor from '../pages/admin/AdminDeliveryMonitor';
import PublicLandingPage from '../pages/PublicLandingPage';
import BrandHeader from '../components/layout/BrandHeader';

const Login = lazy(() => import('../pages/auth/Login')),
  Mfa = lazy(() => import('../pages/auth/MfaVerify')),
  SuperAdminSetup = lazy(() => import('../pages/auth/SuperAdminSetup')),
  ID = lazy(() => import('../pages/institution/InstitutionDashboard')),
  Upload = lazy(() => import('../pages/institution/UploadFdr')),
  Fdrs = lazy(() => import('../pages/institution/MyFdrs')),
  Refund = lazy(() => import('../pages/institution/RefundClaim')),
  BD = lazy(() => import('../pages/bureau/BureauDashboard')),
  Queue = lazy(() => import('../pages/bureau/ScrutinyQueue')),
  Split = lazy(() => import('../pages/bureau/ScrutinySplitView')),
  Disc = lazy(() => import('../pages/bureau/DiscrepancyBoard')),
  Inst = lazy(() => import('../pages/bureau/InstitutionsList')),
  Audit = lazy(() => import('../pages/bureau/AuditLogs')),
  BureauRefunds = lazy(() => import('../pages/bureau/BureauRefunds'));
const WorkflowControlRoom = lazy(() => import('../pages/bureau/WorkflowControlRoom')),
  WorkflowExecution = lazy(() => import('../pages/bureau/WorkflowExecution')),
  ExceptionInbox = lazy(() => import('../pages/bureau/ExceptionInbox')),
  CommandCenter = lazy(() => import('../pages/bureau/CommandCenter'));
const InstitutionRegistrations = lazy(() => import('../pages/bureau/InstitutionRegistrations'));
const InstitutionDetail = lazy(() => import('../pages/institution/InstitutionOperations').then(m => ({ default: m.InstitutionFdrDetail }))),
  InstitutionRenewals = lazy(() => import('../pages/institution/InstitutionOperations').then(m => ({ default: m.InstitutionRenewals }))),
  InstitutionNotifications = lazy(() => import('../pages/institution/InstitutionOperations').then(m => ({ default: m.InstitutionNotifications }))),
  InstitutionAssistant = lazy(() => import('../pages/institution/InstitutionOperations').then(m => ({ default: m.InstitutionAssistant }))),
  ApprovalQueue = lazy(() => import('../pages/bureau/ApprovalQueue')),
  AdminRoles = lazy(() => import('../pages/admin/AdminPhase12').then(m => ({ default: m.AdminRoles }))),
  AdminDashboard = lazy(() => import('../pages/admin/AdminPhase12').then(m => ({ default: m.AdminDashboard }))),
  AdminRules = lazy(() => import('../pages/admin/AdminPhase12').then(m => ({ default: m.AdminRules }))),
  AdminHealth = lazy(() => import('../pages/admin/AdminPhase12').then(m => ({ default: m.AdminHealth }))),
  AdminJobs = lazy(() => import('../pages/admin/AdminPhase12').then(m => ({ default: m.AdminJobs }))),
  AdminOpsAgent = lazy(() => import('../pages/admin/AdminPhase12').then(m => ({ default: m.AdminOpsAgent }))),
  AdminAlerts = lazy(() => import('../pages/admin/AdminPhase12').then(m => ({ default: m.AdminAlerts }))),
  MLGovernance = lazy(() => import('../pages/admin/MLGovernance'));

function InstitutionRoutes() {
  return <RoleGuard roles={['institution']}><><Routes><Route index element={<ID/>}/><Route path="upload" element={<Navigate to="/institution/fdrs/new" replace/>}/><Route path="fdrs/new" element={<Upload/>}/><Route path="fdrs" element={<Fdrs/>}/><Route path="fdrs/:id" element={<InstitutionDetail/>}/><Route path="renewals" element={<InstitutionRenewals/>}/><Route path="releases" element={<Refund/>}/><Route path="refunds" element={<Navigate to="/institution/releases" replace/>}/><Route path="notifications" element={<InstitutionNotifications/>}/><Route path="command" element={<CommandCenter portalLabel="Institution · Read-only Command Center"/>}/><Route path="*" element={<Navigate to="/institution" replace/>}/></Routes><InstitutionAssistant/></></RoleGuard>;
}

function OfficialRoutes() {
  return <RoleGuard roles={['aicte_official']}><Routes><Route index element={<BD/>}/><Route path="queue" element={<Queue/>}/><Route path="registrations" element={<InstitutionRegistrations/>}/><Route path="scrutiny" element={<Navigate to="/official/queue" replace/>}/><Route path="scrutiny/:id" element={<Split/>}/><Route path="review/:id" element={<Split/>}/><Route path="discrepancies" element={<Disc/>}/><Route path="refunds" element={<BureauRefunds/>}/><Route path="approvals" element={<ApprovalQueue/>}/><Route path="institutions" element={<Inst/>}/><Route path="audit" element={<Audit/>}/><Route path="command" element={<CommandCenter/>}/><Route path="control-room" element={<WorkflowControlRoom/>}/><Route path="workflows" element={<WorkflowControlRoom/>}/><Route path="workflows/:id" element={<WorkflowExecution/>}/><Route path="exceptions" element={<ExceptionInbox/>}/><Route path="*" element={<Navigate to="/official" replace/>}/></Routes></RoleGuard>;
}

function AdminRoutes() {
  return <RoleGuard roles={['admin']}><Routes><Route index element={<AdminDashboard/>}/><Route path="dashboard" element={<AdminDashboard/>}/><Route path="users" element={<AdminAccounts/>}/><Route path="roles" element={<AdminRoles/>}/><Route path="registrations" element={<AdminAccounts registrations/>}/><Route path="official-registrations" element={<AdminAccounts registrations officialRegistrations/>}/><Route path="institutions" element={<AdminInstitutions/>}/><Route path="notifications" element={<AdminDeliveryMonitor/>}/><Route path="alerts" element={<AdminAlerts/>}/><Route path="jobs" element={<AdminJobs/>}/><Route path="health" element={<AdminHealth/>}/><Route path="rules" element={<AdminRules/>}/><Route path="ml" element={<MLGovernance/>}/><Route path="ops-agent" element={<AdminOpsAgent/>}/><Route path="command" element={<CommandCenter adminMode/>}/><Route path="audit" element={<Audit/>}/><Route path="*" element={<Navigate to="/admin" replace/>}/></Routes></RoleGuard>;
}

function LegacyBureauRoutes() {
  return <RoleGuard roles={['aicte_official','admin']}><Routes><Route index element={<BD/>}/><Route path="scrutiny" element={<Queue/>}/><Route path="scrutiny/:id" element={<Split/>}/><Route path="discrepancies" element={<Disc/>}/><Route path="refunds" element={<RoleGuard roles={['aicte_official']}><BureauRefunds/></RoleGuard>}/><Route path="institutions" element={<Inst/>}/><Route path="audit" element={<Audit/>}/><Route path="*" element={<Navigate to="/bureau" replace/>}/></Routes></RoleGuard>;
}

export default function AppRoutes() {
  return <Suspense fallback={<div className="p-8" role="status">Loading…</div>}><Routes>
    <Route path="/" element={<PublicLandingPage/>}/>
    <Route path="/login" element={<Login/>}/>
    <Route path="/institution/login" element={<Navigate to="/login?portal=institution" replace/>}/><Route path="/official/login" element={<Navigate to="/login?portal=official" replace/>}/><Route path="/admin/login" element={<Navigate to="/login?portal=admin" replace/>}/>
    <Route path="/super-admin/setup" element={<SuperAdminSetup/>}/>
    <Route path="/institution/register" element={<InstitutionRegister/>}/><Route path="/official/register" element={<OfficialRegister/>}/><Route path="/verify-email" element={<VerifyEmailPage/>}/><Route path="/accept-invite" element={<AcceptInvitePage/>}/><Route path="/forgot-password" element={<ForgotPasswordPage/>}/><Route path="/reset-password" element={<ResetPasswordPage/>}/><Route path="/account/change-password" element={<RoleGuard roles={['institution','aicte_official','admin']}><ChangePasswordPage/></RoleGuard>}/><Route path="/unauthorized" element={<main className="min-h-screen bg-slate-50"><BrandHeader rightSlot={<Link to="/login" className="rounded-lg px-3 py-2 text-sm font-semibold text-[#273544] hover:bg-[#F1F5FA]">Sign in</Link>}/><section className="mx-auto max-w-6xl px-5 py-12 sm:px-8"><h1 className="text-2xl font-bold">Access denied</h1><p className="mt-2">Your account is not permitted to open this page.</p></section></main>}/>
    <Route path="/mfa" element={<Mfa/>}/>
    <Route path="/institution/*" element={<InstitutionRoutes/>}/><Route path="/official/*" element={<OfficialRoutes/>}/><Route path="/admin/*" element={<AdminRoutes/>}/><Route path="/bureau/*" element={<LegacyBureauRoutes/>}/>
    <Route path="*" element={<Navigate to="/login" replace/>}/>
  </Routes></Suspense>;
}
