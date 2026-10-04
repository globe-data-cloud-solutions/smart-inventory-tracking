"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

type SignupStep = "info" | "verify" | "complete";

export default function SignupPage() {
  const router = useRouter();
  const [step, setStep] = useState<SignupStep>("info");
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [orgType, setOrgType] = useState("PRODUCER");
  const [planTier, setPlanTier] = useState("STARTER");
  const [otp, setOtp] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    if (!companyName.trim()) {
      setError("Company name is required");
      setLoading(false);
      return;
    }
    if (!email.includes("@")) {
      setError("Please enter a valid email");
      setLoading(false);
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      setLoading(false);
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      setLoading(false);
      return;
    }

    try {
      const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
      const response = await fetch(`${BASE_URL}/api/v1/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_name: companyName,
          email,
          password,
          organisation_type: orgType,
          plan_tier: planTier,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(
          data.error?.message ||
            data.detail?.message ||
            "Signup failed"
        );
        setLoading(false);
        return;
      }

      setTenantId(data.data.tenant_id);
      setStep("verify");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    if (!otp || otp.length !== 6) {
      setError("Please enter a 6-digit code");
      setLoading(false);
      return;
    }

    try {
      const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
      const response = await fetch(`${BASE_URL}/api/v1/auth/signup/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          email,
          otp_code: otp,
          password,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(
          data.error?.message ||
            data.detail?.message ||
            "Verification failed"
        );
        setLoading(false);
        return;
      }

      localStorage.setItem("access_token", data.data.access_token);
      localStorage.setItem("tenant_slug", data.data.tenant_slug);
      setStep("complete");

      setTimeout(() => {
        router.push(`/${data.data.tenant_slug}/onboard`);
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  };

  const containerStyle: React.CSSProperties = {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#1a1a1a",
    padding: "1rem",
  };

  const cardStyle: React.CSSProperties = {
    width: "100%",
    maxWidth: "400px",
    backgroundColor: "#2a2a2a",
    border: "1px solid #444",
    borderRadius: "8px",
    padding: "2rem",
  };

  const headingStyle: React.CSSProperties = {
    fontSize: "28px",
    fontWeight: "bold",
    color: "#fff",
    marginBottom: "8px",
    textAlign: "center",
  };

  const subheadingStyle: React.CSSProperties = {
    fontSize: "14px",
    color: "#aaa",
    textAlign: "center",
    marginBottom: "2rem",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "8px 12px",
    marginBottom: "1rem",
    backgroundColor: "#333",
    border: "1px solid #555",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "14px",
    boxSizing: "border-box",
  };

  const labelStyle: React.CSSProperties = {
    display: "block",
    fontSize: "13px",
    fontWeight: "500",
    color: "#fff",
    marginBottom: "4px",
  };

  const buttonStyle: React.CSSProperties = {
    width: "100%",
    padding: "10px",
    backgroundColor: "#0066cc",
    color: "#fff",
    border: "none",
    borderRadius: "4px",
    fontSize: "14px",
    fontWeight: "500",
    cursor: "pointer",
    marginTop: "1rem",
  };

  const errorStyle: React.CSSProperties = {
    padding: "10px",
    backgroundColor: "#663333",
    color: "#ffcccc",
    borderRadius: "4px",
    fontSize: "13px",
    marginBottom: "1rem",
  };

  return (
    <div style={containerStyle}>
      <div style={cardStyle}>
        <h1 style={headingStyle}>SMART Inventory</h1>
        <p style={subheadingStyle}>
          {step === "info"
            ? "Create your account"
            : step === "verify"
              ? "Verify your email"
              : "Welcome to SMART"}
        </p>

        {error && <div style={errorStyle}>{error}</div>}

        {step === "info" && (
          <form onSubmit={handleSignup}>
            <div>
              <label style={labelStyle}>Company Name</label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                style={inputStyle}
                placeholder="Your Company"
              />
            </div>

            <div>
              <label style={labelStyle}>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={inputStyle}
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label style={labelStyle}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={inputStyle}
                placeholder="Minimum 8 characters"
              />
            </div>

            <div>
              <label style={labelStyle}>Confirm Password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                style={inputStyle}
                placeholder="Re-enter password"
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "1rem" }}>
              <div>
                <label style={labelStyle}>Organization Type</label>
                <select
                  value={orgType}
                  onChange={(e) => setOrgType(e.target.value)}
                  style={inputStyle}
                >
                  <option value="PRODUCER">Producer</option>
                  <option value="RETAILER">Retailer</option>
                  <option value="HYBRID">Hybrid</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>Plan Tier</label>
                <select
                  value={planTier}
                  onChange={(e) => setPlanTier(e.target.value)}
                  style={inputStyle}
                >
                  <option value="STARTER">Starter</option>
                  <option value="GROWTH">Growth</option>
                  <option value="ENTERPRISE">Enterprise</option>
                </select>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                ...buttonStyle,
                opacity: loading ? 0.5 : 1,
              }}
            >
              {loading ? "Creating account..." : "Continue"}
            </button>

            <p style={{ textAlign: "center", fontSize: "13px", color: "#aaa", marginTop: "1rem" }}>
              Already have an account?{" "}
              <Link href="/login" style={{ color: "#0066cc" }}>
                Sign in
              </Link>
            </p>
          </form>
        )}

        {step === "verify" && (
          <form onSubmit={handleVerify}>
            <div style={{ padding: "10px", backgroundColor: "#334466", color: "#aaddff", borderRadius: "4px", fontSize: "13px", marginBottom: "1rem" }}>
              A verification code has been sent to <strong>{email}</strong>
            </div>

            <div>
              <label style={labelStyle}>Verification Code</label>
              <input
                type="text"
                maxLength={6}
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/[^\d]/g, ""))}
                style={{
                  ...inputStyle,
                  textAlign: "center",
                  fontSize: "24px",
                  letterSpacing: "8px",
                }}
                placeholder="000000"
              />
              <p style={{ fontSize: "12px", color: "#777", marginTop: "-8px", marginBottom: "1rem" }}>
                Expires in 15 minutes
              </p>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                ...buttonStyle,
                opacity: loading ? 0.5 : 1,
              }}
            >
              {loading ? "Verifying..." : "Verify Email"}
            </button>

            <button
              type="button"
              onClick={() => setStep("info")}
              style={{
                ...buttonStyle,
                backgroundColor: "#555",
                marginBottom: 0,
              }}
            >
              Back
            </button>
          </form>
        )}

        {step === "complete" && (
          <div style={{ textAlign: "center", padding: "2rem 0" }}>
            <div style={{ fontSize: "48px", marginBottom: "1rem" }}>✅</div>
            <h2 style={{ fontSize: "20px", fontWeight: "bold", color: "#fff", marginBottom: "0.5rem" }}>
              Welcome to SMART!
            </h2>
            <p style={{ color: "#aaa", fontSize: "13px" }}>
              Your email has been verified. Redirecting to setup...
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
