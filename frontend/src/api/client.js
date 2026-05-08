/**
 * Axios HTTP client instance.
 *
 * - baseURL proxied via Vite to Django backend
 * - Auto-attaches auth token from localStorage
 * - Clears token on 401 responses
 */
import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor: attach auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('nepse_token');
  if (token) {
    config.headers.Authorization = `Token ${token}`;
  }
  return config;
});

// Response interceptor: handle 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('nepse_token');
      localStorage.removeItem('nepse_user');
    }
    return Promise.reject(error);
  }
);

export default api;
