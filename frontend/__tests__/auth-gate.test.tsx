import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "@/components/auth-gate";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

const login = vi.hoisted(() => vi.fn());
const register = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ login, register }));

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ user: null, platformLanguage: "en" });
  login.mockReset();
  register.mockReset();
});

async function signIn(email: string, password: string) {
  await userEvent.type(screen.getByLabelText("Company email"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
}

describe("AuthGate", () => {
  it("signs in and stores the returned identity", async () => {
    login.mockResolvedValue(authUser());
    render(<AuthGate />);

    await signIn("buyer@example.com", "a-sufficiently-long-password");

    await waitFor(() =>
      expect(useUserStore.getState().user?.email).toBe("buyer@example.com"),
    );
    expect(login).toHaveBeenCalledWith("buyer@example.com", "a-sufficiently-long-password");
  });

  it("normalizes the email before sending it", async () => {
    login.mockResolvedValue(authUser());
    render(<AuthGate />);

    await signIn("  Buyer@Example.COM  ", "a-sufficiently-long-password");

    await waitFor(() => expect(login).toHaveBeenCalledWith("buyer@example.com", expect.any(String)));
  });

  it("reports bad credentials without revealing which part was wrong", async () => {
    login.mockRejectedValue({ response: { status: 401 } });
    render(<AuthGate />);

    await signIn("buyer@example.com", "wrong-password-here");

    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
    expect(useUserStore.getState().user).toBeNull();
  });

  it("explains a taken address on registration", async () => {
    register.mockRejectedValue({ response: { status: 409 } });
    render(<AuthGate />);

    await userEvent.click(screen.getByRole("button", { name: /Create one/ }));
    await userEvent.type(screen.getByLabelText("Company email"), "taken@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a-sufficiently-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already has an account");
  });

  it("rejects a short password before calling the server", async () => {
    render(<AuthGate />);

    await userEvent.click(screen.getByRole("button", { name: /Create one/ }));
    await userEvent.type(screen.getByLabelText("Company email"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("at least 12 characters");
    expect(register).not.toHaveBeenCalled();
  });

  it("reports the field named by a server validation error", async () => {
    register.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: [
            {
              loc: ["body", "email"],
              msg: "value is not a valid email address",
            },
          ],
        },
      },
    });
    render(<AuthGate />);

    await userEvent.click(screen.getByRole("button", { name: /Create one/ }));
    await userEvent.type(screen.getByLabelText("Company email"), "buyer@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a-sufficiently-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("valid company email");
    expect(screen.getByRole("alert")).not.toHaveTextContent("Password");
  });

  it("rejects a malformed email before calling the server", async () => {
    render(<AuthGate />);

    await signIn("not-an-email", "a-sufficiently-long-password");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });
});
