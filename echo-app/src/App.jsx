import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AppPage from './pages/AppPage';
import LoginPage from './pages/LoginPage';
import { getToken } from './services/api';

function RequireAuth({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/app" element={<RequireAuth><AppPage /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/app" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
