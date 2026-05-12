import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Shield } from 'lucide-react';
import api from '../api/client';

export default function SSOCallbackPage() {
  const { loginWithToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState('');

  useEffect(() => {
    const token = searchParams.get('token');
    const code = searchParams.get('code');

    if (token) {
      // Direct token (OIDC flow returns token via API, not URL — legacy compat)
      loginWithToken(token)
        .then(() => navigate('/', { replace: true }))
        .catch(() => setError('SSO authentication failed. Please try again.'));
    } else if (code) {
      // Exchange one-time code for JWT (SAML flow — avoids JWT in URL)
      api.post('/sso/exchange', null, { params: { code } })
        .then((res) => loginWithToken(res.data.access_token))
        .then(() => navigate('/', { replace: true }))
        .catch(() => setError('SSO authentication failed. Please try again.'));
    } else {
      setError('No authentication token received.');
    }
  }, []);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-500 via-brand-600 to-brand-800 px-4">
        <div className="w-full max-w-md card text-center">
          <Shield className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-gray-800 mb-2">Authentication Failed</h2>
          <p className="text-gray-600 mb-6">{error}</p>
          <button
            onClick={() => navigate('/login', { replace: true })}
            className="btn-primary"
          >
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-500 via-brand-600 to-brand-800">
      <div className="text-center text-white">
        <div className="animate-spin h-10 w-10 border-4 border-white border-t-transparent rounded-full mx-auto mb-4" />
        <p className="text-lg">Completing sign in...</p>
      </div>
    </div>
  );
}
