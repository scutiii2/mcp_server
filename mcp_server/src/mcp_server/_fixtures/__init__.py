"""Dev fixtures - not real capabilities.

Everything under here exists to test mechanisms (like infra/extensions.py's
proxy) against a real, running process, without pulling in an external
dependency to do it. The leading underscore on the package name is
intentional: it marks this as test scaffolding, not something a deployment
would configure for actual use.
"""
