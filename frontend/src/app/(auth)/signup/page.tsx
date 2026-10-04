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
  const [otpExpiry, setOtpExpiry] = useState(15);

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

      if (!response.ok) {
        const errorData = await response.json();
        setError(
          errorData.error?.message ||
            errorData.detail?.message ||
            "Signup failed"
        );
        setLoading(false);
        return;
      }

      const data = await response.json();
      setTenantId(data.data.tenant_id);
      setOtpExpiry(data.data.otp_expires_in_minutes);
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

      if (!response.ok) {
        const errorData = await response.json();
        setError(
          errorData.error?.message ||
            errorData.detail?.message ||
            "Verification failed"
        );
        setLoading(false);
        return;
      }

      const data = await response.json();
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">SMART Inventory</h1>
          <p className="text-slate-300">
            {step === "info"
              ? "Create your account"
              : step === "verify"
                ? "Verify your email"
                : "Welcome to SMART"}
          </p>
        </div>

        {step === "info" && (
          <form
            onSubmit={handleSignup}
            className="bg-slate-800 border border-slate-700 rounded-lg p-6 space-y-4"
          >
            {error && (
              <div className="p-3 bg-red-600 text-white rounded text-sm">
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-white mb-2">
                Company Name
              </label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                placeholder="Your Company"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                placeholder="Minimum 8 characters"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">
                Confirm Password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                placeholder="Re-enter password"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-white mb-2">
                  Organization Type
                </label>
                <select
                  value={orgType}
                  onChange={(e) => setOrgType(e.target.value)}
                  className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="PRODUCER">Producer</option>
                  <option value="RETAILER">Retailer</option>
                  <option value="HYBRID">Hybrid</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-white mb-2">
                  Plan Tier
                </label>
                <select
                  value={planTier}
                  onChange={(e) => setPlanTier(e.target.value)}
                  className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded text-white focus:outline-none focus:border-blue-500"
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
              className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium transition-colors disabled:opacity-50"
            >
              {loading ? "Creating account..." : "Continue"}
            </button>

            <p className="text-center text-sm text-slate-400">
              Already have an account?{" "}
              <Link href="/login" className="text-blue-400 hover:text-blue-300">
                Sign in
              </Link>
            </p>
          </form>
        )}

        {step === "verify" && (
          <form
            onSubmit={handleVerify}
            className="bg-slate-800 border border-slate-700 rounded-lg p-6 space-y-4"
          >
            {error && (
              <div className="p-3 bg-red-600 text-white rounded text-sm">
                {error}
              </div>
            )}

            <div className="p-3 bg-blue-900 text-blue-100 rounded text-sm">
              A verification code has been sent to <strong>{email}</strong>
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">
                Verification Code
              </label>
              <input
                type="text"
                maxLength={6}
                value={otp}
                onChange={(e) =>
                  setOtp(e.target.value.replace(/[^\d]/g, ""))
                }
                className="w-full px-4 py-2 text-center text-2xl tracking-widest bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
                placeholder="000000"
              />
              <p className="text-xs text-slate-400 mt-2">
                Expires in {otpExpiry} minutes
              </p>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium transition-colors disabled:opacity-50"
            >
              {loading ? "Verifying..." : "Verify Email"}
            </button>

            <button
              type="button"
              onClick={() => setStep("info")}
              className="w-full px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded font-medium transition-colors"
            >
              Back
            </button>
          </form>
        )}

        {step === "complete" && (
          <div className="bg-green-900 border border-green-700 rounded-lg p-6 text-center space-y-4">
            <div className="text-4xl">✅</div>
            <h2 className="text-xl font-bold text-white">Welcome to SMART!</h2>
            <p className="text-green-100">
              Your email has been verified. Redirecting to setup...
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
