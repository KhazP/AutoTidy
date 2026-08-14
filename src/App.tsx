import { AppShell } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Toasts } from "./components/Toasts";
import { ConfigProvider } from "./state/ConfigProvider";
import { EngineProvider } from "./state/EngineProvider";
import { ToastProvider } from "./state/ToastProvider";

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <ConfigProvider>
          <EngineProvider>
            <AppShell />
            <Toasts />
          </EngineProvider>
        </ConfigProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
