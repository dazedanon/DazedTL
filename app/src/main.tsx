import { createRoot } from "react-dom/client";
import App from "./app/App";
import { ApplicationProvider } from "./app/ApplicationProvider";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { reportRendererFailure } from "./app/rendererErrors";
import "./styles/index.css";
window.addEventListener("error", event => reportRendererFailure(event.error, "error"));
window.addEventListener("unhandledrejection", event => reportRendererFailure(event.reason, "unhandledrejection"));
createRoot(document.getElementById("root")!).render(
  <ErrorBoundary label="The interface">
    <ApplicationProvider>
      <App />
    </ApplicationProvider>
  </ErrorBoundary>,
);
