import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './layout/AppLayout';
import { RequireAuth } from './auth/RequireAuth';
import {
  AllocationResultPage,
  LoginPage,
  MaterialsPage,
  OrderDetailPage,
  PriceComparisonPage,
  PriceListImportReviewPage,
  ProjectBuilderPage,
  ProjectRouterPage,
  ProjectsListPage,
  PurchaseRecordsPage,
  SupplierDetailPage,
  SuppliersPage,
  UsersPage,
} from './routes';

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsListPage />} />
        <Route path="/projects/new" element={<ProjectBuilderPage />} />
        <Route path="/projects/:projectId" element={<ProjectRouterPage />} />
        <Route path="/projects/:projectId/allocation" element={<AllocationResultPage />} />
        <Route path="/projects/:projectId/purchases" element={<PurchaseRecordsPage />} />
        <Route path="/projects/:projectId/comparison" element={<PriceComparisonPage />} />
        <Route path="/orders/:orderId" element={<OrderDetailPage />} />
        <Route path="/price-list-imports/:importId" element={<PriceListImportReviewPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/suppliers" element={<SuppliersPage />} />
        <Route path="/suppliers/:supplierId" element={<SupplierDetailPage />} />
        <Route path="/users" element={<UsersPage />} />
      </Route>
    </Routes>
  );
}

export default App;
