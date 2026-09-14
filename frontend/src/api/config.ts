/**
 * Shared API configuration. Single source of truth for the API base URL.
 *
 * In production (nginx), VITE_API_BASE_URL is unset and requests go to
 * the same origin at /api — Traefik routes them to the backend.
 * In local development, set VITE_API_BASE_URL=http://localhost:3001 in .env.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
