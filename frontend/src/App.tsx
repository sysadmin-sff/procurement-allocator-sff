import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './layout/AppLayout';
import { RequireAdmin } from './auth/RequireAdmin';
import { RequireAuth } from './auth/RequireAuth';
import {
  AllocationResultPage,
  CategoriesPage,
  LoginPage,
  MaterialsPage,
  MeasurementsPage,
  MeasurementVisitsPage,
  OrderDetailPage,
  PriceComparisonPage,
  PriceListImportReviewPage,
  PriceMatrixPage,
  ProjectBuilderPage,
  ProjectRouterPage,
  ProjectsListPage,
  ProjectTemplatesPage,
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
        <Route path="/prices" element={<RequireAdmin><PriceMatrixPage /></RequireAdmin>} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/categories" element={<RequireAdmin><CategoriesPage /></RequireAdmin>} />
        <Route path="/suppliers" element={<SuppliersPage />} />
        <Route path="/suppliers/:supplierId" element={<SupplierDetailPage />} />
        <Route path="/users" element={<RequireAdmin><UsersPage /></RequireAdmin>} />
        <Route path="/project-templates" element={<ProjectTemplatesPage />} />
        <Route path="/measurements" element={<MeasurementsPage />} />
        <Route path="/measurements/visits" element={<MeasurementVisitsPage />} />
      </Route>
    </Routes>
  );
}

export default App;
