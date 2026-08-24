import "server-only";

const REQUEST_TIMEOUT_MS = 8_000;
const JSON_HEADERS = {
  accept: "application/json",
  "content-type": "application/json",
};

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export type SafeError = {
  error: { code: string; message: string };
};

function safeUnavailable(): Response {
  return Response.json(
    { error: { code: "backend_unavailable", message: "The service is temporarily unavailable." } },
    { status: 503 },
  );
}

function safeProtocolFailure(): Response {
  return Response.json(
    { error: { code: "backend_unavailable", message: "The service is temporarily unavailable." } },
    { status: 503 },
  );
}

function redact(value: JsonValue, secret: string): JsonValue {
  if (typeof value === "string") return secret ? value.split(secret).join("[redacted]") : value;
  if (Array.isArray(value)) return value.map((item) => redact(item, secret));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redact(item, secret)]));
  }
  return value;
}

function configuredUrl(path: string): URL | null {
  const baseUrl = process.env.VERBAOPS_API_BASE_URL?.trim();
  if (!baseUrl) return null;
  try {
    return new URL(path.replace(/^\/+/, ""), `${baseUrl.replace(/\/+$/, "")}/`);
  } catch {
    return null;
  }
}

async function responseBody(response: Response, secret: string): Promise<JsonValue | null> {
  const text = await response.text();
  if (!text) return null;
  try {
    return redact(JSON.parse(text) as JsonValue, secret);
  } catch {
    return null;
  }
}

export async function forwardToVerbaOps(path: string, init: RequestInit): Promise<Response> {
  const token = process.env.VERBAOPS_API_TOKEN?.trim();
  const url = configuredUrl(path);
  if (!token || !url) return safeUnavailable();

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        ...JSON_HEADERS,
        ...(init.headers ?? {}),
        authorization: `Bearer ${token}`,
      },
    });
    const body = await responseBody(response, token);
    if (body === null && response.status >= 200 && response.status < 300) {
      return new Response(null, { status: response.status });
    }
    if (body === null) return safeProtocolFailure();
    return Response.json(body, { status: response.status });
  } catch {
    return safeUnavailable();
  } finally {
    clearTimeout(timeout);
  }
}

export function validationError(message = "The request is invalid."): Response {
  return Response.json({ error: { code: "request_validation_error", message } }, { status: 422 });
}
