import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AuthProvider } from "./auth";
import { CatalogProvider } from "./catalog";
import { ToastProvider } from "./components/Toast";
import { SimProvider } from "./sim/SimContext";
import { ThemeProvider } from "./theme";
import "./styles/variables.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <SimProvider>
            <CatalogProvider>
              <App />
            </CatalogProvider>
          </SimProvider>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  </StrictMode>
);
