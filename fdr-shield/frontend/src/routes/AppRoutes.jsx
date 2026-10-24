import { Routes, Route, Navigate } from "react-router-dom";
import { lazy, Suspense } from "react";
import RoleGuard from "../components/common/RoleGuard";
const Login = lazy(() => import("../pages/auth/Login")),
  Mfa = lazy(() => import("../pages/auth/MfaVerify")),
  ID = lazy(() => import("../pages/institution/InstitutionDashboard")),
  Upload = lazy(() => import("../pages/institution/UploadFdr")),
  Fdrs = lazy(() => import("../pages/institution/MyFdrs")),
  Refund = lazy(() => import("../pages/institution/RefundClaim")),
  BD = lazy(() => import("../pages/bureau/BureauDashboard")),
  Queue = lazy(() => import("../pages/bureau/ScrutinyQueue")),
  Split = lazy(() => import("../pages/bureau/ScrutinySplitView")),
  Disc = lazy(() => import("../pages/bureau/DiscrepancyBoard")),
  Inst = lazy(() => import("../pages/bureau/InstitutionsList")),
  Audit = lazy(() => import("../pages/bureau/AuditLogs"));
const BureauRefunds = lazy(() => import("../pages/bureau/BureauRefunds"));
export default function AppRoutes() {
  return (
    <Suspense fallback={<div className="p-8">Loading…</div>}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/mfa" element={<Mfa />} />
        <Route
          path="/institution/*"
          element={
            <RoleGuard roles={["institution"]}>
              <Routes>
                <Route index element={<ID />} />
                <Route path="upload" element={<Upload />} />
                <Route path="fdrs" element={<Fdrs />} />
                <Route path="refunds" element={<Refund />} />
              </Routes>
            </RoleGuard>
          }
        />
        <Route
          path="/bureau/*"
          element={
            <RoleGuard roles={["aicte_official", "admin"]}>
              <Routes>
                <Route index element={<BD />} />
                <Route path="scrutiny" element={<Queue />} />
                <Route path="scrutiny/:id" element={<Split />} />
                <Route path="discrepancies" element={<Disc />} />
                <Route path="refunds" element={<RoleGuard roles={["aicte_official", "admin"]}><BureauRefunds /></RoleGuard>} />
                <Route path="institutions" element={<Inst />} />
                <Route path="audit" element={<Audit />} />
              </Routes>
            </RoleGuard>
          }
        />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Suspense>
  );
}
