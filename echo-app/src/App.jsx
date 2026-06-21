import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Shell from './app/Shell';
import LoginPage from './core/auth/LoginPage';
import RequireAuth from './core/auth/RequireAuth';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/app" element={<RequireAuth><Shell /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/app" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
