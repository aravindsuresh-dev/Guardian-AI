import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import ReportPage from "./pages/ReportPage";
import ReviewPage from "./pages/ReviewPage";
import UploadPage from "./pages/UploadPage";
import { ReviewProvider } from "./state/ReviewContext";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ReviewProvider>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ReviewProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
