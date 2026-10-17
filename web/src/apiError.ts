type ValidationError = {
  loc?: unknown;
  msg?: unknown;
};

export function formatApiError(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== 'object') return String(item);
      const error = item as ValidationError;
      const location = Array.isArray(error.loc) ? error.loc.slice(1).join('.') : '';
      const message = typeof error.msg === 'string' ? error.msg : '';
      return [location, message].filter(Boolean).join('：');
    }).filter(Boolean);
    if (messages.length) return messages.join('；');
  }

  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }

  return fallback;
}
