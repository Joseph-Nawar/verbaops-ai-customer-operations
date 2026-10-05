"use client";

import { useEffect, useState } from "react";

import { ActionRequestCard, loadActionView, type ActionRequestView } from "./action-request-card";

export function ActionRequestReview({ actionRequestId }: { actionRequestId: string }): React.JSX.Element {
  const [actionRequest, setActionRequest] = useState<ActionRequestView | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadActionView(actionRequestId)
      .then((view) => {
        if (!cancelled) setActionRequest(view);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [actionRequestId]);

  return (
    <main className="review-shell">
      <section className="review-card" aria-labelledby="review-title">
        <p className="eyebrow">Scoped action review</p>
        <h1 id="review-title">Action request</h1>
        {error ? <p role="alert">This action request is unavailable.</p> : null}
        {!error && actionRequest === null ? <p>Loading action request…</p> : null}
        {actionRequest ? (
          <ActionRequestCard actionRequest={actionRequest} onUpdated={setActionRequest} />
        ) : null}
      </section>
    </main>
  );
}
