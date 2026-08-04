"""Authentication request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Long enough to resist offline guessing, capped so a huge body cannot tie up argon2.
MINIMUM_PASSWORD_LENGTH = 12
MAXIMUM_PASSWORD_LENGTH = 128


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(
        ..., min_length=MINIMUM_PASSWORD_LENGTH, max_length=MAXIMUM_PASSWORD_LENGTH
    )
    full_name: Optional[str] = Field(None, max_length=200)
    # Without one, registration creates a new organization. It never joins an existing
    # tenant on the strength of a matching email domain.
    invitation_token: Optional[str] = Field(None, max_length=128)


class InvitationRequest(BaseModel):
    email: EmailStr
    role: str = Field("member", max_length=20)


class InvitationResponse(BaseModel):
    email: str
    role: str
    expires_at: datetime
    # Returned once, at creation. Phase 4 delivers it by email instead; until there is
    # a mail transport, the inviting admin passes it on.
    token: str


class LoginRequest(BaseModel):
    email: EmailStr
    # Not length-validated: a short submission must fail as "wrong credentials", not as a
    # validation error that confirms the rule while revealing nothing about the account.
    password: str = Field(..., max_length=MAXIMUM_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    full_name: Optional[str] = None
    organization_id: str
    organization_name: str
    role: str


class TokenResponse(BaseModel):
    """Access token plus the identity it belongs to.

    The refresh token is deliberately absent: it travels only as an httpOnly cookie, so
    JavaScript — and therefore any injected script — cannot read it.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
