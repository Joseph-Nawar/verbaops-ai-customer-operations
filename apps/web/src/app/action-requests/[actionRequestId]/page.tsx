import { ActionRequestReview } from "@/components/action-request-review";

export default async function ActionRequestPage({
  params,
}: {
  params: Promise<{ actionRequestId: string }>;
}): Promise<React.JSX.Element> {
  const { actionRequestId } = await params;
  return <ActionRequestReview actionRequestId={actionRequestId} />;
}
