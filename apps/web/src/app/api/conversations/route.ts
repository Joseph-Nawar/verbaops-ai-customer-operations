import { forwardToVerbaOps, validationError } from "@/lib/server/verbaops";
import { isRecord, readJson } from "@/lib/server/request-validation";

export async function POST(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isRecord(body) || Object.keys(body).length !== 0) return validationError();
  return forwardToVerbaOps("v1/conversations", { method: "POST", body: JSON.stringify({}) });
}
