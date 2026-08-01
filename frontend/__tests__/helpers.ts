import type { AuthUser } from "@/lib/types";

/** A signed-in identity for component tests. */
export function authUser(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    user_id: "u1",
    email: "buyer@example.com",
    full_name: "A Buyer",
    organization_id: "org-1",
    organization_name: "Example",
    role: "owner",
    ...overrides,
  };
}
