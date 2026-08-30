/**
 * Authentication module — calls the backend /api/auth/login endpoint.
 * JWT token is stored in localStorage and attached to all API requests.
 * NO hardcoded credentials in client code.
 */

const AUTH_TOKEN_KEY = "openads_token";
const AUTH_USER_KEY = "openads_user";

export function isAuthenticated() {
  return !!localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getSessionUser() {
  return localStorage.getItem(AUTH_USER_KEY) || "";
}

/**
 * Authenticate against the backend. Returns { ok, token?, error? }
 */
export async function login(username, password) {
  try {
    const backendUrl = process.env.REACT_APP_BACKEND_URL || "";
    const res = await fetch(`${backendUrl}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, error: body.detail || "Invalid credentials" };
    }

    const data = await res.json();
    localStorage.setItem(AUTH_TOKEN_KEY, data.token);
    localStorage.setItem(AUTH_USER_KEY, data.username);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: "Cannot connect to server" };
  }
}

export function logout() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
}
