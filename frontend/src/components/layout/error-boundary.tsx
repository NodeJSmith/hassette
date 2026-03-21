import { Component, type ComponentChildren } from "preact";

interface Props {
  children: ComponentChildren;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div class="ht-card" style={{ padding: "var(--ht-sp-6)", textAlign: "center" }}>
          <h2>Something went wrong</h2>
          <p class="ht-text-secondary">{this.state.error.message}</p>
          <button
            class="ht-btn ht-btn-primary"
            onClick={() => this.setState({ error: null })}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
