import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './layout/AppLayout';
import {
  AllocationResultPage,
  MaterialsPage,
  PriceReviewPage,
  ProjectBuilderPage,
  ProjectDetailPage,
  ProjectsListPage,
  SuppliersPage,
} from './routes';

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsListPage />} />
        <Route path="/projects/new" element={<ProjectBuilderPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="/projects/:projectId/allocation" element={<AllocationResultPage />} />
        <Route path="/price-review" element={<PriceReviewPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/suppliers" element={<SuppliersPage />} />
      </Route>
    </Routes>
  );
}

export default App;
