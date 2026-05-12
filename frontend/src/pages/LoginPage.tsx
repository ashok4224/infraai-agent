import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Shield, KeyRound, Mail, ArrowLeft } from 'lucide-react';
import api from '../api/client';

export default function LoginPage() {
  const { login, verifyMfa, resendMfa, cancelMfa, mfaPending, ssoProviders, localAuthEnabled } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [otpCode, setOtpCode] = useState('');
  const [resendCooldown, setResendCooldown] = useState(0);
  const otpInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      // If MFA is required, AuthContext sets mfaPending — don't navigate yet
      if (!mfaPending) navigate('/');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  };

  const handleMfaVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await verifyMfa(otpCode);
      navigate('/');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Invalid or expired OTP code');
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    try {
      await resendMfa();
      setResendCooldown(30);
      const timer = setInterval(() => {
        setResendCooldown((c) => {
          if (c <= 1) { clearInterval(timer); return 0; }
          return c - 1;
        });
      }, 1000);
    } catch {
      setError('Failed to resend code');
    }
  };

  const handleSSOLogin = async (providerId: string) => {
    try {
      const res = await api.get(`/sso/${providerId}/login`);
      window.location.href = res.data.redirect_url;
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'SSO login failed');
    }
  };

  // ── MFA OTP Verification Screen ─────────────────────────────────────
  if (mfaPending) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-500 via-brand-600 to-brand-800 px-4">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-white/20 backdrop-blur mb-4">
              <KeyRound className="h-8 w-8 text-white" />
            </div>
            <h1 className="text-3xl font-bold text-white">Verify Your Identity</h1>
            <p className="text-brand-200 mt-2 text-sm">
              A verification code was sent to <strong>{mfaPending.email}</strong>
            </p>
          </div>

          <form onSubmit={handleMfaVerify} className="card">
            <h2 className="text-xl font-bold text-gray-800 mb-2">Enter OTP Code</h2>
            <p className="text-sm text-gray-500 mb-6">Check your email for the 6-digit code</p>

            {error && (
              <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="mb-6">
              <input
                ref={otpInputRef}
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="input-field text-center text-2xl tracking-[0.5em] font-mono"
                placeholder="000000"
                autoFocus
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading || otpCode.length !== 6}
              className="btn-primary w-full disabled:opacity-50"
            >
              {loading ? 'Verifying...' : 'Verify'}
            </button>

            <div className="flex items-center justify-between mt-4">
              <button
                type="button"
                onClick={() => { cancelMfa(); setError(''); setOtpCode(''); }}
                className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1"
              >
                <ArrowLeft className="h-4 w-4" /> Back to login
              </button>
              <button
                type="button"
                onClick={handleResend}
                disabled={resendCooldown > 0}
                className="text-sm text-brand-600 hover:text-brand-700 disabled:text-gray-400"
              >
                {resendCooldown > 0 ? `Resend in ${resendCooldown}s` : 'Resend code'}
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  // ── Main Login Screen ────────────────────────────────────────────────
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-500 via-brand-600 to-brand-800 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-white/20 backdrop-blur mb-4">
            <Shield className="h-8 w-8 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white">InfraAI Agent</h1>
          <p className="text-brand-200 mt-1 text-sm tracking-widest uppercase">Winfo Solutions</p>
        </div>

        <div className="card">
          {localAuthEnabled && (
            <>
              <h2 className="text-xl font-bold text-gray-800 mb-6">Sign In</h2>

              {error && (
                <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit}>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="input-field"
                      placeholder="admin@winfosolutions.com"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="input-field"
                      placeholder="••••••••"
                      required
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full mt-6 disabled:opacity-50"
                >
                  {loading ? 'Signing in...' : 'Sign In'}
                </button>
              </form>
            </>
          )}

          {/* SSO Providers */}
          {ssoProviders.length > 0 && (
            <>
              {localAuthEnabled && (
                <div className="relative my-6">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-gray-200" />
                  </div>
                  <div className="relative flex justify-center text-sm">
                    <span className="bg-white px-3 text-gray-500">or continue with</span>
                  </div>
                </div>
              )}

              {!localAuthEnabled && (
                <>
                  <h2 className="text-xl font-bold text-gray-800 mb-6">Sign In with SSO</h2>
                  {error && (
                    <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                      {error}
                    </div>
                  )}
                </>
              )}

              <div className="space-y-3">
                {ssoProviders.map((provider) => (
                  <button
                    key={provider.id}
                    onClick={() => handleSSOLogin(provider.id)}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors font-medium"
                  >
                    <Mail className="h-5 w-5" />
                    {provider.name}
                    <span className="text-xs text-gray-400 ml-1">({provider.protocol.toUpperCase()})</span>
                  </button>
                ))}
              </div>
            </>
          )}

          {!localAuthEnabled && ssoProviders.length === 0 && (
            <div className="text-center py-8 text-gray-500">
              <p>No authentication providers configured.</p>
              <p className="text-sm mt-1">Contact your administrator.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
