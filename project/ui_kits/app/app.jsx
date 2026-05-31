// ============================================================================
// Echo Radar — App UI kit · root (state, screens, actions)
// ============================================================================

function ScopeBar({ data }) {
  const live = data.filter(m => m.status === 'new').length;
  const crit = data.filter(m => m.severity >= 75 && m.status === 'new').length;
  const rise = data.filter(m => m.severity >= 45 && m.severity < 75 && m.status === 'new').length;
  const Stat = ({ label, value, color }) => (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 7 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 16, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
      <Eyebrow>{label}</Eyebrow>
    </span>
  );
  return (
    <div className="er-scope">
      <span className="er-scope-live"><span className="er-pulse" />В эфире</span>
      <span className="er-scope-div" />
      <Stat label="сигналов" value={live} color="var(--fg-1)" />
      <Stat label="залетает" value={crit} color="#FF7A87" />
      <Stat label="растёт" value={rise} color="#FFC871" />
      <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)' }}>
        синхронизация 12 сек назад
      </span>
    </div>
  );
}

function App() {
  const [screen, setScreen] = React.useState('inbox');
  const [data, setData] = React.useState(DATA);
  const [selectedId, setSelectedId] = React.useState('m1');
  const [toast, setToast] = React.useState(null);

  const visible = data.filter(m => m.status !== 'rejected');
  const selected = data.find(m => m.id === selectedId);
  const prCount = data.filter(m => (m.lane === 'PR' || m.lane === 'none') && m.status === 'new').length;

  function flash(msg) { setToast(msg); clearTimeout(window.__erT); window.__erT = setTimeout(() => setToast(null), 2600); }

  function onAction(id, action) {
    setData(d => d.map(m => {
      if (m.id !== id) return m;
      if (action === 'approve') return { ...m, status: 'sent' };
      if (action === 'reject')  return { ...m, status: 'rejected' };
      if (action === 'pr')      return { ...m, lane: 'PR', status: 'new', humor: false };
      return m;
    }));
    if (action === 'approve') flash('Ответ отправлен · правка залогирована для tone-learning');
    if (action === 'reject')  { flash('Отклонено как шум'); const next = visible.find(m => m.id !== id); if (next) setSelectedId(next.id); }
    if (action === 'pr')      flash('Передано в PR — срочно');
  }

  return (
    <div className="er-app">
      <Sidebar screen={screen} setScreen={setScreen} prCount={prCount} />
      <div className="er-main">
        <TopBar
          title={screen === 'inbox' ? 'Инбокс' : 'Зонды'}
          sub={screen === 'inbox' ? 'две полосы · PR и SMM' : 'ключевые слова и хэштеги, по которым ищем упоминания'} />
        {screen === 'inbox' ? (
          <>
            <ScopeBar data={data} />
            <div className="er-workspace">
              <Inbox data={visible} selectedId={selectedId} onSelect={setSelectedId} />
              {selected
                ? <DetailPanel m={selected} onAction={onAction} />
                : <aside className="er-detail"><div className="er-empty" style={{ margin: 'auto' }}>Выберите упоминание</div></aside>}
            </div>
          </>
        ) : <ProbesScreen />}
      </div>
      {toast && <div className="er-toast"><Icon name="check" size={15} color="var(--sev-calm)" />{toast}</div>}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
