import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import AppPage from './pages/AppPage';
import WebsitePage from './pages/WebsitePage';

function Home() {
  return (
    <div style={{
      minHeight: '100vh', background: 'var(--bg-void)', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 32, fontFamily: 'var(--font-sans)',
    }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontWeight: 800, fontSize: 38, letterSpacing: '-0.03em', color: 'var(--fg-1)', marginBottom: 8 }}>
          Ech<span style={{ color: 'var(--brand-bright)' }}>o</span> Radar
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--fg-3)' }}>
          Выберите поверхность
        </div>
      </div>
      <div style={{ display: 'flex', gap: 16 }}>
        <Link to="/app" style={{
          display: 'flex', flexDirection: 'column', gap: 8, padding: '24px 32px', textDecoration: 'none',
          background: 'var(--surface-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-xl)',
          transition: 'border-color .12s, background .12s',
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--brand-line)'; e.currentTarget.style.background = 'var(--surface-2)'; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--line-2)'; e.currentTarget.style.background = 'var(--surface-1)'; }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--fg-1)' }}>Приложение</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>Диспетчерский инбокс</span>
        </Link>
        <Link to="/website" style={{
          display: 'flex', flexDirection: 'column', gap: 8, padding: '24px 32px', textDecoration: 'none',
          background: 'var(--surface-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-xl)',
          transition: 'border-color .12s, background .12s',
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--brand-line)'; e.currentTarget.style.background = 'var(--surface-2)'; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--line-2)'; e.currentTarget.style.background = 'var(--surface-1)'; }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--fg-1)' }}>Лендинг</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>Маркетинговый сайт</span>
        </Link>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/app" element={<AppPage />} />
        <Route path="/website" element={<WebsitePage />} />
      </Routes>
    </BrowserRouter>
  );
}
