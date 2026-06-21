import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../../services/api';

export default function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode]         = useState('login'); // 'login' | 'register'
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      const fn = mode === 'login' ? api.login : api.register;
      const res = await fn(email.trim(), password);
      api.setToken(res.token);
      navigate('/app', { replace: true });
    } catch (err) {
      const msg = String(err.message || '');
      setError(
        msg.includes('401') ? 'Неверный email или пароль' :
        msg.includes('409') ? 'Этот email уже зарегистрирован' :
        msg.includes('400') ? 'Проверьте email и пароль (минимум 6 символов)' :
        'Не удалось подключиться к серверу'
      );
    } finally {
      setBusy(false);
    }
  }

  function useDemo() {
    setMode('login'); setEmail('demo@echo.app'); setPassword('demo12345'); setError('');
  }

  const input = {
    width: '100%', padding: '11px 13px', borderRadius: 'var(--r-md)',
    background: 'var(--surface-2)', border: '1px solid var(--line-2)',
    color: 'var(--fg-1)', fontSize: 14, fontFamily: 'var(--font-sans)', outline: 'none',
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)', padding: 24,
    }}>
      <form onSubmit={submit} style={{
        width: 380, maxWidth: '100%', background: 'var(--surface-1)',
        border: '1px solid var(--line-2)', borderRadius: 'var(--r-xl)', padding: 32,
        display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 'var(--r-md)', background: 'var(--brand)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round">
              <path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5M12 12h.01" />
            </svg>
          </div>
          <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--fg-1)' }}>Echo</span>
        </div>

        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--fg-1)' }}>
            {mode === 'login' ? 'Вход' : 'Регистрация'}
          </div>
          <div style={{ fontSize: 13, color: 'var(--fg-3)', marginTop: 2 }}>
            Мониторинг репутации бренда
          </div>
        </div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 12, color: 'var(--fg-2)', fontWeight: 600 }}>Email</span>
          <input style={input} type="email" value={email} autoComplete="email"
            onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required />
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 12, color: 'var(--fg-2)', fontWeight: 600 }}>Пароль</span>
          <input style={input} type="password" value={password}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            onChange={e => setPassword(e.target.value)} placeholder="••••••••" required />
        </label>

        {error && (
          <div style={{
            fontSize: 13, color: 'var(--neg)', background: 'var(--neg-dim)',
            border: '1px solid var(--neg-line)', borderRadius: 'var(--r-md)', padding: '8px 12px',
          }}>{error}</div>
        )}

        <button type="submit" disabled={busy} style={{
          width: '100%', padding: '11px', borderRadius: 'var(--r-md)',
          background: busy ? 'var(--surface-3)' : 'var(--brand)', color: '#fff',
          fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-sans)',
          border: 'none', cursor: busy ? 'default' : 'pointer',
        }}>
          {busy ? '…' : mode === 'login' ? 'Войти' : 'Создать аккаунт'}
        </button>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <button type="button" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}
            style={{ color: 'var(--brand-bright)', fontWeight: 600, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
            {mode === 'login' ? 'Нет аккаунта? Регистрация' : 'Уже есть аккаунт? Вход'}
          </button>
          <button type="button" onClick={useDemo}
            style={{ color: 'var(--fg-3)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 12 }}>
            Demo-доступ
          </button>
        </div>
      </form>
    </div>
  );
}
