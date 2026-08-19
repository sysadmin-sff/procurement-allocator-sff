import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './layout/AppLayout';
import {
  AllocationResultPage,
  MaterialsPage,
  OrderDetailPage,
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
