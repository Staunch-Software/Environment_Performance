import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { SidebarProvider } from './context/SidebarContext';
import { ToastProvider } from './context/ToastContext';
import ProtectedRoute from './components/Layout/ProtectedRoute';

import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Vessels from './pages/Vessels';
import Uploads from './pages/Uploads';
import UploadDetail from './pages/UploadDetail';
import Entries from './pages/Entries';
import Alerts from './pages/Alerts';
import DailyLog from './pages/DailyLog';
import AdminLayout from './pages/admin/AdminLayout';
import UserManagement from './pages/admin/UserManagement';
import VesselConfiguration from './pages/admin/VesselConfiguration';

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
      <SidebarProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/vessels" element={<ProtectedRoute><Vessels /></ProtectedRoute>} />
          <Route path="/uploads" element={<ProtectedRoute><Uploads /></ProtectedRoute>} />
          <Route path="/uploads/:id" element={<ProtectedRoute><UploadDetail /></ProtectedRoute>} />
          <Route path="/entries" element={<ProtectedRoute><Entries /></ProtectedRoute>} />
          <Route path="/alerts" element={<ProtectedRoute><Alerts /></ProtectedRoute>} />
          <Route path="/daily-log" element={<ProtectedRoute><DailyLog /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute adminOnly><AdminLayout /></ProtectedRoute>}>
            <Route index element={<Navigate to="/admin/users" replace />} />
            <Route path="users" element={<UserManagement />} />
            <Route path="vessels" element={<VesselConfiguration />} />
          </Route>
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
      </SidebarProvider>
      </ToastProvider>
    </AuthProvider>
  );
}
