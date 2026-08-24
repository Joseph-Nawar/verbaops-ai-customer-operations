import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Chat } from "./chat";

describe("Chat", () => {
  it("creates one conversation on the first send and reuses it later", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ conversation_id: "conversation-1" }), { status: 201 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            conversation_id: "conversation-1",
            run_id: "run-1",
            user_message: { id: "user-1", role: "user", content: "Where is my order?" },
            assistant_message: { id: "assistant-1", role: "assistant", content: "Please provide your order ID." },
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            conversation_id: "conversation-1",
            run_id: "run-2",
            user_message: { id: "user-2", role: "user", content: "order-1" },
            assistant_message: { id: "assistant-2", role: "assistant", content: "Your order is in transit." },
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    const input = screen.getByLabelText("Message");
    await user.type(input, "Where is my order?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Please provide your order ID.")).toBeInTheDocument();

    await user.type(input, "order-1");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Your order is in transit.")).toBeInTheDocument();

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/conversations", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/conversations/conversation-1/messages",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/conversations/conversation-1/messages",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("renders safe errors, supports retry, and resets the conversation", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ conversation_id: "conversation-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: "nope" } }), { status: 502 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            conversation_id: "conversation-1",
            run_id: "run-1",
            user_message: { id: "user-1", role: "user", content: "hello" },
            assistant_message: { id: "assistant-1", role: "assistant", content: "Hi" },
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    const input = screen.getByLabelText("Message");
    await user.type(input, "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not send that message.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Hi")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByText("Hi")).not.toBeInTheDocument();
  });

  it("disables duplicate submission and exposes the 8000-character boundary", async () => {
    const user = userEvent.setup();
    let resolveSend: ((response: Response) => void) | undefined;
    const pendingSend = new Promise<Response>((resolve) => {
      resolveSend = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ conversation_id: "conversation-1" }), { status: 201 }))
      .mockReturnValueOnce(pendingSend);
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    const input = screen.getByLabelText("Message");
    expect(input).toHaveAttribute("maxlength", "8000");
    await user.type(input, "hello");
    const send = screen.getByRole("button", { name: "Send" });
    await user.click(send);
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveSend?.(
      new Response(
        JSON.stringify({
          conversation_id: "conversation-1",
          run_id: "run-1",
          user_message: { id: "user-1", role: "user", content: "hello" },
          assistant_message: { id: "assistant-1", role: "assistant", content: "Hi" },
        }),
        { status: 200 },
      ),
    );
    expect(await screen.findByText("Hi")).toBeInTheDocument();
  });
});
