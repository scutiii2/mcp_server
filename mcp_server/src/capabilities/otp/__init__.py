"""Email-delivered one-time passcodes.

Two tools that only mean something together: one sends a code to an
inbox, the other checks what someone typed back. The point of the pair is
that the assistant driving them can never see the code - it can prove a
person read a specific inbox, and it can do nothing with that proof
except report it.
"""

# See infra/capability_metadata.py's docstring for what this does and
# why it's optional. No COMMAND_ID - "otp" is already as short as this
# id needs to be, so it falls back to the real id.
TITLE = "OTP"
