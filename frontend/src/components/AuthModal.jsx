/**
 * AuthModal — Login / Register modal dialog.
 *
 * Tab-based switch between Login and Register.
 * Uses Zustand store for auth actions.
 */
import { useState } from 'react';
import { X, LogIn, UserPlus, AlertCircle } from 'lucide-react';
import useChatStore from '../store/chatStore';

export default function AuthModal({ isOpen, onClose }) {
  const { login, register } = useChatStore();
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (mode === 'login') {
        await login(username, password);
      } else {
        await register(username, password);
      }
      setUsername('');
      setPassword('');
      onClose();
    } catch (err) {
      const errData = err.response?.data;
      if (errData?.error) {
        setError(errData.error);
      } else if (errData?.errors) {
        // Flatten DRF validation errors
        const msgs = Object.values(errData.errors).flat();
        setError(msgs.join(' '));
      } else {
        setError('Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-md glass-card p-6 animate-slide-in-up">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 rounded-lg btn-ghost"
        >
          <X size={18} />
        </button>

        {/* Title */}
        <h2 className="text-xl font-bold gradient-text mb-1">
          {mode === 'login' ? 'Welcome Back' : 'Create Account'}
        </h2>
        <p className="text-sm text-surface-500 dark:text-surface-400 mb-6">
          {mode === 'login'
            ? 'Log in to save your conversation history'
            : 'Sign up to get started with NEPSE AI'}
        </p>

        {/* Tabs */}
        <div className="flex mb-6 bg-surface-100 dark:bg-surface-800 rounded-xl p-1">
          <button
            onClick={() => { setMode('login'); setError(''); }}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-sm font-medium transition-all
              ${mode === 'login'
                ? 'bg-white dark:bg-surface-700 text-brand-600 dark:text-brand-400 shadow-sm'
                : 'text-surface-500 dark:text-surface-400'
              }`}
          >
            <LogIn size={14} />
            Login
          </button>
          <button
            onClick={() => { setMode('register'); setError(''); }}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-sm font-medium transition-all
              ${mode === 'register'
                ? 'bg-white dark:bg-surface-700 text-brand-600 dark:text-brand-400 shadow-sm'
                : 'text-surface-500 dark:text-surface-400'
              }`}
          >
            <UserPlus size={14} />
            Register
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-start gap-2 mb-4 p-3 rounded-xl
                          bg-red-50 dark:bg-red-900/20
                          text-red-600 dark:text-red-400 text-sm">
            <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input-field"
              placeholder="Enter username"
              required
              minLength={3}
              autoComplete="username"
              id="auth-username"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
              placeholder="Enter password"
              required
              minLength={6}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              id="auth-password"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full btn-primary py-3 text-sm"
            id="auth-submit"
          >
            {loading
              ? 'Please wait...'
              : mode === 'login' ? 'Log In' : 'Create Account'
            }
          </button>
        </form>
      </div>
    </div>
  );
}
