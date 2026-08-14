import { Component, type ErrorInfo, type ReactNode } from "react";

import { errorMessage } from "../lib/errors";

interface Props {
  children: ReactNode;
}

interface State {
  error: string | null;
}

/**
 * Last resort. A rejected `invoke` is handled where it happens; this catches
 * genuine render bugs so the window shows a message instead of a white void.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: errorMessage(error) };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("AutoTidy UI crashed", error, info.componentStack);
  }

  override render() {
    if (this.state.error === null) return this.props.children;
    return (
      <div className="crash">
        <div className="notice notice--error" role="alert">
          <div className="notice__body">
            <span className="notice__title">AutoTidy hit an unexpected error</span>
            <pre>{this.state.error}</pre>
            <p className="muted" style={{ marginTop: 8 }}>
              Your configuration and history files were not touched by this failure.
            </p>
            <div className="btn-row" style={{ marginTop: 10 }}>
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => this.setState({ error: null })}
              >
                Try again
              </button>
              <button type="button" className="btn" onClick={() => window.location.reload()}>
                Reload window
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
