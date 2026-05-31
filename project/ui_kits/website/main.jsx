// ============================================================================
// Echo Radar — Website kit · root composition
// ============================================================================
function Site() {
  return (
    <React.Fragment>
      <Header />
      <main>
        <Hero />
        <Stakes />
        <Pipeline />
        <SeverityDemo />
        <Platforms />
        <HumanLoop />
        <Pricing />
        <CTABand />
      </main>
      <Footer />
    </React.Fragment>
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(<Site />);
