import type { Metadata } from "next";
import LoginForm from "@/components/auth/LoginForm";
import "./login.css";

export const metadata: Metadata = {
  title: "AIOS · Sign in",
  description: "Sign in to your AIOS workspace — admin, team or client.",
};

// The front door. Every admin, team-portal and client dashboard route is
// gated behind this page (see AuthGuard). The form itself is the client
// component below.
export default function LoginPage() {
  return <LoginForm />;
}
