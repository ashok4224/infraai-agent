import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import api from '../api/client';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  auth_source?: string;
  mfa_enabled?: boolean;
}

interface MfaPending {
  mfa_token: string;
  email: string;
}

interface SSOProvider {
  id: string;
  name: string;
  protocol: string;
  is_default: boolean;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  mfaPending: MfaPending | null;
  ssoProviders: SSOProvider[];
  localAuthEnabled: boolean;
  login: (email: string, password: string) => Promise<void>;
  verifyMfa: (otpCode: string) => Promise<void>;
  resendMfa: () => Promise<void>;
  cancelMfa: () => void;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({} as AuthContextType);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [mfaPending, setMfaPending] = useState<MfaPending | null>(null);
  const [ssoProviders, setSsoProviders] = useState<SSOProvider[]>([]);
  const [localAuthEnabled, setLocalAuthEnabled] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      api.get('/auth/me')
        .then((res) => setUser(res.data))
        .catch(() => localStorage.removeItem('token'))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }

    // Fetch SSO config (public endpoint)
    api.get('/sso/auth-config')
      .then((res) => {
        setSsoProviders(res.data.sso_providers || []);
        setLocalAuthEnabled(res.data.local_auth_enabled ?? true);
      })
      .catch(() => {});
  }, []);

  const login = async (email: string, password: string) => {
    const res = await api.post('/auth/login', { email, password });
    if (res.data.mfa_required) {
      setMfaPending({ mfa_token: res.data.mfa_token, email });
      return;
    }
    localStorage.setItem('token', res.data.access_token);
    const me = await api.get('/auth/me');
    setUser(me.data);
  };

  const verifyMfa = async (otpCode: string) => {
    if (!mfaPending) throw new Error('No MFA session');
    const res = await api.post('/mfa/verify', {
      mfa_token: mfaPending.mfa_token,
      otp_code: otpCode,
    });
    localStorage.setItem('token', res.data.access_token);
    setMfaPending(null);
    const me = await api.get('/auth/me');
    setUser(me.data);
  };

  const resendMfa = async () => {
    if (!mfaPending) return;
    await api.post(`/mfa/resend?mfa_token=${encodeURIComponent(mfaPending.mfa_token)}`);
  };

  const cancelMfa = () => setMfaPending(null);

  const loginWithToken = async (token: string) => {
    localStorage.setItem('token', token);
    const me = await api.get('/auth/me');
    setUser(me.data);
  };

  const logout = () => {
    localStorage.removeItem('token');
    setUser(null);
    setMfaPending(null);
  };

  return (
    <AuthContext.Provider value={{
      user, loading, mfaPending, ssoProviders, localAuthEnabled,
      login, verifyMfa, resendMfa, cancelMfa, loginWithToken, logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
