import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ToastProvider } from "./components/Toast";
import { ThemeProvider } from "./theme";
import "./styles/variables.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </ThemeProvider>
  </StrictMode>
);
