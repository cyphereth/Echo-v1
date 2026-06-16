export function BrandGate({ hasToken, onLogin, onCreateBrand }) {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{
        width: 420,
        maxWidth: '100%',
        border: '1px solid var(--line-2)',
        borderRadius: 'var(--r-md)',
        background: 'var(--surface-1)',
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}>
        <div>
          <div style={{ color: 'var(--fg-1)', fontSize: 18, fontWeight: 800 }}>Брендовый сектор</div>
          <div style={{ color: 'var(--fg-3)', fontSize: 13, marginTop: 4 }}>
            Для мониторинга бренда нужен аккаунт и профиль бренда. Новостной сектор работает отдельно.
          </div>
        </div>
        <button
          onClick={hasToken ? onCreateBrand : onLogin}
          style={{
            height: 38,
            borderRadius: 'var(--r-md)',
            background: 'var(--brand)',
            color: '#fff',
            fontWeight: 800,
            fontSize: 13,
          }}
        >
          {hasToken ? 'Создать бренд' : 'Войти для бренда'}
        </button>
      </div>
    </div>
  );
}
