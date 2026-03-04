import React, { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element #root was not found in index.html');
}
const root = createRoot(rootElement);

function formatErrorDetails(errorLike) {
  if (!errorLike) return 'Unknown frontend startup error.';
  if (errorLike instanceof Error) {
    return `${errorLike.name}: ${errorLike.message}${errorLike.stack ? `\n\n${errorLike.stack}` : ''}`;
  }
  if (typeof errorLike === 'string') return errorLike;
  try {
    return JSON.stringify(errorLike, null, 2);
  } catch {
    return String(errorLike);
  }
}

function FatalScreen({ title, details }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f8fafc',
        color: '#0f172a',
        padding: 24,
        fontFamily: 'Inter, system-ui, sans-serif',
      }}
    >
      <div
        style={{
          width: 'min(900px, 100%)',
          background: '#ffffff',
          border: '1px solid #cbd5e1',
          borderRadius: 12,
          boxShadow: '0 8px 30px rgba(15, 23, 42, 0.08)',
          padding: 20,
        }}
      >
        <h2 style={{ margin: 0, fontSize: 20 }}>Frontend Startup Error</h2>
        <p style={{ margin: '8px 0 12px', color: '#475569', fontSize: 14 }}>{title}</p>
        <pre
          style={{
            margin: 0,
            padding: 12,
            background: '#0f172a',
            color: '#e2e8f0',
            borderRadius: 8,
            overflowX: 'auto',
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          {details}
        </pre>
      </div>
    </div>
  );
}

class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('RootErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.error) {
      return (
        <FatalScreen
          title="A render error occurred inside the React app."
          details={formatErrorDetails(this.state.error)}
        />
      );
    }
    return this.props.children;
  }
}

function renderFatal(title, errorLike) {
  root.render(<FatalScreen title={title} details={formatErrorDetails(errorLike)} />);
}

window.addEventListener('error', (event) => {
  if (event?.error) {
    renderFatal('Unhandled runtime error captured by window.onerror.', event.error);
  }
});

window.addEventListener('unhandledrejection', (event) => {
  renderFatal('Unhandled promise rejection during startup.', event?.reason);
});

async function boot() {
  try {
    const { default: App } = await import('./App.jsx');
    const isDev = import.meta.env.DEV;
    const appTree = isDev ? (
      <App />
    ) : (
      <StrictMode>
        <App />
      </StrictMode>
    );

    root.render(<RootErrorBoundary>{appTree}</RootErrorBoundary>);
  } catch (error) {
    renderFatal('Failed to import or initialize App.jsx.', error);
  }
}

void boot();
