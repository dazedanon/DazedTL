import { createRoot } from "react-dom/client";
import App from "./app/App";
import { ApplicationProvider } from "./app/ApplicationProvider";
import "./styles/index.css";
createRoot(document.getElementById("root")!).render(
  <ApplicationProvider>
    <App />
  </ApplicationProvider>,
);
