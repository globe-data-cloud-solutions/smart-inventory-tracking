"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type SignupStep = "info" | "verify" | "complete";

export default function SignupPage() {
  const router = useRouter();
  const [step, setStep] = useState<SignupStep>("info");

  // Step 1: Company info
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [orgType, setOrgType] = useState("PRODUCER");
  const [planTier, setPlanTier] = useState("STARTER");

  // Step 2: OTP verification
  const [otp, setOtp] = useState("");
  const [tenantId, setTenantId] = useState("");

  // Shared state
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [otpExpiry, setOtpExpiry] = useState(15);

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    // Validation
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
      const response = await api.post("/api/v1/auth/signup", {
        company_name: companyName,
        email,
        password,
        organisation_type: orgType,
        plan_tier: planTier,
      });

      if (response.success) {
        setTenantId(response.data.tenant_id);
        setOtpExpiry(response.data.otp_expires_in_minutes);
        setStep("verify");
      } else {
        setError(response.error?.message || "Signup failed");
      }
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
      const response = await api.post("/api/v1/auth/signup/verify", {
        tenant_id: tenantId,
        email,
        otp_code: otp,
        password,
      });

      if (response.success) {
        // Store token
        localStorage.setItem("access_token", response.data.access_token);
        localStorage.setItem("tenant_slug", response.data.tenant_slug);
        setStep("complete");

        // Redirect to onboarding after 2 seconds
        setTimeout(() => {
          router.push(`/${response.data.tenant_slug}/onboard`);
        }, 2000);
      } else {
        setError(response.error?.message || "Verification failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Header */}
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

        {/* Step 1: Company Info */}
        {step === "info" && (
          <form onSubmit={handleSignup} className="bg-white/10 backdrop-blur border border-white/20 rounded-lg p-6 space-y-4">
            {error && (
              <div className="p-3 bg-red-500/20 border border-red-500/40 text-red-100 rounded text-sm">
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-white mb-2">Company Name</label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/20 rounded text-white placeholder-slate-400 focus:outline-none focus:border-brand-500"
                placeholder="Your Company"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/20 rounded text-white placeholder-slate-400 focus:outline-none focus:border-brand-500"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/20 rounded text-white placeholder-slate-400 focus:outline-none focus:border-brand-500"
                placeholder="Minimum 8 characters"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">Confirm Password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/20 rounded text-white placeholder-slate-400 focus:outline-none focus:border-brand-500"
                placeholder="Re-enter password"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-white mb-2">Organization Type</label>
                <select
                  value={orgType}
                  onChange={(e) => setOrgType(e.target.value)}
                  className="w-full px-4 py-2 bg-white/5 border border-white/20 rounded text-white focus:outline-none focus:border-brand-500"
                >
                  <option value="PRODUCER">Producer</option>
                  <option value="RETAILER">Retailer</option>
                  <option value="HYBRID">Hybrid</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-white mb-2">Plan Tier</label>
                <select
                  value={planTier}
                  onChange={(e) => setPlanTier(e.target.value)}
                  className="w-full px-4 py-2 bg-white/5 border border-white/20 rounded text-white focus:outline-none focus:border-brand-500"
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
              className="w-full px-4 py-2 bg-brand-600 hover:bg-brand-700 text-white rounded font-medium transition-colors disabled:opacity-50"
            >
              {loading ? "Creating account..." : "Continue"}
            </button>

            <p className="text-center text-sm text-slate-400">
              Already have an account?{" "}
              <Link href="/login" className="text-brand-400 hover:text-brand-300">
                Log in
              </Link>
            </p>
          </form>
        )}

        {/* Step 2: OTP Verification */}
        {step === "verify" && (
          <form onSubmit={handleVerify} className="bg-white/10 backdrop-blur border border-white/20 rounded-lg p-6 space-y-4">
            {error && (
              <div className="p-3 bg-red-500/20 border border-red-500/40 text-red-100 rounded text-sm">
                {error}
              </div>
            )}

            <div className="bg-blue-500/20 border border-blue-500/40 text-blue-100 rounded p-3 text-sm">
              A verification code has been sent to <strong>{email}</strong>
            </div>

            <div>
              <label className="block text-sm font-medium text-white mb-2">Verification Code</label>
              <input
                type="text"
                maxLength={6}
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/[^\d]/g, ""))}
                className="w-full px-4 py-2 text-center text-2xl tracking-widest bg-white/5 border border-white/20 rounded text-white placeholder-slate-400 focus:outline-none focus:border-brand-500"
                placeholder="000000"
              />
              <p className="text-xs text-slate-400 mt-2">Expires in {otpExpiry} minutes</p>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full px-4 py-2 bg-brand-600 hover:bg-brand-700 text-white rounded font-medium transition-colors disabled:opacity-50"
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

        {/* Step 3: Complete */}
        {step === "complete" && (
          <div className="bg-green-500/20 border border-green-500/40 rounded-lg p-6 text-center space-y-4">
            <div className="text-4xl">✅</div>
            <h2 className="text-xl font-bold text-white">Welcome to SMART!</h2>
            <p className="text-green-100">Your email has been verified. Redirecting to setup...</p>
          </div>
        )}
      </div>
    </div>
  );
}
