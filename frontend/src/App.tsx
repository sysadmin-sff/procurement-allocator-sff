import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './layout/AppLayout';
import {
  AllocationResultPage,
  MaterialsPage,
  OrderDetailPage,
  OrderPrintPage,
  PriceReviewPage,
  ProjectBuilderPage,
  ProjectRouterPage,
  ProjectsListPage,
  PurchaseRecordsPage,
  SupplierDetailPage,
  SuppliersPage,
} from './routes';

function App() {
  return (
    <Routes>
      {/* Outside AppLayout — no topbar/nav chrome on the printable document
          sent to the supplier (ADR-0007 п.6: a different reader than the
          rest of the app, sees a plain page, not the internal tool shell). */}
      <Route path="/orders/:orderId/print" element={<OrderPrintPage />} />
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsListPage />} />
        <Route path="/projects/new" element={<ProjectBuilderPage />} />
        <Route path="/projects/:projectId" element={<ProjectRouterPage />} />
        <Route path="/projects/:projectId/allocation" element={<AllocationResultPage />} />
        <Route path="/projects/:projectId/purchases" element={<PurchaseRecordsPage />} />
        <Route path="/orders/:orderId" element={<OrderDetailPage />} />
        <Route path="/price-review" element={<PriceReviewPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/suppliers" element={<SuppliersPage />} />
        <Route path="/suppliers/:supplierId" element={<SupplierDetailPage />} />
      </Route>
    </Routes>
  );
}

export default App;
